"""Run a search across the configured job sites and apply the preferences."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from jobsearch_config.catalog import provider
from jobsearch_config.schema import AppConfig, SiteConfig
from jobsearch_config.store import resolve_options

from .filters import Match, apply
from .http import FetchError
from .model import Job
from .providers import ADAPTERS, SearchContext


@dataclass
class SiteOutcome:
    site_id: str
    name: str
    provider: str
    fetched: int = 0
    kept: int = 0
    error: str = ""
    seconds: float = 0.0
    attribution: str = ""

    @property
    def ok(self) -> bool:
        return not self.error


@dataclass
class SearchReport:
    results: list[tuple[Job, Match]] = field(default_factory=list)
    outcomes: list[SiteOutcome] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    strict: bool = True

    @property
    def errors(self) -> list[str]:
        return [f"{o.name}: {o.error}" for o in self.outcomes if o.error]

    @property
    def attributions(self) -> list[str]:
        return sorted({o.attribution for o in self.outcomes if o.attribution and o.fetched})

    def rows(self) -> list[dict[str, Any]]:
        """Flatten to dicts (for DataFrames / CSV)."""
        out: list[dict[str, Any]] = []
        for job, match in self.results:
            row = job.to_dict()
            row["score"] = match.score
            row["passes"] = match.passed
            row["matched_skills"] = ", ".join(match.matched_skills)
            row["filter_notes"] = "; ".join(match.reasons or match.notes)
            row["tags"] = ", ".join(job.tags)
            out.append(row)
        return out


def _keywords(config: AppConfig, override: str | None) -> list[str]:
    if override is not None and override.strip():
        return [override.strip()]
    if override is not None and not override.strip():
        return []
    return config.preferences.titles[:3]


def _location(config: AppConfig) -> str:
    for loc in config.preferences.locations:
        if loc.strip().lower() not in {"remote", "anywhere", "worldwide", "global"}:
            return loc.strip()
    return ""


def search_site(site: SiteConfig, config: AppConfig, keywords: list[str]) -> tuple[list[Job], SiteOutcome]:
    spec = provider(site.provider)
    outcome = SiteOutcome(site_id=site.id, name=site.name, provider=site.provider, attribution=spec.attribution if spec else "")
    adapter = ADAPTERS.get(site.provider)
    if adapter is None:
        outcome.error = f"no adapter for provider '{site.provider}'"
        return [], outcome
    ctx = SearchContext(
        site=site,
        prefs=config.preferences,
        settings=config.search,
        options=resolve_options(site.options),
        keywords=keywords,
        location=_location(config),
    )
    started = time.perf_counter()
    try:
        jobs = adapter(ctx)
    except (FetchError, ValueError, KeyError, TypeError, AttributeError) as exc:
        outcome.error = str(exc) or exc.__class__.__name__
        jobs = []
    outcome.seconds = round(time.perf_counter() - started, 2)
    outcome.fetched = len(jobs)
    return jobs, outcome


def run_search(
    config: AppConfig,
    *,
    keyword: str | None = None,
    site_ids: list[str] | None = None,
    strict: bool | None = None,
    today: date | None = None,
    parallel: bool = True,
) -> SearchReport:
    """Query every enabled site (or ``site_ids``) and return filtered, ranked results.

    ``keyword=None`` uses the preferred titles from the configuration; an
    explicit string overrides them for this run; ``""`` means "no keyword".
    """
    strict = config.search.strict_filtering if strict is None else strict
    keywords = _keywords(config, keyword)
    sites = [s for s in config.enabled_sites() if not site_ids or s.id in site_ids]
    report = SearchReport(keywords=keywords, strict=strict)
    all_jobs: list[Job] = []

    if parallel and len(sites) > 1:
        with ThreadPoolExecutor(max_workers=min(6, len(sites))) as pool:
            futures = {pool.submit(search_site, site, config, keywords): site for site in sites}
            collected = [future.result() for future in as_completed(futures)]
        order = {site.id: index for index, site in enumerate(sites)}
        collected.sort(key=lambda pair: order[pair[1].site_id])
    else:
        collected = [search_site(site, config, keywords) for site in sites]

    per_site: dict[str, int] = {}
    for jobs, outcome in collected:
        report.outcomes.append(outcome)
        all_jobs.extend(jobs)

    if config.search.dedupe_by_url:
        seen: set[str] = set()
        unique: list[Job] = []
        for job in all_jobs:
            key = (job.url or job.external_id or f"{job.title}|{job.organization}").strip().lower().rstrip("/")
            if key in seen:
                continue
            seen.add(key)
            unique.append(job)
        all_jobs = unique

    report.results = apply(all_jobs, config.preferences, strict=strict, today=today)
    for job, match in report.results:
        if match.passed:
            per_site[job.site_id] = per_site.get(job.site_id, 0) + 1
    for outcome in report.outcomes:
        outcome.kept = per_site.get(outcome.site_id, 0)
    return report


def test_site(site: SiteConfig, config: AppConfig, keyword: str | None = None) -> tuple[list[Job], SiteOutcome]:
    """Fetch a single site without filtering (used by the configuration dashboard's 'Test' button)."""
    return search_site(site, config, _keywords(config, keyword))
