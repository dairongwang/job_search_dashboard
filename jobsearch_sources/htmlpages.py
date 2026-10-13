"""Web-page provider: read job listings from ordinary HTML pages.

Three extraction strategies, tried in this order on every fetched page:

1. **schema.org JobPosting** structured data (``<script type="application/ld+json">``).
   Most careers pages and job boards embed it for Google for Jobs; it carries
   title, company, location, salary, employment type and posting date.
2. **CSS selectors** supplied by the user (``item_selector`` + field selectors)
   for listing pages without structured data.
3. **Link following**: when a listing page yields nothing itself, job-looking
   links are followed (politely, with a delay and a cap) and each detail page
   is parsed with strategy 1, falling back to Open Graph / ``<h1>`` metadata.

Every request is checked against the site's robots.txt first and sent with
an identifying User-Agent. When a page renders its listings with JavaScript
and Playwright/Chromium is installed, the page is loaded in a real headless
browser (``render`` option: auto | always | never) — see ``browser.py``.
A 401/403 from the site ends the run; it is never disguised around.
"""

from __future__ import annotations

import json
import re
import time
from datetime import date
from typing import Any
from urllib.parse import urljoin, urlsplit

from . import browser, robots
from .feeds import AccessDenied, NoListings, explain_fetch_error, known_site_guidance
from .http import FetchError, classify_body
from .model import Job, normalise_job_type, normalise_workplace, parse_date

try:  # BeautifulSoup is only needed for this provider
    from bs4 import BeautifulSoup
except ImportError:  # pragma: no cover - exercised only when bs4 is missing
    BeautifulSoup = None  # type: ignore[assignment]

DEFAULT_LINK_PATTERN = (
    r"/(jobs?|careers?|positions?|postings?|vacanc(?:y|ies)|openings?|opportunit(?:y|ies)|employment|viewjob|job-details?)"
    r"(/|\?|$)|[?&](job|jobid|job_id|posting|postingid|jk|id)="
)
_SKIP_LINK = re.compile(r"(login|signin|sign-in|register|apply|alert|/search|/category|/categories|/page/|/tag/|mailto:|javascript:|#)", re.IGNORECASE)


def _soup(html: str) -> "BeautifulSoup":
    if BeautifulSoup is None:
        raise ValueError("the web-page provider needs the 'beautifulsoup4' package (pip install beautifulsoup4).")
    return BeautifulSoup(html, "html.parser")


# ---------------------------------------------------------------------------
# schema.org JobPosting
# ---------------------------------------------------------------------------


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _name(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("name") or value.get("@id") or "")
    return str(value or "")


def _address_text(place: Any) -> str:
    if isinstance(place, str):
        return place
    if not isinstance(place, dict):
        return ""
    address = place.get("address") or place
    if isinstance(address, str):
        return address
    if isinstance(address, dict):
        parts = [address.get("addressLocality"), address.get("addressRegion"), _name(address.get("addressCountry"))]
        text = ", ".join(str(p).strip() for p in parts if p and str(p).strip())
        return text or str(address.get("name") or "")
    return ""


def _salary(base: Any, currency_hint: str) -> tuple[int | None, int | None, str, str]:
    if base is None:
        return None, None, "", ""
    if isinstance(base, (int, float)):
        return int(base), int(base), currency_hint, "year"
    if not isinstance(base, dict):
        return None, None, "", ""
    currency = str(base.get("currency") or currency_hint or "")
    value = base.get("value")
    unit = ""
    low = high = None
    if isinstance(value, dict):
        unit = str(value.get("unitText") or "")
        low = value.get("minValue")
        high = value.get("maxValue")
        if low is None and high is None and value.get("value") is not None:
            low = high = value.get("value")
    elif isinstance(value, (int, float, str)):
        low = high = value
    else:
        low, high = base.get("minValue"), base.get("maxValue")
        unit = str(base.get("unitText") or "")

    def to_int(v: Any) -> int | None:
        try:
            return int(float(str(v).replace(",", ""))) if v not in (None, "") else None
        except ValueError:
            return None

    period = {"HOUR": "hour", "DAY": "day", "WEEK": "week", "MONTH": "month", "YEAR": "year"}.get(unit.upper(), "")
    if period == "week":
        low, high, period = (to_int(low) or 0) * 52 or None, (to_int(high) or 0) * 52 or None, "year"
        return low, high, currency, period
    return to_int(low), to_int(high), currency, period


def jobposting_to_job(data: dict[str, Any], page_url: str, site_name: str, site_id: str, default_workplace: str = "") -> Job | None:
    title = str(data.get("title") or data.get("name") or "").strip()
    if not title:
        return None
    valid_through = parse_date(data.get("validThrough"))
    if valid_through and valid_through < date.today().isoformat():
        return None  # expired posting still present in the page
    locations = [_address_text(p) for p in _as_list(data.get("jobLocation"))]
    location = "; ".join(l for l in locations if l)
    location_type = " ".join(str(v) for v in _as_list(data.get("jobLocationType")))
    workplace = "remote" if "TELECOMMUTE" in location_type.upper() else normalise_workplace(f"{title} {location}", default_workplace)
    if workplace == "remote" and not location:
        requirements = [_name(r) for r in _as_list(data.get("applicantLocationRequirements"))]
        location = ", ".join(r for r in requirements if r) or "Remote"
    job_type, schedule = normalise_job_type(_as_list(data.get("employmentType")))
    salary_min, salary_max, currency, period = _salary(data.get("baseSalary"), str(data.get("salaryCurrency") or ""))
    identifier = data.get("identifier")
    if isinstance(identifier, dict):
        identifier = identifier.get("value") or identifier.get("name")
    url = str(data.get("url") or data.get("sameAs") or page_url or "")
    industry = ", ".join(str(v) for v in _as_list(data.get("industry")) + _as_list(data.get("occupationalCategory")) if v)
    return Job(
        title=title,
        organization=_name(data.get("hiringOrganization")),
        location=location,
        workplace=workplace,
        url=urljoin(page_url, url) if url else page_url,
        source=site_name,
        site_id=site_id,
        description=str(data.get("description") or ""),
        salary_min=salary_min,
        salary_max=salary_max,
        salary_currency=currency,
        salary_period=period,
        job_type=job_type,
        schedule=schedule,
        industry=industry,
        tags=[str(s) for s in _as_list(data.get("skills"))][:10] if data.get("skills") else [],
        published=parse_date(data.get("datePosted")),
        external_id=f"{site_id}:{identifier or url or title}",
    )


def _walk_jsonld(node: Any, postings: list[dict[str, Any]], links: list[str]) -> None:
    if isinstance(node, list):
        for item in node:
            _walk_jsonld(item, postings, links)
        return
    if not isinstance(node, dict):
        return
    types = [str(t).lower() for t in _as_list(node.get("@type"))]
    if "jobposting" in types:
        postings.append(node)
        return
    if "@graph" in node:
        _walk_jsonld(node["@graph"], postings, links)
    if "itemlist" in types or "itemListElement" in node:
        for element in _as_list(node.get("itemListElement")):
            if isinstance(element, dict):
                item = element.get("item")
                if isinstance(item, dict):
                    _walk_jsonld(item, postings, links)
                elif element.get("url"):
                    links.append(str(element["url"]))
                elif isinstance(item, str):
                    links.append(item)
    for key in ("mainEntity", "mainEntityOfPage", "about"):
        if isinstance(node.get(key), (dict, list)):
            _walk_jsonld(node[key], postings, links)


def extract_jsonld(html_or_soup: Any) -> tuple[list[dict[str, Any]], list[str]]:
    """Return (JobPosting dicts, listed item URLs) from a page's JSON-LD blocks."""
    soup = _soup(html_or_soup) if isinstance(html_or_soup, str) else html_or_soup
    postings: list[dict[str, Any]] = []
    links: list[str] = []
    for script in soup.find_all("script", attrs={"type": re.compile(r"application/ld\+json", re.I)}):
        raw = (script.string or script.get_text() or "").strip()
        raw = re.sub(r"^\s*<!\[CDATA\[|\]\]>\s*$", "", raw)
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            try:
                data = json.loads(re.sub(r",\s*([}\]])", r"\1", raw))  # tolerate trailing commas
            except json.JSONDecodeError:
                continue
        _walk_jsonld(data, postings, links)
    return postings, links


# ---------------------------------------------------------------------------
# CSS selectors & link discovery
# ---------------------------------------------------------------------------

FIELD_SELECTORS = ("title", "link", "company", "location", "salary", "date", "description", "job_type")


def _sel_text(node: Any, selector: str) -> str:
    if not selector:
        return ""
    try:
        found = node.select_one(selector)
    except Exception:  # invalid selector
        return ""
    return found.get_text(" ", strip=True) if found else ""


def _sel_href(node: Any, selector: str, base_url: str) -> str:
    target = None
    if selector:
        try:
            target = node.select_one(selector)
        except Exception:
            target = None
    if target is None:
        target = node if node.name == "a" else node.find("a", href=True)
    if target is None or not target.get("href"):
        return ""
    return urljoin(base_url, target["href"])


def extract_with_selectors(soup: Any, options: dict[str, Any], base_url: str) -> list[dict[str, str]]:
    item_selector = str(options.get("item_selector") or "").strip()
    if not item_selector:
        return []
    try:
        items = soup.select(item_selector)
    except Exception as exc:
        raise ValueError(f"invalid item selector '{item_selector}' ({exc}).") from exc
    rows: list[dict[str, str]] = []
    for node in items:
        row = {field: _sel_text(node, str(options.get(f"{field}_selector") or "")) for field in FIELD_SELECTORS if field != "link"}
        row["link"] = _sel_href(node, str(options.get("link_selector") or ""), base_url)
        if not row["title"]:
            row["title"] = _sel_text(node, "h1, h2, h3, h4, a") or node.get_text(" ", strip=True)[:120]
        if row["title"]:
            rows.append(row)
    return rows


def candidate_links(soup: Any, base_url: str, pattern: str = "") -> list[str]:
    regex = re.compile(pattern or DEFAULT_LINK_PATTERN, re.IGNORECASE)
    host = urlsplit(base_url).netloc
    found: list[str] = []
    for anchor in soup.find_all("a", href=True):
        href = urljoin(base_url, anchor["href"]).split("#", 1)[0]
        if urlsplit(href).netloc != host:
            continue
        if href.rstrip("/") == base_url.rstrip("/"):
            continue
        if not regex.search(href) or _SKIP_LINK.search(href):
            continue
        found.append(href)
    return list(dict.fromkeys(found))


def _meta(soup: Any, *names: str) -> str:
    for name in names:
        tag = soup.find("meta", attrs={"property": name}) or soup.find("meta", attrs={"name": name})
        if tag and tag.get("content"):
            return str(tag["content"]).strip()
    return ""


def extract_detail_fallback(soup: Any, url: str) -> dict[str, str]:
    """Best-effort fields from a job page without structured data."""
    title = _meta(soup, "og:title", "twitter:title")
    if not title:
        h1 = soup.find("h1")
        title = h1.get_text(" ", strip=True) if h1 else ""
    if not title and soup.title:
        title = soup.title.get_text(" ", strip=True)
    organization = _meta(soup, "og:site_name")
    if " - " in title and not organization:
        title, organization = title.rsplit(" - ", 1)
    elif " | " in title and not organization:
        title, organization = title.rsplit(" | ", 1)
    description = _meta(soup, "og:description", "description")
    if not description:
        main = soup.find("main") or soup.find("article") or soup.body
        description = main.get_text(" ", strip=True)[:1500] if main else ""
    return {"title": title.strip(), "organization": organization.strip(), "description": description, "url": url}


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


class _Fetcher:
    """Fetches pages for one site run: robots.txt, delays, static HTTP or browser rendering."""

    def __init__(self, ctx: Any):
        self.ctx = ctx
        self.clock: dict[str, float] = {}
        self.delay = float(ctx.options.get("delay_seconds") or 1)
        self.render_mode = str(ctx.options.get("render") or "auto")
        self.use_browser = self.render_mode == "always"
        self.browser_checked = False
        self.browser_ok = False
        self.browser_reason = ""
        self.skipped_by_robots = 0
        self.rendered_pages = 0
        self.last_render_error = ""

    def allowed(self, url: str) -> robots.Verdict:
        return robots.check(url, self.ctx.settings)

    def _pause(self, url: str, crawl_delay: float | None) -> None:
        host = urlsplit(url).netloc
        delay = max(self.delay, crawl_delay or 0)
        last = self.clock.get(host)
        if last is not None and delay > 0:
            wait = delay - (time.monotonic() - last)
            if wait > 0:
                time.sleep(wait)
        self.clock[host] = time.monotonic()

    def browser_available(self) -> bool:
        if not self.browser_checked:
            self.browser_checked = True
            self.browser_ok, self.browser_reason = browser.available()
        return self.browser_ok

    def static(self, url: str) -> str:
        verdict = self.allowed(url)
        if not verdict.allowed:
            raise AccessDenied(verdict.reason, transient=verdict.unreachable)
        self._pause(url, verdict.crawl_delay)
        try:
            return self.ctx.get_text(url)
        except FetchError as exc:
            if exc.status in (401, 403, 429):
                raise AccessDenied(explain_fetch_error(exc, url), exc.status) from exc
            raise ValueError(explain_fetch_error(exc, url)) from exc

    def rendered_with_steps(self, url: str, steps: list[dict[str, Any]]) -> list[str]:
        """Load ``url`` in a browser, drive the search form with ``steps`` and return the HTML snapshots."""
        verdict = self.allowed(url)
        if not verdict.allowed:
            raise AccessDenied(verdict.reason, transient=verdict.unreachable)
        self.last_render_error = ""
        pages = browser.render_pages([url], self.ctx.settings, delay_seconds=max(self.delay, verdict.crawl_delay or 0), actions={url: steps})
        if not pages:
            return []
        page = pages[0]
        if page.denied:
            raise AccessDenied(
                f"the site refused automated access (HTTP {page.status}) even to a real browser session; this app does not "
                "disguise itself or solve bot-protection challenges.",
                page.status,
            )
        if page.step_error:
            self.ctx.notes.append(f"search form: {page.step_error} (completed {page.steps_done} of {len(steps)} steps)")
        if page.error or not page.html:
            self.last_render_error = page.error or f"HTTP {page.status} with an empty page"
            return []
        self.rendered_pages += 1
        return page.pages

    def rendered(self, urls: list[str]) -> dict[str, str]:
        """Render allowed URLs in a browser; returns url -> html (missing on failure). Raises AccessDenied on 401/403."""
        allowed: list[str] = []
        crawl_delay = 0.0
        for url in urls:
            verdict = self.allowed(url)
            if not verdict.allowed:
                self.skipped_by_robots += 1
                continue
            crawl_delay = max(crawl_delay, verdict.crawl_delay or 0)
            allowed.append(url)
        if not allowed:
            return {}
        out: dict[str, str] = {}
        self.last_render_error = ""
        for page in browser.render_pages(allowed, self.ctx.settings, delay_seconds=max(self.delay, crawl_delay)):
            if page.denied:
                raise AccessDenied(
                    f"the site refused automated access (HTTP {page.status}) even to a real browser session; this app does not "
                    "disguise itself or solve bot-protection challenges.",
                    page.status,
                )
            if page.error or not page.html:
                self.last_render_error = page.error or f"HTTP {page.status} with an empty page"
                continue
            self.rendered_pages += 1
            out[page.url] = page.html
        return out


def _job_from_row(ctx: Any, row: dict[str, str], page_url: str, default_workplace: str) -> Job:
    job_type, schedule = normalise_job_type(row.get("job_type"))
    return Job(
        title=row["title"],
        organization=row.get("company", ""),
        location=row.get("location", ""),
        workplace=normalise_workplace(f"{row['title']} {row.get('location', '')}", default_workplace),
        url=row.get("link") or page_url,
        source=ctx.site.name,
        site_id=ctx.site.id,
        description=row.get("description", ""),
        salary_text=row.get("salary", ""),
        job_type=job_type,
        schedule=schedule,
        published=parse_date(row.get("date")),
        external_id=f"{ctx.site.id}:{row.get('link') or row['title']}",
    )


def _jobs_from_detail(ctx: Any, html: str, link: str, default_workplace: str) -> list[Job]:
    soup = _soup(html)
    postings, _ = extract_jsonld(soup)
    jobs = [j for j in (jobposting_to_job(p, link, ctx.site.name, ctx.site.id, default_workplace) for p in postings) if j]
    if jobs:
        return jobs
    fallback = extract_detail_fallback(soup, link)
    if not fallback["title"]:
        return []
    return [
        Job(
            title=fallback["title"],
            organization=fallback["organization"],
            workplace=normalise_workplace(fallback["title"] + " " + fallback["description"][:200], default_workplace),
            url=link,
            source=ctx.site.name,
            site_id=ctx.site.id,
            description=fallback["description"],
            external_id=f"{ctx.site.id}:{link}",
        )
    ]


_PLACEHOLDER = re.compile(r"\{([a-zA-Z_][\w-]*)\}")


def expand_steps(steps: list[dict[str, Any]], values: dict[str, Any]) -> list[dict[str, Any]]:
    """Substitute ``{name}`` placeholders in a step list from ``values``.

    A placeholder whose value is a list expands the step into one step per
    item (e.g. ticking several brands). Unknown placeholders are left as is.
    """

    def fill(node: Any, table: dict[str, Any]) -> Any:
        if isinstance(node, str):
            return _PLACEHOLDER.sub(lambda m: str(table.get(m.group(1), m.group(0))), node)
        if isinstance(node, dict):
            return {k: fill(v, table) for k, v in node.items()}
        if isinstance(node, list):
            return [fill(v, table) for v in node]
        return node

    out: list[dict[str, Any]] = []
    for step in steps:
        text = json.dumps(step)
        list_names = [name for name in _PLACEHOLDER.findall(text) if isinstance(values.get(name), list)]
        if list_names:
            name = list_names[0]
            for item in values[name]:
                out.append(fill(step, {**values, name: item}))
        else:
            out.append(fill(step, values))
    return out


def looks_js_rendered(soup: Any) -> bool:
    text_len = len(soup.get_text(" ", strip=True))
    script_len = sum(len(s.get_text() or "") for s in soup.find_all("script"))
    return (script_len > text_len * 2 and text_len < 3000) or text_len < 200


def html_page(ctx: Any) -> list[Job]:
    template = str(ctx.options.get("url") or "")
    if not template:
        raise ValueError("web-page site has no URL.")
    options = ctx.options
    default_workplace = str(options.get("workplace") or "")
    pages = max(1, int(options.get("pages") or 1))
    follow = str(options.get("follow_links") or "auto")
    max_detail = max(0, int(options.get("max_detail_pages") or 15))
    link_pattern = str(options.get("link_pattern") or "")
    keywords = [k.lower() for k in ctx.keywords if k]
    steps_template = [step for step in (options.get("actions") or []) if isinstance(step, dict)]
    form_values = dict(options.get("form_values") or {})
    keyword_in_url = "{keyword}" in template or any("{keyword}" in json.dumps(step) for step in steps_template)
    fetcher = _Fetcher(ctx)
    if steps_template:
        if fetcher.render_mode == "never":
            raise ValueError("search-form steps ('actions') need browser rendering; set 'Render with browser' to auto or always.")
        if not fetcher.browser_available():
            raise ValueError(f"search-form steps ('actions') need a browser: {fetcher.browser_reason}")
        fetcher.use_browser = True
    jobs: list[Job] = []
    detail_budget = max_detail
    pages_fetched = 0
    js_suspected = False

    def extract_listing(soup: Any, url: str) -> tuple[int, list[str]]:
        before = len(jobs)
        postings, listed_links = extract_jsonld(soup)
        for posting in postings:
            job = jobposting_to_job(posting, url, ctx.site.name, ctx.site.id, default_workplace)
            if job:
                jobs.append(job)
        for row in extract_with_selectors(soup, options, url):
            jobs.append(_job_from_row(ctx, row, url, default_workplace))
        return len(jobs) - before, listed_links

    for keyword in (ctx.keywords or [""]) if keyword_in_url else [""]:
        for page in range(1, pages + 1):
            url = ctx.fill(template, keyword).replace("{page}", str(page))
            html = ""
            if steps_template:
                steps = expand_steps(steps_template, {**form_values, "keyword": keyword, "location": ctx.location, "page": page})
                snapshots = fetcher.rendered_with_steps(url, steps)
                if not snapshots:
                    js_suspected = True
                    ctx.notes.append(f"browser rendering failed: {fetcher.last_render_error or 'no content'}")
                    break
                pages_fetched += 1
                found_here = 0
                links: list[str] = []
                soup = None
                for snapshot in snapshots:
                    soup = _soup(snapshot)
                    found, listed_links = extract_listing(soup, url)
                    found_here += found
                    links = list(dict.fromkeys(links + (listed_links or candidate_links(soup, url, link_pattern))))
                if follow != "never" and (follow == "always" or found_here == 0) and detail_budget > 0 and links:
                    batch = links[:detail_budget]
                    rendered = fetcher.rendered(batch)
                    detail_budget -= len(rendered)
                    for link, detail_html in rendered.items():
                        jobs.extend(_jobs_from_detail(ctx, detail_html, link, default_workplace))
                if found_here == 0 and not links:
                    js_suspected = soup is not None and looks_js_rendered(soup)
                    break
                continue
            if not fetcher.use_browser:
                html = fetcher.static(url)
                pages_fetched += 1
                kind = classify_body(html)
                if kind == "feed":
                    raise ValueError("the URL is an RSS/Atom feed — configure it as an 'RSS / Atom feed' site instead.")
                if kind == "json":
                    raise ValueError("the URL returns JSON — configure it as a 'Generic JSON API' site instead.")
            soup = _soup(html) if html else None
            found_here, listed_links = extract_listing(soup, url) if soup is not None else (0, [])
            links = (listed_links or candidate_links(soup, url, link_pattern)) if soup is not None else []

            # Nothing usable statically? Become a real browser if the site allows it and Playwright is installed.
            needs_browser = fetcher.use_browser or (
                fetcher.render_mode == "auto" and found_here == 0 and not links and soup is not None and looks_js_rendered(soup)
            )
            if needs_browser and fetcher.render_mode != "never":
                if fetcher.browser_available():
                    rendered = fetcher.rendered([url])
                    if rendered:
                        pages_fetched += 1
                        fetcher.use_browser = True
                        soup = _soup(rendered[url])
                        found_here, listed_links = extract_listing(soup, url)
                        links = listed_links or candidate_links(soup, url, link_pattern)
                    else:
                        js_suspected = True
                        ctx.notes.append(f"browser rendering failed: {fetcher.last_render_error or 'no content'}")
                elif soup is not None and looks_js_rendered(soup):
                    js_suspected = True
                    ctx.notes.append(f"page looks JavaScript-rendered; {fetcher.browser_reason}")
            elif soup is not None and found_here == 0 and not links and looks_js_rendered(soup):
                js_suspected = True

            if follow != "never" and (follow == "always" or found_here == 0) and detail_budget > 0 and links:
                batch = links[:detail_budget]
                if fetcher.use_browser:
                    rendered = fetcher.rendered(batch)
                    detail_budget -= len(rendered)
                    for link, detail_html in rendered.items():
                        jobs.extend(_jobs_from_detail(ctx, detail_html, link, default_workplace))
                else:
                    for link in batch:
                        try:
                            detail_html = fetcher.static(link)
                        except AccessDenied as exc:
                            if exc.status_code:
                                raise  # the site blocked us mid-way: stop, do not hammer it
                            fetcher.skipped_by_robots += 1
                            continue
                        except ValueError:
                            continue
                        detail_budget -= 1
                        jobs.extend(_jobs_from_detail(ctx, detail_html, link, default_workplace))
            if found_here == 0 and not links:
                break  # nothing on this page; don't paginate further

    if keywords and not keyword_in_url:
        jobs = [j for j in jobs if any(k in j.searchable_text for k in keywords)]

    if fetcher.rendered_pages:
        ctx.notes.append(f"rendered {fetcher.rendered_pages} page(s) in a browser")
    if fetcher.skipped_by_robots:
        ctx.notes.append(f"{fetcher.skipped_by_robots} job link(s) skipped because robots.txt disallows them")
    if not jobs:
        guidance = known_site_guidance(template)
        if js_suspected:
            if fetcher.last_render_error:
                hint = f"Loading it in a browser failed too: {fetcher.last_render_error}."
            elif fetcher.browser_reason:
                hint = fetcher.browser_reason
            elif fetcher.rendered_pages:
                hint = "It was loaded in a real browser as well, and still showed no listings."
            else:
                hint = "Set 'Render with browser' to 'always' or check the page with 'Test this site now'."
            message = f"the page loaded ({pages_fetched} request(s)) but contained no job listings — it appears to render results with JavaScript. {hint}"
        elif fetcher.skipped_by_robots and not fetcher.rendered_pages:
            message = f"no listings extracted; {fetcher.skipped_by_robots} job link(s) were skipped because robots.txt disallows them."
        else:
            message = (
                f"the page loaded ({pages_fetched} request(s)) but no job listings were found: no schema.org JobPosting data, "
                "no job-looking links, and no CSS selectors configured."
            )
        if keywords and not keyword_in_url and pages_fetched:
            message += f" (Listings were also filtered locally by: {', '.join(keywords)}.)"
        raise NoListings(message + (f" {guidance}" if guidance else ""))

    seen: set[str] = set()
    unique: list[Job] = []
    for job in jobs:
        key = job.url or job.external_id
        if key in seen:
            continue
        seen.add(key)
        unique.append(job)
        if len(unique) >= ctx.limit:
            break
    return unique
