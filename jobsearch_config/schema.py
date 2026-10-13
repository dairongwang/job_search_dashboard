"""Configuration schema for the job search dashboard.

Plain dataclasses, no third-party dependencies, so the same module can be
imported by the configuration dashboard, the main app, the CLI and tests.

The configuration answers two questions:

* **Which job sites should be searched?** -> ``AppConfig.sites`` (a list of
  ``SiteConfig``; each one names a provider adapter plus provider options).
* **What kind of jobs does the user want?** -> ``AppConfig.preferences``
  (industry, skills, location, salary range, job types, ...).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

CONFIG_VERSION = 1

# ---------------------------------------------------------------------------
# Controlled vocabularies (shared by the config UI, providers and filters)
# ---------------------------------------------------------------------------

JOB_TYPES: dict[str, str] = {
    "permanent": "Permanent (direct hire)",
    "contract": "Contract",
    "temporary": "Temporary",
    "freelance": "Freelance",
    "internship": "Internship",
}

SCHEDULES: dict[str, str] = {
    "full_time": "Full-time",
    "part_time": "Part-time",
}

WORKPLACES: dict[str, str] = {
    "remote": "Remote",
    "hybrid": "Hybrid",
    "onsite": "On-site",
}

INDUSTRIES: list[str] = [
    "Software / Technology",
    "Data / Analytics",
    "Finance / Banking",
    "Healthcare / Life Sciences",
    "Education",
    "Government / Public Sector",
    "Retail / E-commerce",
    "Manufacturing / Engineering",
    "Consulting / Professional Services",
    "Media / Marketing / Advertising",
    "Non-profit",
    "Energy / Utilities",
    "Telecommunications",
    "Logistics / Transportation",
    "Hospitality / Travel",
    "Legal",
    "Real Estate / Construction",
    "Human Resources / Recruiting",
]

CURRENCIES: list[str] = ["USD", "EUR", "GBP", "CAD", "AUD", "INR", "CHF", "SGD", "JPY"]
SALARY_PERIODS: dict[str, str] = {"year": "per year", "month": "per month", "day": "per day", "hour": "per hour"}


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


def _clean_list(values: Any) -> list[str]:
    """Normalise a list-ish value into a de-duplicated list of stripped strings."""
    if values is None:
        return []
    if isinstance(values, str):
        values = [part for part in values.replace("\n", ",").split(",")]
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value).strip()
        key = text.lower()
        if text and key not in seen:
            seen.add(key)
            out.append(text)
    return out


def _opt_int(value: Any) -> int | None:
    if value in (None, "", False):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


@dataclass
class SiteConfig:
    """One job site to query.

    ``provider`` picks the adapter (see ``jobsearch_config.catalog``). ``options``
    holds provider-specific settings such as an API key, country code, category,
    feed URL or a JSON field mapping. Secrets may be written as ``${ENV_NAME}``
    and are resolved from the environment at run time.
    """

    id: str
    provider: str
    name: str = ""
    enabled: bool = True
    max_results: int = 20
    options: dict[str, Any] = field(default_factory=dict)
    notes: str = ""

    def __post_init__(self) -> None:
        self.id = str(self.id).strip()
        self.provider = str(self.provider).strip().lower()
        self.name = str(self.name or self.id).strip()
        self.enabled = bool(self.enabled)
        self.max_results = max(1, min(int(self.max_results or 20), 200))
        self.options = dict(self.options or {})
        self.notes = str(self.notes or "")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SiteConfig":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class SalaryRange:
    minimum: int | None = None
    maximum: int | None = None
    currency: str = "USD"
    period: str = "year"
    include_unlisted: bool = True  # keep listings that do not publish pay

    def __post_init__(self) -> None:
        self.minimum = _opt_int(self.minimum)
        self.maximum = _opt_int(self.maximum)
        self.currency = (self.currency or "USD").upper()
        self.period = self.period if self.period in SALARY_PERIODS else "year"
        self.include_unlisted = bool(self.include_unlisted)

    @property
    def is_set(self) -> bool:
        return self.minimum is not None or self.maximum is not None

    def describe(self) -> str:
        if not self.is_set:
            return "any"
        low = f"{self.minimum:,}" if self.minimum is not None else "…"
        high = f"{self.maximum:,}" if self.maximum is not None else "…"
        return f"{low}–{high} {self.currency} {SALARY_PERIODS.get(self.period, self.period)}"

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "SalaryRange":
        data = data or {}
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class JobPreferences:
    """What kind of jobs the user wants."""

    titles: list[str] = field(default_factory=list)  # role keywords, e.g. "data analyst"
    industries: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)  # ranked; more matches = higher score
    min_skill_matches: int = 0  # 0 = skills only affect ranking
    exclude_keywords: list[str] = field(default_factory=list)
    locations: list[str] = field(default_factory=list)  # cities, regions, countries
    workplaces: list[str] = field(default_factory=lambda: ["remote", "hybrid", "onsite"])
    job_types: list[str] = field(default_factory=lambda: list(JOB_TYPES))
    schedules: list[str] = field(default_factory=lambda: list(SCHEDULES))
    include_unknown_job_type: bool = True
    salary: SalaryRange = field(default_factory=SalaryRange)
    posted_within_days: int | None = 30

    def __post_init__(self) -> None:
        self.titles = _clean_list(self.titles)
        self.industries = _clean_list(self.industries)
        self.skills = _clean_list(self.skills)
        self.min_skill_matches = max(0, int(self.min_skill_matches or 0))
        self.exclude_keywords = _clean_list(self.exclude_keywords)
        self.locations = _clean_list(self.locations)
        self.workplaces = [w for w in _clean_list(self.workplaces) if w in WORKPLACES] or list(WORKPLACES)
        self.job_types = [j for j in _clean_list(self.job_types) if j in JOB_TYPES] or list(JOB_TYPES)
        self.schedules = [s for s in _clean_list(self.schedules) if s in SCHEDULES] or list(SCHEDULES)
        self.include_unknown_job_type = bool(self.include_unknown_job_type)
        if not isinstance(self.salary, SalaryRange):
            self.salary = SalaryRange.from_dict(self.salary)
        self.posted_within_days = _opt_int(self.posted_within_days)

    @property
    def remote_only(self) -> bool:
        return self.workplaces == ["remote"]

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "JobPreferences":
        data = data or {}
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class SearchSettings:
    """Cross-site behaviour of the search engine."""

    timeout_seconds: int = 15
    strict_filtering: bool = True  # drop listings that fail hard filters (vs. only rank lower)
    dedupe_by_url: bool = True
    user_agent: str = "JobSearchDashboard/2.0 (personal local tracker)"

    def __post_init__(self) -> None:
        self.timeout_seconds = max(3, min(int(self.timeout_seconds or 15), 120))
        self.strict_filtering = bool(self.strict_filtering)
        self.dedupe_by_url = bool(self.dedupe_by_url)
        self.user_agent = str(self.user_agent or SearchSettings.user_agent)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "SearchSettings":
        data = data or {}
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class AppConfig:
    version: int = CONFIG_VERSION
    sites: list[SiteConfig] = field(default_factory=list)
    preferences: JobPreferences = field(default_factory=JobPreferences)
    search: SearchSettings = field(default_factory=SearchSettings)
    updated_at: str = ""

    # -- serialisation -----------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "updated_at": self.updated_at,
            "sites": [asdict(site) for site in self.sites],
            "preferences": asdict(self.preferences),
            "search": asdict(self.search),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "AppConfig":
        data = data or {}
        sites = [SiteConfig.from_dict(s) for s in data.get("sites", []) if isinstance(s, dict) and s.get("id")]
        return cls(
            version=int(data.get("version") or CONFIG_VERSION),
            sites=sites,
            preferences=JobPreferences.from_dict(data.get("preferences")),
            search=SearchSettings.from_dict(data.get("search")),
            updated_at=str(data.get("updated_at") or ""),
        )

    # -- helpers -------------------------------------------------------------

    def touch(self) -> None:
        self.updated_at = datetime.now().isoformat(timespec="seconds")

    def enabled_sites(self) -> list[SiteConfig]:
        return [s for s in self.sites if s.enabled]

    def get_site(self, site_id: str) -> SiteConfig | None:
        for site in self.sites:
            if site.id == site_id:
                return site
        return None

    def upsert_site(self, site: SiteConfig) -> None:
        for index, existing in enumerate(self.sites):
            if existing.id == site.id:
                self.sites[index] = site
                return
        self.sites.append(site)

    def remove_site(self, site_id: str) -> bool:
        before = len(self.sites)
        self.sites = [s for s in self.sites if s.id != site_id]
        return len(self.sites) != before
