"""Separable configuration library for the Job Search Dashboard.

Zero third-party dependencies. Used by:

* ``config_dashboard.py`` - the configuration UI (development/operation),
* ``app.py``              - the main dashboard (reads the config),
* ``python -m jobsearch_config`` - CLI for deployment scripts and CI.
"""

from .catalog import PROVIDERS, ProviderSpec, OptionSpec, provider, builtin_providers, custom_providers, platform_providers, default_options
from .defaults import default_config, default_sites
from .schema import (
    CONFIG_VERSION,
    CURRENCIES,
    INDUSTRIES,
    JOB_TYPES,
    SALARY_PERIODS,
    SCHEDULES,
    WORKPLACES,
    AppConfig,
    JobPreferences,
    SalaryRange,
    SearchSettings,
    SiteConfig,
)
from .store import (
    ENV_PATH_VAR,
    config_path,
    dumps,
    exists,
    load_config,
    loads,
    mtime,
    resolve_options,
    resolve_secret,
    save_config,
)
from .registry import ENV_REGISTRY_VAR, SEED_SITES, Registry, SiteRecord, block_reason, classify_outcome, host_of, load_registry, registry_path
from .admin import ENV_ADMIN_TOKEN, AdminRequired, admin_configured, set_web_page_search, signature_valid, verify_token, web_page_search_allowed
from .validate import Issue, has_errors, search_form_status, validate

__all__ = [
    "PROVIDERS", "ProviderSpec", "OptionSpec", "provider", "builtin_providers", "custom_providers", "platform_providers", "default_options",
    "default_config", "default_sites",
    "CONFIG_VERSION", "CURRENCIES", "INDUSTRIES", "JOB_TYPES", "SALARY_PERIODS", "SCHEDULES", "WORKPLACES",
    "AppConfig", "JobPreferences", "SalaryRange", "SearchSettings", "SiteConfig",
    "ENV_PATH_VAR", "config_path", "dumps", "exists", "load_config", "loads", "mtime",
    "resolve_options", "resolve_secret", "save_config",
    "Issue", "has_errors", "search_form_status", "validate",
    "ENV_ADMIN_TOKEN", "AdminRequired", "admin_configured", "set_web_page_search", "signature_valid", "verify_token", "web_page_search_allowed",
    "ENV_REGISTRY_VAR", "SEED_SITES", "Registry", "SiteRecord", "block_reason", "classify_outcome", "host_of", "load_registry", "registry_path",
]
