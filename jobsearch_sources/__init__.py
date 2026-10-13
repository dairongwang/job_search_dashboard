"""Job-site adapters, preference filters and the search orchestrator.

Depends only on the standard library and ``jobsearch_config``.
"""

from .filters import Match, apply, evaluate
from .http import FetchError, set_fetcher
from .model import Job, normalise_job_type, parse_salary_text, plain_text
from .providers import ADAPTERS, KEYWORD_PROVIDERS, SearchContext
from .search import SearchReport, SiteOutcome, run_search, search_site, test_site

__all__ = [
    "Match", "apply", "evaluate",
    "FetchError", "set_fetcher",
    "Job", "normalise_job_type", "parse_salary_text", "plain_text",
    "ADAPTERS", "KEYWORD_PROVIDERS", "SearchContext",
    "SearchReport", "SiteOutcome", "run_search", "search_site", "test_site",
]
