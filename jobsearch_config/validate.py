"""Validation of an ``AppConfig``.

Returns a list of ``Issue`` objects rather than raising, so the dashboard can
show everything at once and the CLI can exit non-zero on errors only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from typing import TYPE_CHECKING

from .catalog import provider
from .schema import CONFIG_VERSION, JOB_TYPES, SCHEDULES, WORKPLACES, AppConfig

if TYPE_CHECKING:  # pragma: no cover
    from .registry import Registry

SITE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
ENV_REF_RE = re.compile(r"^\$\{([A-Za-z_][A-Za-z0-9_]*)\}$")


@dataclass(frozen=True)
class Issue:
    level: str  # "error" | "warning"
    where: str
    message: str

    def __str__(self) -> str:
        return f"[{self.level}] {self.where}: {self.message}"


def validate(config: AppConfig, registry: "Registry | None" = None) -> list[Issue]:
    """Validate ``config``. ``registry`` defaults to the persisted site registry (pass ``False`` to skip)."""
    issues: list[Issue] = []
    if registry is None:
        try:
            from .registry import load_registry

            registry = load_registry()
        except (OSError, ValueError):
            registry = False  # type: ignore[assignment]

    if config.version > CONFIG_VERSION:
        issues.append(Issue("warning", "version", f"Config version {config.version} is newer than this app ({CONFIG_VERSION})."))

    # --- sites -------------------------------------------------------------
    seen_ids: set[str] = set()
    if not config.sites:
        issues.append(Issue("warning", "sites", "No job sites configured; searches will return nothing."))
    elif not config.enabled_sites():
        issues.append(Issue("warning", "sites", "All job sites are disabled; searches will return nothing."))

    for site in config.sites:
        where = f"sites.{site.id or '?'}"
        if not SITE_ID_RE.match(site.id):
            issues.append(Issue("error", where, "Site id must be lowercase letters, digits, '-' or '_' (max 40 chars)."))
        if site.id in seen_ids:
            issues.append(Issue("error", where, "Duplicate site id."))
        seen_ids.add(site.id)

        spec = provider(site.provider)
        if spec is None:
            issues.append(Issue("error", where, f"Unknown provider '{site.provider}'."))
            continue

        for opt in spec.options:
            value = site.options.get(opt.key, opt.default)
            if opt.required and site.enabled and value in (None, ""):
                issues.append(Issue("error", where, f"Option '{opt.label}' is required for {spec.label}."))
            if opt.kind == "select" and opt.choices and value not in opt.choices and value not in ("", None):
                issues.append(Issue("error", where, f"Option '{opt.label}' must be one of {', '.join(c or '(blank)' for c in opt.choices)}."))
            if opt.kind == "int" and value not in (None, ""):
                try:
                    int(value)
                except (TypeError, ValueError):
                    issues.append(Issue("error", where, f"Option '{opt.label}' must be an integer."))
            if opt.kind == "json" and value is not None:
                expected = (list,) if isinstance(opt.default, list) else (dict,)
                if not isinstance(value, expected):
                    issues.append(Issue("error", where, f"Option '{opt.label}' must be a JSON {'array' if expected == (list,) else 'object'}."))
            if opt.kind == "secret" and isinstance(value, str):
                match = ENV_REF_RE.match(value)
                if match and site.enabled:
                    import os

                    if not os.environ.get(match.group(1)):
                        issues.append(
                            Issue("warning", where, f"Option '{opt.label}' references ${{{match.group(1)}}} which is not set in this environment.")
                        )
        if spec.custom:
            url = str(site.options.get("url") or "")
            if url and not url.lower().startswith(("http://", "https://")):
                issues.append(Issue("error", where, "URL must start with http:// or https://."))
            if url and registry and site.enabled:
                blocked = registry.forbidden(url)
                if blocked is not None:
                    issues.append(
                        Issue(
                            "error",
                            where,
                            f"{blocked.host} forbids automated access (registry, checked {blocked.updated_at}): {blocked.message} "
                            "Disable the site or re-check it in the Site registry tab.",
                        )
                    )

    # --- preferences ----------------------------------------------------------
    prefs = config.preferences
    if not prefs.titles and not prefs.skills:
        issues.append(Issue("warning", "preferences", "No target titles or skills; results will be broad and unranked."))
    for value, allowed, name in (
        (prefs.job_types, JOB_TYPES, "job_types"),
        (prefs.schedules, SCHEDULES, "schedules"),
        (prefs.workplaces, WORKPLACES, "workplaces"),
    ):
        bad = [v for v in value if v not in allowed]
        if bad:
            issues.append(Issue("error", f"preferences.{name}", f"Unknown values: {', '.join(bad)}."))

    salary = prefs.salary
    if salary.minimum is not None and salary.minimum < 0:
        issues.append(Issue("error", "preferences.salary", "Minimum salary cannot be negative."))
    if salary.minimum is not None and salary.maximum is not None and salary.minimum > salary.maximum:
        issues.append(Issue("error", "preferences.salary", "Minimum salary is greater than maximum."))
    if prefs.posted_within_days is not None and prefs.posted_within_days <= 0:
        issues.append(Issue("error", "preferences.posted_within_days", "Must be a positive number of days or blank."))
    if prefs.min_skill_matches > len(prefs.skills):
        issues.append(Issue("error", "preferences.min_skill_matches", "Cannot require more skill matches than skills listed."))

    return issues


def has_errors(issues: list[Issue]) -> bool:
    return any(issue.level == "error" for issue in issues)
