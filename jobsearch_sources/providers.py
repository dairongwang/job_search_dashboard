"""Provider adapters: turn a ``SiteConfig`` + preferences into normalised ``Job`` rows.

Each adapter is a plain function ``fn(ctx: SearchContext) -> list[Job]``
registered in ``ADAPTERS`` under the provider key from
``jobsearch_config.catalog``. Adapters push whatever the remote API supports
(keyword, location, salary, contract type...) and leave the rest to the
local filter stage, so results are consistent across sites.
"""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any, Callable
from urllib.parse import quote_plus

from jobsearch_config.schema import JobPreferences, SearchSettings, SiteConfig

from .feeds import discover_feeds, explain_fetch_error, known_site_guidance
from .http import FetchError, basic_auth, build_url, classify_body, fetch_json, fetch_text
from .model import Job, normalise_job_type, normalise_workplace, parse_date, plain_text


@dataclass
class SearchContext:
    site: SiteConfig
    prefs: JobPreferences
    settings: SearchSettings
    options: dict[str, Any]  # site.options with ${ENV} resolved
    keywords: list[str] = field(default_factory=list)  # search phrases to try (titles or override)
    keywords_explicit: bool = False  # True when ``keywords`` were requested for this run (override / form test) rather than defaulted from the titles
    location: str = ""  # first non-remote preferred location, for location-aware APIs
    notes: list[str] = field(default_factory=list)  # adapter remarks surfaced next to the results
    extra: dict[str, Any] = field(default_factory=dict)  # structured adapter details (e.g. search-form run info)

    @property
    def limit(self) -> int:
        return self.site.max_results

    @property
    def per_query(self) -> int:
        return max(5, math.ceil(self.limit / max(1, len(self.keywords or [""]))))

    def get_json(self, url: str, headers: dict[str, str] | None = None) -> Any:
        return fetch_json(url, headers=headers, timeout=self.settings.timeout_seconds, user_agent=self.settings.user_agent)

    def get_text(self, url: str, headers: dict[str, str] | None = None) -> str:
        return fetch_text(url, headers=headers, timeout=self.settings.timeout_seconds, user_agent=self.settings.user_agent)

    def fill(self, template: str, keyword: str) -> str:
        """Substitute {keyword}/{location}/{limit} placeholders in a user-supplied URL."""
        return (
            template.replace("{keyword}", quote_plus(keyword))
            .replace("{location}", quote_plus(self.location))
            .replace("{limit}", str(self.limit))
        )


Adapter = Callable[[SearchContext], list[Job]]

# Industry label (from preferences) -> provider category slug
_REMOTIVE_INDUSTRY = {
    "Software / Technology": "software-dev",
    "Data / Analytics": "data",
    "Media / Marketing / Advertising": "marketing",
    "Finance / Banking": "finance-legal",
    "Legal": "finance-legal",
    "Human Resources / Recruiting": "hr",
}
_JOBICY_INDUSTRY = {
    "Software / Technology": "dev",
    "Data / Analytics": "data-science",
    "Media / Marketing / Advertising": "marketing",
    "Finance / Banking": "finance",
    "Legal": "legal",
    "Human Resources / Recruiting": "hr",
}


def _derive(mapping: dict[str, str], prefs: JobPreferences) -> str:
    for industry in prefs.industries:
        if industry in mapping:
            return mapping[industry]
    return ""


def _dedupe(jobs: list[Job], limit: int) -> list[Job]:
    seen: set[str] = set()
    out: list[Job] = []
    for job in jobs:
        key = job.external_id or job.url or f"{job.title}|{job.organization}"
        if key in seen:
            continue
        seen.add(key)
        out.append(job)
        if len(out) >= limit:
            break
    return out


# ---------------------------------------------------------------------------
# Remotive
# ---------------------------------------------------------------------------


def remotive(ctx: SearchContext) -> list[Job]:
    category = ctx.options.get("category") or _derive(_REMOTIVE_INDUSTRY, ctx.prefs)
    jobs: list[Job] = []
    for keyword in ctx.keywords or [""]:
        url = build_url("https://remotive.com/api/remote-jobs", {"search": keyword, "category": category, "limit": ctx.per_query})
        payload = ctx.get_json(url)
        for item in payload.get("jobs", []):
            job_type, schedule = normalise_job_type(item.get("job_type"))
            jobs.append(
                Job(
                    title=item.get("title"),
                    organization=item.get("company_name"),
                    location=item.get("candidate_required_location") or "Worldwide",
                    workplace="remote",
                    url=item.get("url"),
                    source=ctx.site.name,
                    site_id=ctx.site.id,
                    description=item.get("description"),
                    salary_text=item.get("salary") or "",
                    job_type=job_type,
                    schedule=schedule,
                    industry=item.get("category") or "",
                    tags=item.get("tags") or [],
                    published=parse_date(item.get("publication_date")),
                    external_id=f"remotive:{item.get('id')}",
                )
            )
    return _dedupe(jobs, ctx.limit)


# ---------------------------------------------------------------------------
# Jobicy
# ---------------------------------------------------------------------------


def jobicy(ctx: SearchContext) -> list[Job]:
    geo = ctx.options.get("geo") or ""
    industry = ctx.options.get("industry") or _derive(_JOBICY_INDUSTRY, ctx.prefs)
    jobs: list[Job] = []
    for keyword in ctx.keywords or [""]:
        url = build_url(
            "https://jobicy.com/api/v2/remote-jobs",
            {"count": min(ctx.per_query, 50), "geo": geo, "industry": industry, "tag": keyword},
        )
        payload = ctx.get_json(url)
        for item in payload.get("jobs", []):
            salary_min = item.get("annualSalaryMin") or item.get("salaryMin")
            salary_max = item.get("annualSalaryMax") or item.get("salaryMax")
            job_type, schedule = normalise_job_type(item.get("jobType"))
            industries = item.get("jobIndustry") or []
            jobs.append(
                Job(
                    title=item.get("jobTitle"),
                    organization=item.get("companyName"),
                    location=item.get("jobGeo") or "Anywhere",
                    workplace="remote",
                    url=item.get("url"),
                    source=ctx.site.name,
                    site_id=ctx.site.id,
                    description=item.get("jobExcerpt") or item.get("jobDescription"),
                    salary_min=int(salary_min) if salary_min else None,
                    salary_max=int(salary_max) if salary_max else None,
                    salary_currency=item.get("salaryCurrency") or "",
                    salary_period="year" if (salary_min or salary_max) else "",
                    job_type=job_type,
                    schedule=schedule,
                    industry=", ".join(industries) if isinstance(industries, list) else str(industries),
                    tags=[item.get("jobLevel")] if item.get("jobLevel") else [],
                    published=parse_date(item.get("pubDate")),
                    external_id=f"jobicy:{item.get('id')}",
                )
            )
    return _dedupe(jobs, ctx.limit)


# ---------------------------------------------------------------------------
# Arbeitnow
# ---------------------------------------------------------------------------


def arbeitnow(ctx: SearchContext) -> list[Job]:
    pages = int(ctx.options.get("pages") or 1)
    jobs: list[Job] = []
    keywords = [k.lower() for k in ctx.keywords if k]
    for page in range(1, pages + 1):
        payload = ctx.get_json(build_url("https://www.arbeitnow.com/api/job-board-api", {"page": page}))
        for item in payload.get("data", []):
            text = f"{item.get('title', '')} {item.get('description', '')}".lower()
            if keywords and not any(k in text for k in keywords):
                continue
            job_type, schedule = normalise_job_type(item.get("job_types"))
            jobs.append(
                Job(
                    title=item.get("title"),
                    organization=item.get("company_name"),
                    location=item.get("location"),
                    workplace="remote" if item.get("remote") else "onsite",
                    url=item.get("url"),
                    source=ctx.site.name,
                    site_id=ctx.site.id,
                    description=item.get("description"),
                    job_type=job_type,
                    schedule=schedule,
                    tags=item.get("tags") or [],
                    published=parse_date(item.get("created_at")),
                    external_id=f"arbeitnow:{item.get('slug')}",
                )
            )
        if not payload.get("links", {}).get("next"):
            break
    return _dedupe(jobs, ctx.limit)


# ---------------------------------------------------------------------------
# Remote OK
# ---------------------------------------------------------------------------


def remoteok(ctx: SearchContext) -> list[Job]:
    # Remote OK filters by tags; use the first skill (or keyword) as a tag hint, then filter locally.
    tag = ""
    if ctx.prefs.skills:
        tag = ctx.prefs.skills[0].lower()
    payload = ctx.get_json(build_url("https://remoteok.com/api", {"tags": tag}))
    jobs: list[Job] = []
    keywords = [k.lower() for k in ctx.keywords if k]
    for item in payload if isinstance(payload, list) else []:
        if not isinstance(item, dict) or "position" not in item:
            continue  # first element is the legal notice
        text = f"{item.get('position', '')} {item.get('description', '')} {' '.join(item.get('tags') or [])}".lower()
        if keywords and not any(k in text for k in keywords):
            continue
        jobs.append(
            Job(
                title=item.get("position"),
                organization=item.get("company"),
                location=item.get("location") or "Worldwide",
                workplace="remote",
                url=item.get("url") or item.get("apply_url"),
                source=ctx.site.name,
                site_id=ctx.site.id,
                description=item.get("description"),
                salary_min=int(item["salary_min"]) if item.get("salary_min") else None,
                salary_max=int(item["salary_max"]) if item.get("salary_max") else None,
                salary_currency="USD" if item.get("salary_min") or item.get("salary_max") else "",
                salary_period="year" if item.get("salary_min") or item.get("salary_max") else "",
                tags=item.get("tags") or [],
                published=parse_date(item.get("epoch") or item.get("date")),
                external_id=f"remoteok:{item.get('id')}",
            )
        )
    return _dedupe(jobs, ctx.limit)


# ---------------------------------------------------------------------------
# The Muse
# ---------------------------------------------------------------------------


def themuse(ctx: SearchContext) -> list[Job]:
    pages = int(ctx.options.get("pages") or 1)
    jobs: list[Job] = []
    keywords = [k.lower() for k in ctx.keywords if k]
    for page in range(1, pages + 1):
        params: dict[str, Any] = {
            "page": page,
            "category": ctx.options.get("category") or "",
            "level": ctx.options.get("level") or "",
            "location": ctx.location,
            "api_key": ctx.options.get("api_key") or "",
        }
        payload = ctx.get_json(build_url("https://www.themuse.com/api/public/jobs", params))
        for item in payload.get("results", []):
            name = item.get("name") or ""
            contents = item.get("contents") or ""
            text = f"{name} {contents}".lower()
            if keywords and not any(k in text for k in keywords):
                continue
            locations = [loc.get("name", "") for loc in item.get("locations") or []]
            location = "; ".join(loc for loc in locations if loc)
            categories = [c.get("name", "") for c in item.get("categories") or []]
            levels = [lv.get("name", "") for lv in item.get("levels") or []]
            job_type = "internship" if any("intern" in lv.lower() for lv in levels) else ""
            jobs.append(
                Job(
                    title=name,
                    organization=(item.get("company") or {}).get("name"),
                    location=location,
                    workplace=normalise_workplace(location, ""),
                    url=(item.get("refs") or {}).get("landing_page"),
                    source=ctx.site.name,
                    site_id=ctx.site.id,
                    description=contents,
                    job_type=job_type,
                    industry=", ".join(categories),
                    tags=levels,
                    published=parse_date(item.get("publication_date")),
                    external_id=f"themuse:{item.get('id')}",
                )
            )
        if page >= int(payload.get("page_count") or 1):
            break
    return _dedupe(jobs, ctx.limit)


# ---------------------------------------------------------------------------
# Himalayas
# ---------------------------------------------------------------------------


def himalayas(ctx: SearchContext) -> list[Job]:
    payload = ctx.get_json(build_url("https://himalayas.app/jobs/api", {"limit": min(ctx.limit * 2, 100)}))
    jobs: list[Job] = []
    keywords = [k.lower() for k in ctx.keywords if k]
    for item in payload.get("jobs", []):
        text = f"{item.get('title', '')} {item.get('excerpt', '')} {item.get('description', '')}".lower()
        if keywords and not any(k in text for k in keywords):
            continue
        job_type, schedule = normalise_job_type(item.get("employmentType"))
        restrictions = item.get("locationRestrictions") or []
        jobs.append(
            Job(
                title=item.get("title"),
                organization=item.get("companyName"),
                location=", ".join(restrictions) if restrictions else "Worldwide",
                workplace="remote",
                url=item.get("applicationLink") or item.get("url"),
                source=ctx.site.name,
                site_id=ctx.site.id,
                description=item.get("excerpt") or item.get("description"),
                salary_min=int(item["minSalary"]) if item.get("minSalary") else None,
                salary_max=int(item["maxSalary"]) if item.get("maxSalary") else None,
                salary_currency=item.get("currency") or "",
                salary_period="year" if item.get("minSalary") or item.get("maxSalary") else "",
                job_type=job_type,
                schedule=schedule,
                industry=", ".join(item.get("categories") or []),
                tags=item.get("seniority") or [],
                published=parse_date(item.get("pubDate")),
                external_id=f"himalayas:{item.get('guid') or item.get('applicationLink')}",
            )
        )
    return _dedupe(jobs, ctx.limit)


# ---------------------------------------------------------------------------
# Adzuna (app id + key)
# ---------------------------------------------------------------------------


def adzuna(ctx: SearchContext) -> list[Job]:
    country = (ctx.options.get("country") or "us").lower()
    app_id = ctx.options.get("app_id") or ""
    app_key = ctx.options.get("app_key") or ""
    if not app_id or not app_key:
        raise ValueError("Adzuna needs an app id and app key (set them in the configuration dashboard or via ${ADZUNA_APP_ID}/${ADZUNA_APP_KEY}).")
    prefs = ctx.prefs
    salary = prefs.salary
    jobs: list[Job] = []
    for keyword in ctx.keywords or [""]:
        params: dict[str, Any] = {
            "app_id": app_id,
            "app_key": app_key,
            "results_per_page": min(ctx.per_query, 50),
            "what": keyword,
            "where": ctx.location,
            "content-type": "application/json",
        }
        if salary.period == "year" and salary.minimum:
            params["salary_min"] = salary.minimum
        if salary.period == "year" and salary.maximum:
            params["salary_max"] = salary.maximum
        if prefs.posted_within_days:
            params["max_days_old"] = prefs.posted_within_days
        wants_perm = "permanent" in prefs.job_types
        wants_contract = any(t in prefs.job_types for t in ("contract", "temporary", "freelance"))
        if wants_perm and not wants_contract:
            params["permanent"] = 1
        elif wants_contract and not wants_perm:
            params["contract"] = 1
        if prefs.schedules == ["full_time"]:
            params["full_time"] = 1
        elif prefs.schedules == ["part_time"]:
            params["part_time"] = 1
        url = build_url(f"https://api.adzuna.com/v1/api/jobs/{country}/search/1", params)
        payload = ctx.get_json(url)
        for item in payload.get("results", []):
            job_type, _ = normalise_job_type(item.get("contract_type"))
            _, schedule = normalise_job_type(item.get("contract_time"))
            location = (item.get("location") or {}).get("display_name") or ""
            jobs.append(
                Job(
                    title=item.get("title"),
                    organization=(item.get("company") or {}).get("display_name"),
                    location=location,
                    workplace=normalise_workplace(f"{item.get('title', '')} {location}", ""),
                    url=item.get("redirect_url"),
                    source=ctx.site.name,
                    site_id=ctx.site.id,
                    description=item.get("description"),
                    salary_min=int(item["salary_min"]) if item.get("salary_min") else None,
                    salary_max=int(item["salary_max"]) if item.get("salary_max") else None,
                    salary_currency={"us": "USD", "gb": "GBP", "ca": "CAD", "au": "AUD", "in": "INR", "nz": "NZD", "sg": "SGD", "za": "ZAR", "br": "BRL", "ch": "CHF", "mx": "MXN", "pl": "PLN"}.get(country, "EUR"),
                    salary_period="year" if item.get("salary_min") or item.get("salary_max") else "",
                    job_type=job_type,
                    schedule=schedule,
                    industry=(item.get("category") or {}).get("label") or "",
                    published=parse_date(item.get("created")),
                    external_id=f"adzuna:{item.get('id')}",
                )
            )
    return _dedupe(jobs, ctx.limit)


# ---------------------------------------------------------------------------
# Reed (UK, API key)
# ---------------------------------------------------------------------------


def reed(ctx: SearchContext) -> list[Job]:
    api_key = ctx.options.get("api_key") or ""
    if not api_key:
        raise ValueError("Reed needs an API key (set it in the configuration dashboard or via ${REED_API_KEY}).")
    prefs = ctx.prefs
    salary = prefs.salary
    jobs: list[Job] = []
    only_type = prefs.job_types[0] if len(prefs.job_types) == 1 else ""
    for keyword in ctx.keywords or [""]:
        params: dict[str, Any] = {
            "keywords": keyword,
            "locationName": ctx.location,
            "distanceFromLocation": ctx.options.get("distance_miles") or 15,
            "resultsToTake": min(ctx.per_query, 100),
            "permanent": "true" if "permanent" in prefs.job_types else "",
            "contract": "true" if "contract" in prefs.job_types or "freelance" in prefs.job_types else "",
            "temp": "true" if "temporary" in prefs.job_types else "",
            "fullTime": "true" if "full_time" in prefs.schedules else "",
            "partTime": "true" if "part_time" in prefs.schedules else "",
        }
        if salary.period == "year" and salary.minimum:
            params["minimumSalary"] = salary.minimum
        if salary.period == "year" and salary.maximum:
            params["maximumSalary"] = salary.maximum
        payload = ctx.get_json(build_url("https://www.reed.co.uk/api/1.0/search", params), headers=basic_auth(api_key))
        for item in payload.get("results", []):
            jobs.append(
                Job(
                    title=item.get("jobTitle"),
                    organization=item.get("employerName"),
                    location=item.get("locationName"),
                    workplace=normalise_workplace(f"{item.get('jobTitle', '')} {item.get('locationName', '')}", ""),
                    url=item.get("jobUrl"),
                    source=ctx.site.name,
                    site_id=ctx.site.id,
                    description=item.get("jobDescription"),
                    salary_min=int(item["minimumSalary"]) if item.get("minimumSalary") else None,
                    salary_max=int(item["maximumSalary"]) if item.get("maximumSalary") else None,
                    salary_currency=item.get("currency") or "GBP",
                    salary_period="year" if item.get("minimumSalary") or item.get("maximumSalary") else "",
                    job_type=only_type,  # Reed only echoes the filter, not the type per job
                    published=parse_date(item.get("date")),
                    external_id=f"reed:{item.get('jobId')}",
                )
            )
    return _dedupe(jobs, ctx.limit)


# ---------------------------------------------------------------------------
# USAJOBS (API key + email)
# ---------------------------------------------------------------------------


def usajobs(ctx: SearchContext) -> list[Job]:
    api_key = ctx.options.get("api_key") or ""
    email = ctx.options.get("email") or ""
    if not api_key or not email:
        raise ValueError("USAJOBS needs an API key and the registered email.")
    headers = {"Host": "data.usajobs.gov", "User-Agent": email, "Authorization-Key": api_key}
    prefs = ctx.prefs
    jobs: list[Job] = []
    for keyword in ctx.keywords or [""]:
        params: dict[str, Any] = {
            "Keyword": keyword,
            "LocationName": ctx.location,
            "ResultsPerPage": min(ctx.per_query, 100),
        }
        if prefs.salary.period == "year" and prefs.salary.minimum:
            params["RemunerationMinimumAmount"] = prefs.salary.minimum
        if prefs.posted_within_days:
            params["DatePosted"] = min(prefs.posted_within_days, 60)
        payload = ctx.get_json(build_url("https://data.usajobs.gov/api/search", params), headers=headers)
        for item in (payload.get("SearchResult") or {}).get("SearchResultItems", []):
            desc = item.get("MatchedObjectDescriptor") or {}
            pay = (desc.get("PositionRemuneration") or [{}])[0]
            interval = (pay.get("RateIntervalCode") or "PA").upper()
            period = {"PA": "year", "PH": "hour", "PD": "day", "PM": "month"}.get(interval, "year")
            offering = [o.get("Name", "") for o in desc.get("PositionOfferingType") or []]
            schedule_names = [s.get("Name", "") for s in desc.get("PositionSchedule") or []]
            job_type, _ = normalise_job_type(offering)
            _, schedule = normalise_job_type(schedule_names)
            details = (desc.get("UserArea") or {}).get("Details") or {}
            telework = str(details.get("TeleworkEligible", "")).lower() == "true"
            jobs.append(
                Job(
                    title=desc.get("PositionTitle"),
                    organization=desc.get("OrganizationName"),
                    location=desc.get("PositionLocationDisplay"),
                    workplace="hybrid" if telework else "onsite",
                    url=desc.get("PositionURI"),
                    source=ctx.site.name,
                    site_id=ctx.site.id,
                    description=details.get("JobSummary") or desc.get("QualificationSummary"),
                    salary_min=int(float(pay["MinimumRange"])) if pay.get("MinimumRange") else None,
                    salary_max=int(float(pay["MaximumRange"])) if pay.get("MaximumRange") else None,
                    salary_currency="USD",
                    salary_period=period,
                    job_type=job_type or ("permanent" if any("permanent" in o.lower() for o in offering) else ""),
                    schedule=schedule,
                    industry=", ".join(c.get("Name", "") for c in desc.get("JobCategory") or []),
                    published=parse_date(desc.get("PublicationStartDate")),
                    external_id=f"usajobs:{item.get('MatchedObjectId')}",
                )
            )
    return _dedupe(jobs, ctx.limit)


# ---------------------------------------------------------------------------
# Generic RSS / Atom
# ---------------------------------------------------------------------------

_ATOM = "{http://www.w3.org/2005/Atom}"
_DC = "{http://purl.org/dc/elements/1.1/}"


def _text(node: ET.Element | None) -> str:
    return (node.text or "").strip() if node is not None else ""


def _split_title(title: str, fmt: str) -> tuple[str, str]:
    if fmt == "company: title" and ": " in title:
        company, role = title.split(": ", 1)
        return role.strip(), company.strip()
    if fmt == "title at company" and " at " in title:
        role, company = title.rsplit(" at ", 1)
        return role.strip(), company.strip()
    return title, ""


def _fetch_feed_text(ctx: SearchContext, url: str) -> str:
    """GET a feed URL; if it is an HTML page, follow the feed it advertises; explain failures."""
    try:
        text = ctx.get_text(url)
    except FetchError as exc:
        raise ValueError(explain_fetch_error(exc, url)) from exc
    kind = classify_body(text)
    if kind == "feed" or kind == "xml":
        return text
    if kind == "html":
        feeds = discover_feeds(text, url)
        for feed_url in feeds[:3]:
            try:
                candidate = ctx.get_text(feed_url)
            except FetchError:
                continue
            if classify_body(candidate) in ("feed", "xml"):
                return candidate
        guidance = known_site_guidance(url)
        raise ValueError(
            "the URL returns a web page (HTML), not an RSS/Atom feed"
            + (f". {guidance}" if guidance else ". Use the site's feed URL (look for an RSS/Atom link) or its API.")
        )
    if kind == "json":
        raise ValueError("the URL returns JSON, not an RSS/Atom feed — configure it as a 'Generic JSON API' site instead.")
    raise ValueError("the URL did not return an RSS/Atom feed.")


def rss(ctx: SearchContext) -> list[Job]:
    template = ctx.options.get("url") or ""
    if not template:
        raise ValueError("RSS site has no feed URL.")
    default_workplace = ctx.options.get("workplace") or ""
    title_format = ctx.options.get("title_format") or ""
    keywords = [k.lower() for k in ctx.keywords if k]
    urls = [ctx.fill(template, k) for k in (ctx.keywords or [""])] if "{keyword}" in template else [ctx.fill(template, "")]
    jobs: list[Job] = []
    for url in dict.fromkeys(urls):
        text = _fetch_feed_text(ctx, url)
        try:
            root = ET.fromstring(text.encode("utf-8"))
        except ET.ParseError as exc:
            raise ValueError(f"Feed is not valid XML ({exc}).") from exc
        entries = root.findall(".//item") or root.findall(f".//{_ATOM}entry")
        for entry in entries:
            title = _text(entry.find("title")) or _text(entry.find(f"{_ATOM}title"))
            link = _text(entry.find("link"))
            if not link:
                link_node = entry.find(f"{_ATOM}link")
                link = link_node.get("href", "") if link_node is not None else ""
            description = (
                _text(entry.find("description"))
                or _text(entry.find(f"{_ATOM}summary"))
                or _text(entry.find(f"{_ATOM}content"))
                or _text(entry.find("{http://purl.org/rss/1.0/modules/content/}encoded"))
            )
            published = _text(entry.find("pubDate")) or _text(entry.find(f"{_ATOM}published")) or _text(entry.find(f"{_ATOM}updated")) or _text(entry.find(f"{_DC}date"))
            author = _text(entry.find(f"{_DC}creator")) or _text(entry.find("author")) or _text(entry.find(f"{_ATOM}author/{_ATOM}name"))
            categories = [_text(c) for c in entry.findall("category")] + [c.get("term", "") for c in entry.findall(f"{_ATOM}category")]
            role, company = _split_title(title, title_format)
            guid = _text(entry.find("guid")) or _text(entry.find(f"{_ATOM}id")) or link
            haystack = f"{title} {description}".lower()
            if keywords and "{keyword}" not in template and not any(k in haystack for k in keywords):
                continue
            jobs.append(
                Job(
                    title=role,
                    organization=company or author,
                    location=_text(entry.find("location")) or "",
                    workplace=normalise_workplace(f"{title} {description[:300]}", default_workplace),
                    url=link,
                    source=ctx.site.name,
                    site_id=ctx.site.id,
                    description=description,
                    job_type=normalise_job_type(categories)[0],
                    tags=[c for c in categories if c],
                    published=parse_date(published),
                    external_id=f"{ctx.site.id}:{guid}",
                )
            )
    return _dedupe(jobs, ctx.limit)


# ---------------------------------------------------------------------------
# Generic JSON API with field mapping
# ---------------------------------------------------------------------------


def _dig(data: Any, path: str) -> Any:
    """Follow a dotted path through dicts/lists: 'company.name', 'locations.0.name', 'tags.*.name'."""
    if not path:
        return data
    current = data
    for part in path.split("."):
        if current is None:
            return None
        if part == "*" and isinstance(current, list):
            return [_dig(item, "") for item in current]
        if isinstance(current, list):
            try:
                current = current[int(part)]
            except (ValueError, IndexError):
                return None
        elif isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


def _join(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(str(v) for v in value if v not in (None, ""))
    return "" if value is None else str(value)


def generic_json(ctx: SearchContext) -> list[Job]:
    template = ctx.options.get("url") or ""
    if not template:
        raise ValueError("JSON site has no endpoint URL.")
    mapping: dict[str, str] = dict(ctx.options.get("mapping") or {})
    headers: dict[str, str] = {str(k): str(v) for k, v in (ctx.options.get("headers") or {}).items()}
    items_path = ctx.options.get("items_path") or ""
    default_workplace = ctx.options.get("workplace") or ""
    keywords = [k.lower() for k in ctx.keywords if k]
    urls = [ctx.fill(template, k) for k in (ctx.keywords or [""])] if "{keyword}" in template else [ctx.fill(template, "")]
    jobs: list[Job] = []
    for url in dict.fromkeys(urls):
        try:
            payload = ctx.get_json(url, headers=headers)
        except FetchError as exc:
            raise ValueError(explain_fetch_error(exc, url)) from exc
        items = _dig(payload, items_path)
        if not isinstance(items, list):
            raise ValueError(f"Items path '{items_path or '(root)'}' did not resolve to a list.")
        for item in items:
            if not isinstance(item, dict):
                continue
            get = lambda key: _dig(item, mapping.get(key, "")) if mapping.get(key) else None  # noqa: E731
            title = _join(get("title"))
            description = _join(get("description"))
            if keywords and "{keyword}" not in template and not any(k in f"{title} {description}".lower() for k in keywords):
                continue
            job_type, schedule = normalise_job_type(get("job_type"))
            salary_min = get("salary_min")
            salary_max = get("salary_max")
            location = _join(get("location"))
            jobs.append(
                Job(
                    title=title,
                    organization=_join(get("organization")),
                    location=location,
                    workplace=normalise_workplace(_join(get("workplace")) or f"{title} {location}", default_workplace),
                    url=_join(get("url")),
                    source=ctx.site.name,
                    site_id=ctx.site.id,
                    description=description,
                    salary_text=_join(get("salary_text")),
                    salary_min=int(float(salary_min)) if salary_min not in (None, "") else None,
                    salary_max=int(float(salary_max)) if salary_max not in (None, "") else None,
                    salary_currency=_join(get("salary_currency")),
                    job_type=job_type,
                    schedule=schedule,
                    industry=_join(get("industry")),
                    tags=[str(t) for t in (get("tags") or [])] if isinstance(get("tags"), list) else [],
                    published=parse_date(get("published")),
                    external_id=f"{ctx.site.id}:{_join(get('id')) or _join(get('url'))}",
                )
            )
    return _dedupe(jobs, ctx.limit)


from .ats import ATS_ADAPTERS  # noqa: E402  (after SearchContext is defined)
from .htmlpages import html_page  # noqa: E402

ADAPTERS: dict[str, Adapter] = {
    **ATS_ADAPTERS,
    "html": html_page,
    "remotive": remotive,
    "jobicy": jobicy,
    "arbeitnow": arbeitnow,
    "remoteok": remoteok,
    "themuse": themuse,
    "himalayas": himalayas,
    "adzuna": adzuna,
    "reed": reed,
    "usajobs": usajobs,
    "rss": rss,
    "json": generic_json,
}

# Providers that accept a keyword server-side (others filter locally on the keyword list).
KEYWORD_PROVIDERS = {"remotive", "jobicy", "adzuna", "reed", "usajobs", "smartrecruiters", "workday"}

__all__ = ["ADAPTERS", "KEYWORD_PROVIDERS", "SearchContext", "plain_text"]
