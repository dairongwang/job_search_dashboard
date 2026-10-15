"""Compliance scan: are the configured sites still allowed to be accessed automatically?

A site that was fine when it was added can change its mind — publish a
robots.txt that disallows the pages, start answering scripts with 403, or
be recorded as prohibiting robots by its terms. ``scan()`` re-checks every
custom / careers-platform site in the configuration (feeds, JSON APIs, web
pages, search-form sites, Workday & co.) against the three rules the app
applies everywhere:

1. **policy** — the host is a policy block in the site registry (its terms
   prohibit robots/scrapers; lifted only by an administrator),
2. **robots.txt** — the site's URL is disallowed for our crawler token,
3. **access** — the host answers the URL with 401/403/429.

Non-compliant sites are **disabled** in the configuration (with a dated note
explaining why) and the registry row is updated, so the next search skips
them. The scan runs once a day from the main app (``run_if_due``, in the
background), on demand from the configuration dashboard, or from cron /
Task Scheduler with ``python -m jobsearch_sources compliance-scan``.
"""

from __future__ import annotations

import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

from jobsearch_config.catalog import provider
from jobsearch_config.registry import Registry, load_registry
from jobsearch_config.schema import AppConfig, SiteConfig
from jobsearch_config.store import load_config, resolve_options, save_config

from . import robots
from .http import FetchError, fetch_bytes

META_LAST = "last_compliance_scan"
META_SUMMARY = "last_compliance_summary"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


@dataclass
class SiteCompliance:
    site_id: str
    name: str
    url: str
    host: str = ""
    compliant: bool | None = None  # None = could not be determined (network error)
    reason: str = ""  # terms | robots | http | error | ""
    message: str = ""
    status_code: int = 0
    was_enabled: bool = False
    disabled: bool = False  # disabled by this scan
    checked_at: str = field(default_factory=_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ComplianceReport:
    checked_at: str = field(default_factory=_now)
    results: list[SiteCompliance] = field(default_factory=list)
    config_saved: bool = False

    @property
    def non_compliant(self) -> list[SiteCompliance]:
        return [r for r in self.results if r.compliant is False]

    @property
    def disabled(self) -> list[SiteCompliance]:
        return [r for r in self.results if r.disabled]

    @property
    def undetermined(self) -> list[SiteCompliance]:
        return [r for r in self.results if r.compliant is None]

    def summary(self) -> str:
        ok = sum(1 for r in self.results if r.compliant)
        text = f"{len(self.results)} site(s) checked: {ok} compliant, {len(self.non_compliant)} non-compliant"
        if self.disabled:
            text += f" ({len(self.disabled)} disabled: {', '.join(r.name for r in self.disabled)})"
        if self.undetermined:
            text += f", {len(self.undetermined)} could not be reached"
        return text

    def to_dict(self) -> dict[str, Any]:
        return {"checked_at": self.checked_at, "summary": self.summary(), "config_saved": self.config_saved, "results": [r.to_dict() for r in self.results]}


def site_url(site: SiteConfig) -> str:
    """URL that identifies the site's host ("" for built-in API providers, which are not subject to the scan)."""
    spec = provider(site.provider)
    if spec is None:
        return ""
    if spec.custom:
        return str(site.options.get("url") or "")
    if spec.platform:
        from .ats import site_url as ats_url

        try:
            return ats_url(site.provider, resolve_options(site.options))
        except (ValueError, KeyError):
            return ""
    return ""


def check_site(site: SiteConfig, config: AppConfig, registry: Registry) -> SiteCompliance:
    """Check one site against the access policy. Updates the registry; does not touch the configuration."""
    url = site_url(site)
    result = SiteCompliance(site_id=site.id, name=site.name, url=url, host=urlsplit(url).netloc.lower(), was_enabled=site.enabled)
    if not url:
        result.compliant, result.message = True, "built-in API provider — not subject to the scan"
        return result
    probe_url = url.replace("{keyword}", "analyst").replace("{location}", "").replace("{limit}", "10").replace("{page}", "1")
    row = registry.lookup(url)
    if row is not None and row.policy_block:
        result.compliant, result.reason, result.message = False, "terms", f"{row.host} prohibits automated access by its terms of use — {row.message}"
        registry.record(url, "forbidden", row.message, source="scan", reason="terms", save=False)
        return result
    verdict = robots.check(probe_url, config.search)
    if not verdict.allowed and not verdict.unreachable:
        result.compliant, result.reason, result.message = False, "robots", verdict.reason
        registry.record(url, "forbidden", verdict.reason, source="scan", reason="robots", save=False)
        return result
    if verdict.unreachable:
        result.compliant, result.reason, result.message = None, "error", verdict.reason
        registry.record(url, "error", verdict.reason, source="scan", save=False)
        return result
    try:
        fetch_bytes(probe_url, timeout=config.search.timeout_seconds, user_agent=config.search.user_agent)
    except FetchError as exc:
        result.status_code = exc.status
        if exc.status in (401, 403, 429):
            result.compliant, result.reason = False, "http"
            result.message = f"the site refused automated access (HTTP {exc.status})"
            registry.record(url, "forbidden", result.message, source="scan", status_code=exc.status, reason="http", save=False)
        else:
            result.compliant, result.reason, result.message = None, "error", str(exc)
            registry.record(url, "error", str(exc), source="scan", status_code=exc.status, save=False)
        return result
    result.compliant, result.message = True, "robots.txt allows the URL and the host answers it"
    registry.record(url, "ok", "Compliance scan: reachable and allowed.", source="scan", status_code=200, save=False)
    return result


def scan(config: AppConfig, registry: Registry | None = None, disable: bool = True, save: bool = True) -> ComplianceReport:
    """Check every custom / platform site; disable the non-compliant ones (``disable``) and persist (``save``)."""
    registry = registry if registry is not None else load_registry()
    report = ComplianceReport()
    changed = False
    for site in config.sites:
        if not site_url(site):
            continue
        result = check_site(site, config, registry)
        if result.compliant is False and disable and site.enabled:
            site.enabled = False
            stamp = report.checked_at[:16].replace("T", " ")
            site.notes = (f"[compliance {stamp}] disabled — {result.message}" + (f" | {site.notes}" if site.notes else ""))[:600]
            result.disabled = True
            changed = True
        report.results.append(result)
    registry.meta[META_LAST] = report.checked_at
    registry.meta[META_SUMMARY] = report.summary()
    if save:
        registry.save()
        if changed:
            save_config(config)
            report.config_saved = True
    return report


def last_scan(registry: Registry | None = None) -> tuple[str, str]:
    """(timestamp, summary) of the last scan recorded in the registry ("" when never)."""
    registry = registry if registry is not None else load_registry()
    return str(registry.meta.get(META_LAST) or ""), str(registry.meta.get(META_SUMMARY) or "")


def due(config: AppConfig, registry: Registry | None = None) -> bool:
    hours = int(config.search.compliance_scan_hours or 0)
    if hours <= 0:
        return False
    stamp, _ = last_scan(registry)
    if not stamp:
        return True
    try:
        return datetime.now() - datetime.fromisoformat(stamp) >= timedelta(hours=hours)
    except ValueError:
        return True


_background_lock = threading.Lock()
_background_started = False


def run_if_due(background: bool = True) -> bool:
    """Run the daily scan when it is due. Returns True when a scan was started/run.

    Called by the main app on every interaction; cheap when nothing is due.
    With ``background=True`` the scan runs in a daemon thread (once per process)
    so the UI never waits for the network.
    """
    global _background_started
    try:
        config = load_config()
        registry = load_registry()
    except (OSError, ValueError):
        return False
    if not due(config, registry):
        return False
    if not background:
        scan(config, registry)
        return True
    with _background_lock:
        if _background_started:
            return False
        _background_started = True

    def worker() -> None:
        global _background_started
        try:
            scan(load_config(), load_registry())
        except Exception:  # noqa: BLE001 - never let a background scan crash the app
            pass
        finally:
            with _background_lock:
                _background_started = False

    threading.Thread(target=worker, name="compliance-scan", daemon=True).start()
    return True
