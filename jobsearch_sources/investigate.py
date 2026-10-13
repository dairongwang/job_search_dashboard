"""Investigate a careers / job-board URL: may we crawl it, and how do we get its jobs?

``investigate(url)`` answers, from live requests:

1. **robots.txt** — is this URL allowed for our crawler (RFC 9309 rules)?
2. **reachability** — does the host answer, or refuse scripts (401/403)?
3. **platform** — which applicant-tracking system powers the page (Workday,
   Greenhouse, Lever, …)? Those expose public job APIs, which are the
   cleanest, most reliable source and the intended way for third parties.
4. **page data** — schema.org JobPosting objects, advertised feeds,
   job-looking links, JavaScript rendering.
5. **search form** — the inputs, dropdowns and buttons on the page
   (placeholder / label / option texts), so a form-driving recipe for the
   web-page provider can be written without guessing selectors.

The result carries a ready-to-save ``SiteConfig`` suggestion. Run it from the
configuration dashboard (*Investigate a careers URL*) or the CLI::

    python -m jobsearch_sources investigate https://www.yahooinc.com/careers/ --render
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any
from urllib.parse import urlsplit

from jobsearch_config.catalog import default_options
from jobsearch_config.registry import load_registry
from jobsearch_config.schema import SearchSettings, SiteConfig

from . import browser, robots
from .feeds import discover_feeds, explain_fetch_error
from .htmlpages import _soup, candidate_links, extract_jsonld, looks_js_rendered
from .http import FetchError, classify_body, fetch_bytes

# Platform fingerprints: regex over the page HTML (links, iframes, scripts) -> provider + options.
PLATFORMS: list[tuple[str, str, str]] = [
    # (provider key, regex, human label)
    ("workday", r"https?://([\w-]+)\.(wd\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?([\w-]+)", "Workday"),
    ("greenhouse", r"boards(?:-api)?\.greenhouse\.io/(?:v1/boards/|embed/job_board\?for=|)([\w-]+)|job-boards\.greenhouse\.io/([\w-]+)", "Greenhouse"),
    ("lever", r"jobs\.lever\.co/([\w-]+)|api\.lever\.co/v0/postings/([\w-]+)", "Lever"),
    ("ashby", r"jobs\.ashbyhq\.com/([\w-]+)|api\.ashbyhq\.com/posting-api/job-board/([\w-]+)", "Ashby"),
    ("smartrecruiters", r"(?:careers|jobs)\.smartrecruiters\.com/([\w-]+)|api\.smartrecruiters\.com/v1/companies/([\w-]+)", "SmartRecruiters"),
    ("recruitee", r"https?://([\w-]+)\.recruitee\.com", "Recruitee"),
    ("workable", r"apply\.workable\.com/([\w-]+)|([\w-]+)\.workable\.com", "Workable"),
]

# Platforms without a public job API: handled by the web-page provider (with browser rendering when needed).
HTML_PLATFORMS: list[tuple[str, str, str]] = [
    ("icims", r"careers-[\w-]+\.icims\.com|icims\.com/jobs", "iCIMS — HTML search pages; use the Web page provider with `{keyword}` in the URL (e.g. `…/jobs/search?ss=1&searchKeyword={keyword}`)."),
    ("successfactors", r"successfactors|sapsf\.|jobs\.[\w.-]+/search/\?", "SAP SuccessFactors — HTML search (`/search/?q={keyword}`); job pages embed JobPosting data. Use the Web page provider."),
    ("taleo", r"taleo\.net", "Oracle Taleo — JavaScript-rendered; use the Web page provider with browser rendering."),
    ("oracle_hcm", r"oraclecloud\.com/hcmUI/CandidateExperience", "Oracle Cloud HCM — JavaScript-rendered; use the Web page provider with browser rendering."),
    ("phenom", r"phenompeople|phenom\.com|/widgets/\w+\.js|pxjs", "Phenom — JavaScript-rendered with JobPosting data on job pages; use the Web page provider with browser rendering."),
    ("eightfold", r"eightfold\.ai", "Eightfold — JavaScript-rendered; use the Web page provider with browser rendering."),
    ("jobvite", r"jobs\.jobvite\.com/([\w-]+)", "Jobvite — HTML list pages; use the Web page provider (job pages carry JobPosting data)."),
    ("bamboohr", r"([\w-]+)\.bamboohr\.com/careers", "BambooHR — HTML careers list (`/careers/list` JSON is also available); use the Web page provider."),
    ("teamtailor", r"([\w-]+)\.teamtailor\.com", "Teamtailor — offers `/jobs.rss`; add it as an RSS site."),
    ("personio", r"([\w-]+)\.jobs\.personio\.(?:de|com)", "Personio — offers an XML feed at `/xml`; add the careers page as an RSS/Atom site or use the Web page provider."),
]


@dataclass
class FormControl:
    kind: str  # input | select | button | combobox | checkbox
    label: str  # placeholder / aria-label / visible text / name
    selector: str  # best-effort CSS hint
    options: list[str] = field(default_factory=list)


@dataclass
class Investigation:
    url: str
    host: str = ""
    robots_allowed: bool | None = None
    robots_reason: str = ""
    crawl_delay: float | None = None
    reachable: bool | None = None
    http_status: int = 0
    denied: bool = False
    error: str = ""
    registry_status: str = ""
    registry_message: str = ""
    platform: str = ""  # provider key or html-platform key
    platform_label: str = ""
    platform_options: dict[str, Any] = field(default_factory=dict)
    content_kind: str = ""  # html | feed | json | unknown
    jsonld_postings: int = 0
    feeds: list[str] = field(default_factory=list)
    job_links: int = 0
    js_rendered: bool = False
    rendered: bool = False
    form_controls: list[FormControl] = field(default_factory=list)
    verdict: str = ""  # crawlable | forbidden | unreachable | unknown
    summary: str = ""
    suggested_site: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def suggested_config(self) -> SiteConfig | None:
        return SiteConfig.from_dict(self.suggested_site) if self.suggested_site else None


def _site_id(host: str, suffix: str = "") -> str:
    base = re.sub(r"[^a-z0-9]+", "-", host.lower().replace("www.", "")).strip("-")[:32]
    return f"{base}{suffix}" if base else "site"


def detect_platform(html: str, page_url: str) -> tuple[str, str, dict[str, Any]]:
    """Return (provider_or_platform_key, label, options) from page HTML; ("", "", {}) if none."""
    haystack = html
    for key, pattern, label in PLATFORMS:
        match = re.search(pattern, haystack)
        if not match:
            continue
        groups = [g for g in match.groups() if g]
        options: dict[str, Any] = {}
        if key == "workday":
            tenant, wd, site = match.group(1), match.group(2), match.group(3)
            if site.lower() in ("job", "jobs", "login"):
                site = "careers"
            options = {"tenant": tenant, "host": f"{tenant}.{wd}.myworkdayjobs.com", "site": site, "url": f"https://{tenant}.{wd}.myworkdayjobs.com/{site}"}
        elif key == "greenhouse":
            options = {"board": groups[0]}
        elif key == "lever":
            options = {"site": groups[0]}
        elif key == "ashby":
            options = {"board": groups[0]}
        elif key == "smartrecruiters":
            options = {"company_id": groups[0]}
        elif key == "recruitee":
            options = {"company": groups[0]}
        elif key == "workable":
            options = {"subdomain": groups[0]}
        return key, label, options
    for key, pattern, label in HTML_PLATFORMS:
        if re.search(pattern, haystack, re.IGNORECASE):
            return key, label, {}
    return "", "", {}


def _text(node: Any) -> str:
    return node.get_text(" ", strip=True) if node is not None else ""


def form_controls(soup: Any) -> list[FormControl]:
    """Inventory of inputs, selects, custom dropdowns and buttons a search recipe could drive."""
    controls: list[FormControl] = []
    seen: set[tuple[str, str]] = set()

    def add(kind: str, label: str, selector: str, options: list[str] | None = None) -> None:
        label = re.sub(r"\s+", " ", label or "").strip()[:80]
        if not label or (kind, label) in seen:
            return
        seen.add((kind, label))
        controls.append(FormControl(kind, label, selector, options or []))

    for node in soup.find_all("input"):
        itype = (node.get("type") or "text").lower()
        if itype in ("hidden", "submit", "button", "image"):
            if itype == "submit" and node.get("value"):
                add("button", node["value"], f"input[type=submit][value='{node['value']}']")
            continue
        label = node.get("placeholder") or node.get("aria-label") or node.get("name") or node.get("id") or ""
        selector = f"#{node['id']}" if node.get("id") else (f"input[name='{node['name']}']" if node.get("name") else f"input[placeholder='{node.get('placeholder', '')}']")
        add("checkbox" if itype in ("checkbox", "radio") else "input", label, selector)
    for node in soup.find_all("select"):
        label = node.get("aria-label") or node.get("name") or node.get("id") or _text(node.find("option"))
        selector = f"#{node['id']}" if node.get("id") else (f"select[name='{node['name']}']" if node.get("name") else "select")
        add("select", label, selector, [_text(o) for o in node.find_all("option")][:40])
    for node in soup.find_all(attrs={"role": re.compile(r"combobox|listbox", re.I)}):
        label = node.get("aria-label") or node.get("placeholder") or _text(node)
        add("combobox", label, f"[role='{node.get('role')}']" + (f"#{node['id']}" if node.get("id") else ""), [_text(o) for o in node.find_all(attrs={"role": "option"})][:40])
    for node in soup.find_all("button"):
        label = _text(node) or node.get("aria-label") or node.get("value") or ""
        add("button", label, f"button:has-text('{label}')" if label else "button")
    for node in soup.find_all("a", attrs={"role": "button"}):
        add("button", _text(node), f"a[role=button]:has-text('{_text(node)}')")
    return controls[:60]


def _suggest(report: Investigation, settings: SearchSettings) -> None:
    host_id = _site_id(report.host)
    name = report.host.replace("www.", "")
    if report.platform in ("workday", "greenhouse", "lever", "ashby", "smartrecruiters", "recruitee", "workable"):
        options = default_options(report.platform)
        options.update(report.platform_options)
        report.suggested_site = asdict(
            SiteConfig(
                id=f"{host_id}-{report.platform}",
                provider=report.platform,
                name=f"{name} ({report.platform_label})",
                enabled=True,
                options=options,
                notes=f"Suggested by Investigate from {report.url}",
            )
        )
        report.summary = (
            f"{report.platform_label} powers this careers site; its public job API returns structured listings. "
            f"Suggested: a '{report.platform_label}' site with {', '.join(f'{k}={v}' for k, v in report.platform_options.items() if k != 'url')}."
        )
        return
    if report.feeds:
        options = default_options("rss")
        options["url"] = report.feeds[0]
        report.suggested_site = asdict(SiteConfig(id=f"{host_id}-feed", provider="rss", name=f"{name} (feed)", enabled=True, options=options))
        report.summary = f"The page advertises a feed ({report.feeds[0]}); an RSS site is the lightest option."
        return
    if report.content_kind == "feed":
        options = default_options("rss")
        options["url"] = report.url
        report.suggested_site = asdict(SiteConfig(id=f"{host_id}-feed", provider="rss", name=f"{name} (feed)", enabled=True, options=options))
        report.summary = "This URL is an RSS/Atom feed."
        return
    if report.content_kind == "json":
        options = default_options("json")
        options["url"] = report.url
        report.suggested_site = asdict(SiteConfig(id=f"{host_id}-api", provider="json", name=f"{name} (API)", enabled=True, options=options))
        report.summary = "This URL returns JSON; map its fields in a Generic JSON API site."
        return
    if report.content_kind == "html" and report.verdict == "crawlable":
        options = default_options("html")
        options["url"] = report.url
        options["render"] = "always" if report.js_rendered else "auto"
        report.suggested_site = asdict(SiteConfig(id=f"{host_id}-page", provider="html", name=f"{name} (page)", enabled=True, options=options))
        parts = []
        if report.jsonld_postings:
            parts.append(f"{report.jsonld_postings} JobPosting object(s) on the page")
        if report.job_links:
            parts.append(f"{report.job_links} job-looking link(s)")
        if report.js_rendered:
            parts.append("results are rendered by JavaScript (browser rendering suggested)")
        if report.form_controls:
            parts.append(f"{len(report.form_controls)} form control(s) found for a search recipe")
        report.summary = ("Web page: " + "; ".join(parts) + ".") if parts else "Web page with no detectable listings; configure CSS selectors or a search recipe."
        if report.platform_label and report.platform not in ("workday", "greenhouse", "lever", "ashby", "smartrecruiters", "recruitee", "workable"):
            report.summary = report.platform_label + " " + report.summary


def investigate(url: str, settings: SearchSettings | None = None, render: bool = False, record: bool = True) -> Investigation:
    settings = settings or SearchSettings()
    report = Investigation(url=url, host=urlsplit(url).netloc.lower())
    registry = load_registry() if record else None
    if registry is not None:
        row = registry.lookup(url)
        if row is not None:
            report.registry_status = "forbidden" if not row.active else row.status
            report.registry_message = row.message

    verdict = robots.check(url, settings)
    report.robots_allowed, report.robots_reason, report.crawl_delay = verdict.allowed, verdict.reason, verdict.crawl_delay
    if not verdict.allowed:
        report.verdict = "unreachable" if verdict.unreachable else "forbidden"
        report.summary = verdict.reason
        if registry is not None:
            registry.record(url, "error" if verdict.unreachable else "forbidden", verdict.reason, source="probe")
        return report

    try:
        raw = fetch_bytes(url, timeout=settings.timeout_seconds, user_agent=settings.user_agent)
        report.reachable, report.http_status = True, 200
    except FetchError as exc:
        report.reachable = False
        report.http_status = exc.status
        report.denied = exc.status in (401, 403, 429)
        report.error = explain_fetch_error(exc, url)
        report.verdict = "forbidden" if report.denied else "unreachable"
        report.summary = report.error
        if registry is not None:
            registry.record(url, "forbidden" if report.denied else "error", report.error, source="probe", status_code=exc.status)
        return report

    report.content_kind = classify_body(raw)
    text = raw.decode("utf-8", errors="replace")
    html = text
    if report.content_kind == "html":
        soup = _soup(html)
        report.js_rendered = looks_js_rendered(soup)
        if render and browser.available()[0]:
            pages = browser.render_pages([url], settings, delay_seconds=0)
            if pages and pages[0].denied:
                report.denied, report.http_status = True, pages[0].status
                report.error = f"the site refused a real browser session too (HTTP {pages[0].status})."
                report.verdict = "forbidden"
                report.summary = report.error
                if registry is not None:
                    registry.record(url, "forbidden", report.error, source="probe", status_code=pages[0].status)
                return report
            if pages and pages[0].html:
                html = pages[0].html
                soup = _soup(html)
                report.rendered = True
        key, label, options = detect_platform(html, url)
        report.platform, report.platform_label, report.platform_options = key, label, options
        postings, listed = extract_jsonld(soup)
        report.jsonld_postings = len(postings)
        report.feeds = discover_feeds(html, url)
        report.job_links = len(listed or candidate_links(soup, url))
        report.form_controls = form_controls(soup)
    report.verdict = "crawlable"
    _suggest(report, settings)
    if registry is not None:
        status = "ok" if (report.jsonld_postings or report.job_links or report.platform or report.feeds or report.content_kind in ("feed", "json")) else "empty"
        registry.record(url, status, report.summary or "Reachable.", source="probe", status_code=200)
    return report


def format_report(report: Investigation) -> str:
    lines = [f"URL: {report.url}", f"Verdict: {report.verdict}"]
    lines.append(f"robots.txt: {'allowed' if report.robots_allowed else 'DISALLOWED — ' + report.robots_reason}" + (f" (crawl-delay {report.crawl_delay}s)" if report.crawl_delay else ""))
    if report.reachable is not None:
        lines.append(f"Reachable: {'yes' if report.reachable else 'no — ' + report.error}")
    if report.registry_status:
        lines.append(f"Registry: {report.registry_status} — {report.registry_message}")
    if report.platform:
        lines.append(f"Platform: {report.platform_label} {json.dumps(report.platform_options) if report.platform_options else ''}".rstrip())
    if report.content_kind:
        lines.append(f"Content: {report.content_kind}; JobPosting objects: {report.jsonld_postings}; job links: {report.job_links}; feeds: {', '.join(report.feeds) or 'none'}; JavaScript-rendered: {'yes' if report.js_rendered else 'no'}{' (rendered in browser)' if report.rendered else ''}")
    if report.form_controls:
        lines.append("Search form controls:")
        for control in report.form_controls:
            extra = f" options: {', '.join(control.options[:8])}{'…' if len(control.options) > 8 else ''}" if control.options else ""
            lines.append(f"  - {control.kind:9} {control.label!r:40} {control.selector}{extra}")
    if report.summary:
        lines.append(f"Summary: {report.summary}")
    if report.suggested_site:
        lines.append("Suggested site config:")
        lines.append(json.dumps(report.suggested_site, indent=2))
    return "\n".join(lines)
