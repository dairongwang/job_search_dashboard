"""Catalog of job-site providers the app knows how to talk to.

The catalog is pure data. It drives the configuration dashboard (which
options to show for a site) and documents what each adapter pushes to the
remote API versus what is filtered locally. The adapters themselves live in
``jobsearch_sources.providers``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class OptionSpec:
    key: str
    label: str
    kind: str = "text"  # text | secret | select | int | bool | textarea | json
    default: Any = ""
    help: str = ""
    choices: tuple[str, ...] = ()
    required: bool = False


@dataclass(frozen=True)
class ProviderSpec:
    key: str
    label: str
    description: str
    homepage: str
    requires_key: bool = False
    custom: bool = False  # user supplies the URL (generic adapters)
    attribution: str = ""
    server_side: tuple[str, ...] = ()  # preferences the adapter pushes to the API
    options: tuple[OptionSpec, ...] = field(default_factory=tuple)
    default_site: dict[str, Any] | None = None  # suggested site entry for "add from catalog"


REMOTIVE_CATEGORIES = (
    "",
    "software-dev",
    "data",
    "devops",
    "product",
    "design",
    "marketing",
    "sales",
    "customer-support",
    "business",
    "finance-legal",
    "hr",
    "writing",
    "all-others",
)

JOBICY_GEOS = (
    "",
    "usa",
    "canada",
    "uk",
    "europe",
    "emea",
    "apac",
    "latam",
    "australia",
    "germany",
    "france",
    "netherlands",
    "spain",
    "portugal",
    "ireland",
    "india",
    "singapore",
)

JOBICY_INDUSTRIES = (
    "",
    "engineering",
    "data-science",
    "dev",
    "devops",
    "product",
    "design",
    "marketing",
    "sales",
    "customer-support",
    "hr",
    "finance",
    "legal",
    "management",
    "supporting",
    "technical-support",
    "seo",
    "copywriting",
    "business",
    "admin",
)

ADZUNA_COUNTRIES = ("us", "gb", "ca", "au", "de", "fr", "nl", "in", "nz", "sg", "za", "at", "be", "br", "ch", "es", "it", "mx", "pl")

PROVIDERS: dict[str, ProviderSpec] = {
    "remotive": ProviderSpec(
        key="remotive",
        label="Remotive",
        description="Public remote-job feed. No key needed; Remotive asks for attribution and light use.",
        homepage="https://remotive.com/remote-jobs",
        attribution="Listings courtesy of Remotive (https://remotive.com).",
        server_side=("titles/keyword", "category"),
        options=(
            OptionSpec(
                "category",
                "Category",
                "select",
                "",
                "Remotive job category. Leave blank to search all categories.",
                REMOTIVE_CATEGORIES,
            ),
        ),
        default_site={"id": "remotive", "name": "Remotive", "enabled": True, "max_results": 20},
    ),
    "jobicy": ProviderSpec(
        key="jobicy",
        label="Jobicy",
        description="Public remote-job API with geo and industry filters. No key needed.",
        homepage="https://jobicy.com/jobs-rss-feed",
        attribution="Listings courtesy of Jobicy (https://jobicy.com).",
        server_side=("titles/keyword (tag)", "geo", "industry"),
        options=(
            OptionSpec("geo", "Region", "select", "", "Restrict to a Jobicy region code.", JOBICY_GEOS),
            OptionSpec("industry", "Industry", "select", "", "Jobicy industry slug.", JOBICY_INDUSTRIES),
        ),
        default_site={"id": "jobicy", "name": "Jobicy", "enabled": True, "max_results": 20},
    ),
    "arbeitnow": ProviderSpec(
        key="arbeitnow",
        label="Arbeitnow",
        description="Europe-leaning job board API (many Germany/EU listings, remote flags, visa sponsorship tags). No key.",
        homepage="https://www.arbeitnow.com/api/job-board-api",
        attribution="Listings courtesy of Arbeitnow (https://www.arbeitnow.com).",
        server_side=("titles/keyword",),
        options=(
            OptionSpec("pages", "Pages to fetch", "int", 1, "Each page holds ~100 listings; keep small.", ()),
        ),
        default_site={"id": "arbeitnow", "name": "Arbeitnow", "enabled": False, "max_results": 30},
    ),
    "remoteok": ProviderSpec(
        key="remoteok",
        label="Remote OK",
        description="Public JSON feed of remote jobs with tags and salary bands. No key; please keep request volume low.",
        homepage="https://remoteok.com/api",
        attribution="Listings courtesy of Remote OK (https://remoteok.com). Please link back to the original listing.",
        server_side=("skills (tags)",),
        options=(),
        default_site={"id": "remoteok", "name": "Remote OK", "enabled": False, "max_results": 30},
    ),
    "themuse": ProviderSpec(
        key="themuse",
        label="The Muse",
        description="Public jobs API covering many on-site and hybrid roles in the US. API key optional for higher limits.",
        homepage="https://www.themuse.com/developers/api/v2",
        attribution="Listings courtesy of The Muse (https://www.themuse.com).",
        server_side=("category", "location", "level"),
        options=(
            OptionSpec("category", "Category", "text", "", "Muse category, e.g. 'Data and Analytics', 'Software Engineering'."),
            OptionSpec("level", "Level", "select", "", "Experience level filter.", ("", "Internship", "Entry Level", "Mid Level", "Senior Level", "Management")),
            OptionSpec("api_key", "API key (optional)", "secret", "", "Raises the rate limit. May be written as ${THEMUSE_API_KEY}."),
            OptionSpec("pages", "Pages to fetch", "int", 1, "20 listings per page.", ()),
        ),
        default_site={"id": "themuse", "name": "The Muse", "enabled": False, "max_results": 20},
    ),
    "himalayas": ProviderSpec(
        key="himalayas",
        label="Himalayas",
        description="Remote jobs API with structured salary and employment-type fields. No key.",
        homepage="https://himalayas.app/jobs/api",
        attribution="Listings courtesy of Himalayas (https://himalayas.app).",
        server_side=(),
        options=(),
        default_site={"id": "himalayas", "name": "Himalayas", "enabled": False, "max_results": 30},
    ),
    "adzuna": ProviderSpec(
        key="adzuna",
        label="Adzuna",
        description="Aggregator with strong location, salary and permanent/contract filters. Needs a free app id + key.",
        homepage="https://developer.adzuna.com/",
        requires_key=True,
        attribution="Listings courtesy of Adzuna (https://www.adzuna.com).",
        server_side=("titles/keyword", "location", "salary range", "permanent/contract", "full/part-time", "posted within"),
        options=(
            OptionSpec("country", "Country", "select", "us", "Adzuna country endpoint.", ADZUNA_COUNTRIES, required=True),
            OptionSpec("app_id", "App ID", "secret", "${ADZUNA_APP_ID}", "From developer.adzuna.com.", required=True),
            OptionSpec("app_key", "App key", "secret", "${ADZUNA_APP_KEY}", "From developer.adzuna.com.", required=True),
        ),
        default_site={"id": "adzuna", "name": "Adzuna", "enabled": False, "max_results": 25},
    ),
    "reed": ProviderSpec(
        key="reed",
        label="Reed (UK)",
        description="UK job board with permanent / contract / temp and salary filters. Needs a free API key.",
        homepage="https://www.reed.co.uk/developers/jobseeker",
        requires_key=True,
        attribution="Listings courtesy of Reed.co.uk.",
        server_side=("titles/keyword", "location", "salary range", "permanent/contract/temp", "full/part-time"),
        options=(
            OptionSpec("api_key", "API key", "secret", "${REED_API_KEY}", "From reed.co.uk/developers.", required=True),
            OptionSpec("distance_miles", "Distance (miles)", "int", 15, "Radius around the first preferred location.", ()),
        ),
        default_site={"id": "reed", "name": "Reed", "enabled": False, "max_results": 25},
    ),
    "usajobs": ProviderSpec(
        key="usajobs",
        label="USAJOBS",
        description="US federal government vacancies. Needs a free API key and the email it was registered with.",
        homepage="https://developer.usajobs.gov/",
        requires_key=True,
        attribution="Data from USAJOBS (https://www.usajobs.gov).",
        server_side=("titles/keyword", "location", "salary minimum"),
        options=(
            OptionSpec("api_key", "API key", "secret", "${USAJOBS_API_KEY}", "Authorization-Key header.", required=True),
            OptionSpec("email", "Registered email", "text", "${USAJOBS_EMAIL}", "User-Agent header required by USAJOBS.", required=True),
        ),
        default_site={"id": "usajobs", "name": "USAJOBS", "enabled": False, "max_results": 25},
    ),
    "rss": ProviderSpec(
        key="rss",
        label="RSS / Atom feed",
        description="Any job board that publishes an RSS or Atom feed (company career pages, niche boards, Google Alerts).",
        homepage="",
        custom=True,
        server_side=(),
        options=(
            OptionSpec(
                "url",
                "Feed URL",
                "text",
                "",
                "May contain {keyword} and {location} placeholders, e.g. https://example.com/jobs.rss?q={keyword}",
                required=True,
            ),
            OptionSpec(
                "title_format",
                "Title format",
                "select",
                "",
                "How the feed composes titles, so the company can be split out.",
                ("", "title at company", "company: title"),
            ),
            OptionSpec("workplace", "Default workplace", "select", "", "Used when the feed does not say.", ("", "remote", "hybrid", "onsite")),
        ),
    ),
    "json": ProviderSpec(
        key="json",
        label="Generic JSON API",
        description="Any JSON endpoint. Map response fields to the job columns with dotted paths.",
        homepage="",
        custom=True,
        server_side=(),
        options=(
            OptionSpec(
                "url",
                "Endpoint URL",
                "text",
                "",
                "May contain {keyword}, {location}, {limit} placeholders.",
                required=True,
            ),
            OptionSpec("items_path", "Items path", "text", "", "Dotted path to the list of jobs, e.g. 'data.jobs'. Blank if the response is a list."),
            OptionSpec(
                "mapping",
                "Field mapping (JSON)",
                "json",
                {
                    "title": "title",
                    "organization": "company",
                    "location": "location",
                    "url": "url",
                    "description": "description",
                    "salary_min": "salary_min",
                    "salary_max": "salary_max",
                    "job_type": "type",
                    "published": "date",
                    "id": "id",
                },
                "Job column -> dotted path in each item.",
            ),
            OptionSpec("headers", "Extra headers (JSON)", "json", {}, "e.g. {\"Authorization\": \"Bearer ${MY_TOKEN}\"}"),
            OptionSpec("workplace", "Default workplace", "select", "", "Used when the item does not say.", ("", "remote", "hybrid", "onsite")),
        ),
    ),
}


def provider(key: str) -> ProviderSpec | None:
    return PROVIDERS.get((key or "").lower())


def builtin_providers() -> list[ProviderSpec]:
    return [spec for spec in PROVIDERS.values() if not spec.custom]


def custom_providers() -> list[ProviderSpec]:
    return [spec for spec in PROVIDERS.values() if spec.custom]


def default_options(key: str) -> dict[str, Any]:
    spec = provider(key)
    if not spec:
        return {}
    return {opt.key: (dict(opt.default) if isinstance(opt.default, dict) else opt.default) for opt in spec.options}
