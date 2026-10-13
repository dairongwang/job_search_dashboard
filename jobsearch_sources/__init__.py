"""Job-site adapters, preference filters and the search orchestrator.

Depends only on the standard library and ``jobsearch_config``.
"""

from .feeds import KNOWN_NO_FEED, ProbeResult, discover_feeds, explain_fetch_error, known_site_guidance, probe
from .filters import Match, apply, evaluate
from .investigate import Investigation, detect_platform, form_controls, format_report, investigate
from .http import FetchError, set_fetcher
from .model import Job, normalise_job_type, parse_salary_text, plain_text
from .providers import ADAPTERS, KEYWORD_PROVIDERS, SearchContext
from .search import SearchReport, SiteOutcome, run_search, search_site, test_site

__all__ = [
    "KNOWN_NO_FEED", "ProbeResult", "discover_feeds", "explain_fetch_error", "known_site_guidance", "probe",
    "Match", "apply", "evaluate",
    "Investigation", "detect_platform", "form_controls", "format_report", "investigate",
    "FetchError", "set_fetcher",
    "Job", "normalise_job_type", "parse_salary_text", "plain_text",
    "ADAPTERS", "KEYWORD_PROVIDERS", "SearchContext",
    "SearchReport", "SiteOutcome", "run_search", "search_site", "test_site",
]
