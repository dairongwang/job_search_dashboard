"""Factory for a sensible starting configuration."""

from __future__ import annotations

from .catalog import PROVIDERS, default_options
from .schema import AppConfig, JobPreferences, SalaryRange, SearchSettings, SiteConfig


def default_sites() -> list[SiteConfig]:
    sites: list[SiteConfig] = []
    for spec in PROVIDERS.values():
        if spec.custom or not spec.default_site:
            continue
        entry = dict(spec.default_site)
        sites.append(
            SiteConfig(
                id=entry["id"],
                provider=spec.key,
                name=entry.get("name", spec.label),
                enabled=bool(entry.get("enabled", False)),
                max_results=int(entry.get("max_results", 20)),
                options=default_options(spec.key),
                notes="",
            )
        )
    return sites


def default_config() -> AppConfig:
    config = AppConfig(
        sites=default_sites(),
        preferences=JobPreferences(
            titles=["data analyst"],
            industries=[],
            skills=["SQL", "Python", "Excel", "Tableau"],
            min_skill_matches=0,
            exclude_keywords=[],
            locations=["Remote", "Philadelphia, PA"],
            workplaces=["remote", "hybrid", "onsite"],
            job_types=["permanent", "contract", "temporary", "freelance", "internship"],
            schedules=["full_time", "part_time"],
            include_unknown_job_type=True,
            salary=SalaryRange(minimum=None, maximum=None, currency="USD", period="year", include_unlisted=True),
            posted_within_days=30,
        ),
        search=SearchSettings(),
    )
    config.touch()
    return config
