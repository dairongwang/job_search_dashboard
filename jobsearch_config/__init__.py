"""Separable configuration library for the Job Search Dashboard.

Zero third-party dependencies. Used by:

* ``config_dashboard.py`` - the configuration UI (development/operation),
* ``app.py``              - the main dashboard (reads the config),
* ``python -m jobsearch_config`` - CLI for deployment scripts and CI.
"""

from .catalog import PROVIDERS, ProviderSpec, OptionSpec, provider, builtin_providers, custom_providers, default_options
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
from .validate import Issue, has_errors, validate

__all__ = [
    "PROVIDERS", "ProviderSpec", "OptionSpec", "provider", "builtin_providers", "custom_providers", "default_options",
    "default_config", "default_sites",
    "CONFIG_VERSION", "CURRENCIES", "INDUSTRIES", "JOB_TYPES", "SALARY_PERIODS", "SCHEDULES", "WORKPLACES",
    "AppConfig", "JobPreferences", "SalaryRange", "SearchSettings", "SiteConfig",
    "ENV_PATH_VAR", "config_path", "dumps", "exists", "load_config", "loads", "mtime",
    "resolve_options", "resolve_secret", "save_config",
    "Issue", "has_errors", "validate",
]
