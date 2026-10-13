"""Adapters for applicant-tracking platforms that power company career pages.

Most "careers" pages are front ends for one of a handful of platforms, and
those platforms publish **job-board APIs meant for third parties** (widgets,
aggregators, job boards). Reading them is the intended use — no scraping,
no JavaScript, and the data is structured (title, location, department,
employment type, sometimes salary).

| provider          | endpoint (public, no key)                                                   |
|-------------------|-----------------------------------------------------------------------------|
| greenhouse        | https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true        |
| lever             | https://api.lever.co/v0/postings/{site}?mode=json                           |
| ashby             | https://api.ashbyhq.com/posting-api/job-board/{board}?includeCompensation=true |
| smartrecruiters   | https://api.smartrecruiters.com/v1/companies/{company}/postings             |
| recruitee         | https://{company}.recruitee.com/api/offers/                                 |
| workable          | https://www.workable.com/api/accounts/{subdomain}?details=true              |
| workday           | POST https://{tenant}.{host}/wday/cxs/{tenant}/{site}/jobs (the career site's own search API) |

The ``investigate`` module detects which platform a careers URL uses and
suggests the matching site configuration.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

from .feeds import AccessDenied, explain_fetch_error
from .http import FetchError, build_url, post_json
from .model import Job, normalise_job_type, normalise_workplace, parse_date, plain_text


def _guard(call, url: str):
    """Run a fetch, translating HTTP failures into the app's typed errors."""
    try:
        return call()
    except FetchError as exc:
        if exc.status in (401, 403, 429):
            raise AccessDenied(explain_fetch_error(exc, url), exc.status) from exc
        raise ValueError(explain_fetch_error(exc, url)) from exc


def _matches(text: str, keywords: list[str]) -> bool:
    if not keywords:
        return True
    lowered = text.lower()
    return any(k in lowered for k in keywords)


def _cap(jobs: list[Job], limit: int) -> list[Job]:
    seen: set[str] = set()
    out: list[Job] = []
    for job in jobs:
        key = job.url or job.external_id
        if key in seen:
            continue
        seen.add(key)
        out.append(job)
        if len(out) >= limit:
            break
    return out


# ---------------------------------------------------------------------------
# Greenhouse
# ---------------------------------------------------------------------------


def greenhouse(ctx: Any) -> list[Job]:
    board = str(ctx.options.get("board") or "").strip()
    if not board:
        raise ValueError("Greenhouse needs the board token (the part after boards.greenhouse.io/).")
    url = build_url(f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs", {"content": "true"})
    payload = _guard(lambda: ctx.get_json(url), url)
    keywords = [k.lower() for k in ctx.keywords if k]
    department_filter = str(ctx.options.get("department") or "").lower()
    jobs: list[Job] = []
    for item in payload.get("jobs", []):
        title = item.get("title") or ""
        content = item.get("content") or ""
        departments = ", ".join(d.get("name", "") for d in item.get("departments") or [])
        if department_filter and department_filter not in departments.lower():
            continue
        if not _matches(f"{title} {content}", keywords):
            continue
        location = (item.get("location") or {}).get("name") or ""
        jobs.append(
            Job(
                title=title,
                organization=str(ctx.options.get("company") or board),
                location=location,
                workplace=normalise_workplace(f"{title} {location}", str(ctx.options.get("workplace") or "")),
                url=item.get("absolute_url") or "",
                source=ctx.site.name,
                site_id=ctx.site.id,
                description=content,
                industry=departments,
                tags=[o.get("name", "") for o in item.get("offices") or []],
                published=parse_date(item.get("first_published") or item.get("updated_at")),
                external_id=f"greenhouse:{board}:{item.get('id')}",
            )
        )
    return _cap(jobs, ctx.limit)


# ---------------------------------------------------------------------------
# Lever
# ---------------------------------------------------------------------------


def lever(ctx: Any) -> list[Job]:
    site = str(ctx.options.get("site") or "").strip()
    if not site:
        raise ValueError("Lever needs the site name (the part after jobs.lever.co/).")
    params: dict[str, Any] = {"mode": "json", "limit": min(ctx.limit * 3, 100)}
    for key in ("department", "team", "location", "commitment"):
        if ctx.options.get(key):
            params[key] = ctx.options[key]
    url = build_url(f"https://api.lever.co/v0/postings/{site}", params)
    payload = _guard(lambda: ctx.get_json(url), url)
    keywords = [k.lower() for k in ctx.keywords if k]
    jobs: list[Job] = []
    for item in payload if isinstance(payload, list) else []:
        title = item.get("text") or ""
        description = item.get("descriptionPlain") or item.get("description") or ""
        if not _matches(f"{title} {description}", keywords):
            continue
        categories = item.get("categories") or {}
        job_type, schedule = normalise_job_type(categories.get("commitment"))
        salary = item.get("salaryRange") or {}
        created = item.get("createdAt")
        jobs.append(
            Job(
                title=title,
                organization=str(ctx.options.get("company") or site),
                location=categories.get("location") or ", ".join(categories.get("allLocations") or []),
                workplace=normalise_workplace(item.get("workplaceType") or "", str(ctx.options.get("workplace") or "")),
                url=item.get("hostedUrl") or item.get("applyUrl") or "",
                source=ctx.site.name,
                site_id=ctx.site.id,
                description=description,
                salary_min=int(salary["min"]) if salary.get("min") else None,
                salary_max=int(salary["max"]) if salary.get("max") else None,
                salary_currency=salary.get("currency") or "",
                salary_period={"per-year-salary": "year", "per-hour-wage": "hour"}.get(str(salary.get("interval") or ""), "year" if salary else ""),
                job_type=job_type,
                schedule=schedule,
                industry=", ".join(v for v in (categories.get("department"), categories.get("team")) if v),
                published=parse_date(created / 1000 if isinstance(created, (int, float)) else created),
                external_id=f"lever:{site}:{item.get('id')}",
            )
        )
    return _cap(jobs, ctx.limit)


# ---------------------------------------------------------------------------
# Ashby
# ---------------------------------------------------------------------------


def ashby(ctx: Any) -> list[Job]:
    board = str(ctx.options.get("board") or "").strip()
    if not board:
        raise ValueError("Ashby needs the job board name (the part after jobs.ashbyhq.com/).")
    url = build_url(f"https://api.ashbyhq.com/posting-api/job-board/{board}", {"includeCompensation": "true"})
    payload = _guard(lambda: ctx.get_json(url), url)
    keywords = [k.lower() for k in ctx.keywords if k]
    jobs: list[Job] = []
    for item in payload.get("jobs", []):
        title = item.get("title") or ""
        description = item.get("descriptionPlain") or item.get("descriptionHtml") or ""
        if not _matches(f"{title} {description}", keywords):
            continue
        job_type, schedule = normalise_job_type(item.get("employmentType"))
        comp = item.get("compensation") or {}
        salary_text = comp.get("compensationTierSummary") or ""
        jobs.append(
            Job(
                title=title,
                organization=str(ctx.options.get("company") or board),
                location=", ".join(v for v in [item.get("location")] + [s.get("location", "") for s in item.get("secondaryLocations") or []] if v),
                workplace="remote" if item.get("isRemote") else normalise_workplace(item.get("location") or "", str(ctx.options.get("workplace") or "")),
                url=item.get("jobUrl") or item.get("applyUrl") or "",
                source=ctx.site.name,
                site_id=ctx.site.id,
                description=description,
                salary_text=salary_text,
                job_type=job_type,
                schedule=schedule,
                industry=", ".join(v for v in (item.get("department"), item.get("team")) if v),
                published=parse_date(item.get("publishedAt")),
                external_id=f"ashby:{board}:{item.get('id')}",
            )
        )
    return _cap(jobs, ctx.limit)


# ---------------------------------------------------------------------------
# SmartRecruiters
# ---------------------------------------------------------------------------


def smartrecruiters(ctx: Any) -> list[Job]:
    company = str(ctx.options.get("company_id") or "").strip()
    if not company:
        raise ValueError("SmartRecruiters needs the company identifier (the part after careers.smartrecruiters.com/).")
    jobs: list[Job] = []
    for keyword in ctx.keywords or [""]:
        params: dict[str, Any] = {"q": keyword, "limit": min(ctx.per_query, 100)}
        if ctx.location:
            params["city"] = ctx.location.split(",")[0].strip()
        url = build_url(f"https://api.smartrecruiters.com/v1/companies/{company}/postings", params)
        payload = _guard(lambda: ctx.get_json(url), url)
        for item in payload.get("content", []):
            loc = item.get("location") or {}
            location = ", ".join(v for v in (loc.get("city"), loc.get("region"), loc.get("country")) if v)
            job_type, schedule = normalise_job_type((item.get("typeOfEmployment") or {}).get("label"))
            jobs.append(
                Job(
                    title=item.get("name") or "",
                    organization=(item.get("company") or {}).get("name") or str(ctx.options.get("company") or company),
                    location=location,
                    workplace="remote" if loc.get("remote") else normalise_workplace(location, str(ctx.options.get("workplace") or "")),
                    url=f"https://jobs.smartrecruiters.com/{company}/{item.get('id')}",
                    source=ctx.site.name,
                    site_id=ctx.site.id,
                    description="; ".join(
                        v for v in ((item.get("department") or {}).get("label"), (item.get("function") or {}).get("label"), (item.get("experienceLevel") or {}).get("label")) if v
                    ),
                    job_type=job_type,
                    schedule=schedule,
                    industry=(item.get("industry") or {}).get("label") or "",
                    published=parse_date(item.get("releasedDate")),
                    external_id=f"smartrecruiters:{company}:{item.get('id')}",
                )
            )
    return _cap(jobs, ctx.limit)


# ---------------------------------------------------------------------------
# Recruitee
# ---------------------------------------------------------------------------


def recruitee(ctx: Any) -> list[Job]:
    company = str(ctx.options.get("company") or "").strip()
    if not company:
        raise ValueError("Recruitee needs the company subdomain (the part before .recruitee.com).")
    url = f"https://{company}.recruitee.com/api/offers/"
    payload = _guard(lambda: ctx.get_json(url), url)
    keywords = [k.lower() for k in ctx.keywords if k]
    jobs: list[Job] = []
    for item in payload.get("offers", []):
        title = item.get("title") or ""
        description = f"{item.get('description') or ''} {item.get('requirements') or ''}"
        if not _matches(f"{title} {description}", keywords):
            continue
        job_type, schedule = normalise_job_type(item.get("employment_type_code"))
        salary = item.get("salary") or {}
        location = item.get("location") or ", ".join(v for v in (item.get("city"), item.get("country")) if v)
        jobs.append(
            Job(
                title=title,
                organization=str(ctx.options.get("company_name") or company),
                location=location,
                workplace="remote" if item.get("remote") else normalise_workplace(location, str(ctx.options.get("workplace") or "")),
                url=item.get("careers_url") or "",
                source=ctx.site.name,
                site_id=ctx.site.id,
                description=description,
                salary_min=int(salary["min"]) if salary.get("min") else None,
                salary_max=int(salary["max"]) if salary.get("max") else None,
                salary_currency=salary.get("currency") or "",
                salary_period={"monthly": "month", "yearly": "year", "hourly": "hour"}.get(str(salary.get("period") or ""), ""),
                job_type=job_type,
                schedule=schedule,
                industry=item.get("department") or "",
                published=parse_date(item.get("published_at")),
                external_id=f"recruitee:{company}:{item.get('id')}",
            )
        )
    return _cap(jobs, ctx.limit)


# ---------------------------------------------------------------------------
# Workable
# ---------------------------------------------------------------------------


def workable(ctx: Any) -> list[Job]:
    subdomain = str(ctx.options.get("subdomain") or "").strip()
    if not subdomain:
        raise ValueError("Workable needs the account subdomain (the part before .workable.com or after apply.workable.com/).")
    url = build_url(f"https://www.workable.com/api/accounts/{subdomain}", {"details": "true"})
    payload = _guard(lambda: ctx.get_json(url), url)
    keywords = [k.lower() for k in ctx.keywords if k]
    jobs: list[Job] = []
    for item in payload.get("jobs", []):
        title = item.get("title") or ""
        description = item.get("description") or ""
        if not _matches(f"{title} {description}", keywords):
            continue
        job_type, schedule = normalise_job_type(item.get("employment_type"))
        location = ", ".join(v for v in (item.get("city"), item.get("state"), item.get("country")) if v)
        jobs.append(
            Job(
                title=title,
                organization=payload.get("name") or subdomain,
                location=location,
                workplace="remote" if item.get("telecommuting") else normalise_workplace(location, str(ctx.options.get("workplace") or "")),
                url=item.get("url") or item.get("application_url") or "",
                source=ctx.site.name,
                site_id=ctx.site.id,
                description=description,
                job_type=job_type,
                schedule=schedule,
                industry=", ".join(v for v in (item.get("department"), item.get("function"), item.get("industry")) if v),
                tags=[item.get("experience")] if item.get("experience") else [],
                published=parse_date(item.get("published_on")),
                external_id=f"workable:{subdomain}:{item.get('shortcode') or item.get('code')}",
            )
        )
    return _cap(jobs, ctx.limit)


# ---------------------------------------------------------------------------
# Workday
# ---------------------------------------------------------------------------

_POSTED_RE = re.compile(r"(\d+)\+?\s*day", re.IGNORECASE)


def workday_posted_on(text: str, today: date | None = None) -> str:
    """'Posted Today' / 'Posted Yesterday' / 'Posted 3 Days Ago' / 'Posted 30+ Days Ago' -> ISO date."""
    today = today or date.today()
    lowered = (text or "").lower()
    if "today" in lowered:
        return today.isoformat()
    if "yesterday" in lowered:
        return (today - timedelta(days=1)).isoformat()
    match = _POSTED_RE.search(lowered)
    if match:
        return (today - timedelta(days=int(match.group(1)))).isoformat()
    return parse_date(text)


def workday_base(options: dict[str, Any]) -> tuple[str, str, str]:
    """Return (base_url, tenant, site) from options ``host``/``tenant``/``site`` or a pasted careers URL."""
    tenant = str(options.get("tenant") or "").strip()
    site = str(options.get("site") or "").strip()
    host = str(options.get("host") or "").strip()
    url = str(options.get("url") or "").strip()
    if url:
        match = re.search(r"https?://([\w-]+)\.(wd\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?([\w-]+)", url)
        if match:
            tenant = tenant or match.group(1)
            host = host or f"{match.group(1)}.{match.group(2)}.myworkdayjobs.com"
            site = site or match.group(3)
    if tenant and not host:
        host = f"{tenant}.wd5.myworkdayjobs.com"
    if not tenant or not site:
        raise ValueError("Workday needs the tenant and site, e.g. tenant `ouryahoo`, site `careers` (from ouryahoo.wd5.myworkdayjobs.com/careers).")
    return f"https://{host}", tenant, site


def _resolve_facets(ctx: Any, base: str, tenant: str, site: str, wanted: dict[str, Any]) -> dict[str, list[str]]:
    """Map human-readable facet values ({"locationCountry": "United States"}) to Workday facet ids."""
    if not wanted:
        return {}
    url = f"{base}/wday/cxs/{tenant}/{site}/jobs"
    payload = _guard(lambda: post_json(url, {"appliedFacets": {}, "limit": 1, "offset": 0, "searchText": ""}, timeout=ctx.settings.timeout_seconds, user_agent=ctx.settings.user_agent), url)
    available: dict[str, dict[str, str]] = {}

    def walk(facets: list[dict[str, Any]]) -> None:
        for facet in facets or []:
            param = facet.get("facetParameter") or ""
            values = {}
            for value in facet.get("values") or []:
                if value.get("id"):
                    values[str(value.get("descriptor") or "").lower()] = value["id"]
                if value.get("facetParameter"):
                    walk([value])
            if param:
                available.setdefault(param, {}).update(values)

    walk(payload.get("facets") or [])
    resolved: dict[str, list[str]] = {}
    unknown: list[str] = []
    for param, wanted_values in wanted.items():
        values = wanted_values if isinstance(wanted_values, list) else [wanted_values]
        table = available.get(param, {})
        ids = []
        for value in values:
            text = str(value).strip()
            if not text:
                continue
            if text in table.values():
                ids.append(text)  # already an id
                continue
            hit = table.get(text.lower()) or next((vid for name, vid in table.items() if text.lower() in name), None)
            if hit:
                ids.append(hit)
            else:
                unknown.append(f"{param}={text}")
        if ids:
            resolved[param] = ids
    if unknown:
        options = "; ".join(f"{p}: {', '.join(sorted(v)[:8])}{'…' if len(v) > 8 else ''}" for p, v in available.items() if v)
        ctx.notes.append(f"Workday facet value(s) not found: {', '.join(unknown)}. Available — {options}")
    return resolved


def workday(ctx: Any) -> list[Job]:
    base, tenant, site = workday_base(ctx.options)
    facets = _resolve_facets(ctx, base, tenant, site, dict(ctx.options.get("facets") or {}))
    details = str(ctx.options.get("details") or "auto")
    url = f"{base}/wday/cxs/{tenant}/{site}/jobs"
    jobs: list[Job] = []
    today = date.today()
    for keyword in ctx.keywords or [""]:
        offset = 0
        while len(jobs) < ctx.limit * 2:
            body = {"appliedFacets": facets, "limit": 20, "offset": offset, "searchText": keyword}
            payload = _guard(
                lambda: post_json(url, body, timeout=ctx.settings.timeout_seconds, user_agent=ctx.settings.user_agent), url
            )
            postings = payload.get("jobPostings") or []
            for item in postings:
                path = item.get("externalPath") or ""
                title = item.get("title") or ""
                jobs.append(
                    Job(
                        title=title,
                        organization=str(ctx.options.get("company") or tenant),
                        location=item.get("locationsText") or "",
                        workplace=normalise_workplace(f"{title} {item.get('locationsText') or ''}", str(ctx.options.get("workplace") or "")),
                        url=f"{base}/{site}{path}" if path else base,
                        source=ctx.site.name,
                        site_id=ctx.site.id,
                        description="",
                        published=workday_posted_on(item.get("postedOn") or "", today),
                        external_id=f"workday:{tenant}:{(item.get('bulletFields') or [path])[0]}",
                        tags=[b for b in item.get("bulletFields") or [] if b],
                    )
                )
            total = int(payload.get("total") or 0)
            offset += len(postings)
            if not postings or offset >= total:
                break
    jobs = _cap(jobs, ctx.limit)

    # Detail pages carry the description, time type and country; fetch them for the kept listings.
    if details != "never" and jobs:
        fetched = 0
        for job in jobs:
            if details == "auto" and fetched >= 10:
                break
            path = job.url.split(f"/{site}", 1)[1] if f"/{site}/" in job.url else ""
            if not path:
                continue
            detail_url = f"{base}/wday/cxs/{tenant}/{site}{path}"
            try:
                info = (_guard(lambda: ctx.get_json(detail_url), detail_url) or {}).get("jobPostingInfo") or {}
            except (ValueError, AccessDenied):
                continue
            fetched += 1
            job.description = plain_text(info.get("jobDescription") or "")
            job_type, schedule = normalise_job_type(info.get("timeType"))
            job.job_type = job.job_type or job_type
            job.schedule = job.schedule or schedule
            if info.get("location"):
                job.location = info["location"] + (f"; {info['additionalLocations']}" if info.get("additionalLocations") else "")
            if info.get("startDate"):
                job.published = parse_date(info["startDate"]) or job.published
            if info.get("externalUrl"):
                job.url = info["externalUrl"]
            job.workplace = "remote" if info.get("remoteType") and "remote" in str(info.get("remoteType")).lower() else job.workplace
    return jobs


ATS_ADAPTERS = {
    "greenhouse": greenhouse,
    "lever": lever,
    "ashby": ashby,
    "smartrecruiters": smartrecruiters,
    "recruitee": recruitee,
    "workable": workable,
    "workday": workday,
}


def site_url(provider: str, options: dict[str, Any]) -> str:
    """Representative URL of an ATS site (for the site registry / robots.txt host checks)."""
    try:
        if provider == "greenhouse":
            return f"https://boards-api.greenhouse.io/v1/boards/{options.get('board', '')}/jobs"
        if provider == "lever":
            return f"https://api.lever.co/v0/postings/{options.get('site', '')}"
        if provider == "ashby":
            return f"https://api.ashbyhq.com/posting-api/job-board/{options.get('board', '')}"
        if provider == "smartrecruiters":
            return f"https://api.smartrecruiters.com/v1/companies/{options.get('company_id', '')}/postings"
        if provider == "recruitee":
            return f"https://{options.get('company', '')}.recruitee.com/api/offers/"
        if provider == "workable":
            return f"https://www.workable.com/api/accounts/{options.get('subdomain', '')}"
        if provider == "workday":
            base, tenant, site = workday_base(options)
            return f"{base}/{site}"
    except ValueError:
        return ""
    return ""
