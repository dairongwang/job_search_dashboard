"""Site registry: what the app has learned about each job-site host.

One row per host, persisted as JSON next to the configuration file
(``site_registry.json``; override with ``JOB_SEARCH_REGISTRY``). Rows are
created from the built-in seed list and then **updated on every check** —
"Test this site now" in the configuration dashboard, the URL check when a
custom site is created, and every search run by the main app.

Fields per row:

* ``host``        — lowercased host without ``www.`` (seed rows use the registrable domain and match sub-hosts)
* ``status``      — ``ok`` | ``forbidden`` | ``empty`` | ``error``
* ``active``      — False when the site forbids automated access (HTTP 401/403, robots.txt
                    disallow, known terms); such hosts cannot be added or enabled
* ``reason``      — why it is inactive: ``terms`` (the site's terms of use prohibit robots /
                    scrapers — a *policy* block that no successful fetch can lift; only an
                    administrator override can), ``http`` (401/403/429), ``robots`` (robots.txt)
* ``message``     — the warning / explanation shown to the user
* ``source``      — ``builtin`` | ``probe`` | ``search`` | ``manual``
* ``created_at`` / ``updated_at`` — ISO timestamps
* ``checks``      — how many times the host has been checked
* ``last_url`` / ``last_status_code``
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlsplit

from .store import config_path

ENV_REGISTRY_VAR = "JOB_SEARCH_REGISTRY"
REGISTRY_FILENAME = "site_registry.json"

STATUSES = ("ok", "forbidden", "empty", "error")
REASONS = ("", "terms", "http", "robots")
POLICY_REASONS = ("terms",)  # blocks that are the site's stated policy, not a technical answer: sticky until an administrator overrides

# Seed knowledge. Every entry can be re-checked and is overwritten by live results.
SEED_SITES: dict[str, str] = {
    "indeed.com": "Indeed publishes no feed or public API, its terms prohibit automated access, and its servers answer scripts "
    "with HTTP 403 (robots.txt also disallows job pages such as /viewjob). This app will not work around that. "
    "Adzuna carries much of the same inventory — enable the Adzuna site (free API key).",
    "monster.com": "Monster publishes no feed or public API, its terms prohibit automated access, and its servers answer scripts "
    "with HTTP 403; search results are rendered by JavaScript. Try Adzuna, The Muse or USAJOBS instead.",
    "craigslist.org": "Craigslist's terms prohibit robots and scrapers, its RSS feeds were retired, and search results are rendered by "
    "JavaScript, so a fetched page contains no listings.",
    "linkedin.com": "LinkedIn Jobs has no public feed or API, prohibits automated access, and requires a login.",
    "glassdoor.com": "Glassdoor has no public feed or API and blocks automated requests.",
    "ziprecruiter.com": "ZipRecruiter's API is partner-only; there is no public feed.",
    "dice.com": "Dice has no public feed; its site blocks automated requests.",
    "simplyhired.com": "SimplyHired has no public feed or API.",
    "careerbuilder.com": "CareerBuilder's API is partner-only; there is no public feed.",
}


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def host_of(url_or_host: str) -> str:
    text = (url_or_host or "").strip().lower()
    host = urlsplit(text).netloc if "://" in text else text.split("/", 1)[0]
    host = host.split("@")[-1].split(":")[0]
    return host[4:] if host.startswith("www.") else host


@dataclass
class SiteRecord:
    host: str
    status: str = "ok"
    active: bool = True
    message: str = ""
    source: str = "probe"
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    checks: int = 0
    last_url: str = ""
    last_status_code: int = 0
    reason: str = ""  # terms | http | robots | "" (see module docstring)
    last_scan: str = ""  # last compliance scan of this host (ISO timestamp)

    @property
    def forbidden(self) -> bool:
        return not self.active

    @property
    def policy_block(self) -> bool:
        """The site's terms prohibit automated access: cannot be lifted by a live check."""
        return not self.active and self.reason in POLICY_REASONS

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SiteRecord":
        known = {f for f in cls.__dataclass_fields__}
        row = cls(**{k: v for k, v in data.items() if k in known})
        row.host = host_of(row.host)
        row.status = row.status if row.status in STATUSES else "error"
        row.active = bool(row.active)
        row.checks = int(row.checks or 0)
        row.reason = row.reason if row.reason in REASONS else ""
        if row.source == "builtin" and not row.active and not row.reason:
            row.reason = "terms"  # registries written before the reason field: the seed list is terms-based
        return row


def registry_path(path: str | os.PathLike[str] | None = None) -> Path:
    if path:
        return Path(path).expanduser().resolve()
    env = os.environ.get(ENV_REGISTRY_VAR)
    if env:
        return Path(env).expanduser().resolve()
    return config_path().with_name(REGISTRY_FILENAME)


class Registry:
    """In-memory view of the registry file with upsert/lookup helpers."""

    def __init__(self, path: Path, rows: Iterable[SiteRecord] = (), meta: dict[str, Any] | None = None):
        self.path = path
        self.rows: dict[str, SiteRecord] = {row.host: row for row in rows}
        self.meta: dict[str, Any] = dict(meta or {})  # e.g. last_compliance_scan, last_compliance_summary
        self._lock = threading.Lock()

    # -- persistence ---------------------------------------------------------

    @classmethod
    def load(cls, path: str | os.PathLike[str] | None = None) -> "Registry":
        target = registry_path(path)
        rows: list[SiteRecord] = []
        meta: dict[str, Any] = {}
        if target.is_file():
            with target.open("r", encoding="utf-8") as handle:
                raw = json.load(handle)
            for item in (raw.get("sites") if isinstance(raw, dict) else raw) or []:
                if isinstance(item, dict) and item.get("host"):
                    rows.append(SiteRecord.from_dict(item))
            if isinstance(raw, dict) and isinstance(raw.get("meta"), dict):
                meta = raw["meta"]
        registry = cls(target, rows, meta)
        if not target.is_file():
            registry.seed()
            registry.save()
        elif registry.repair_seeds():
            registry.save()
        return registry

    def repair_seeds(self) -> int:
        """Restore seeded terms-based blocks that a live check once flipped active (only a manual override may lift them)."""
        repaired = 0
        for host, message in SEED_SITES.items():
            row = self.rows.get(host)
            if row is not None and row.active and row.source != "manual":
                row.active, row.status, row.reason, row.message = False, "forbidden", "terms", message
                row.updated_at = _now()
                repaired += 1
        return repaired

    def save(self) -> Path:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            payload = {"version": 1, "updated_at": _now(), "meta": dict(self.meta), "sites": [row.to_dict() for row in sorted(self.rows.values(), key=lambda r: r.host)]}
            fd, tmp = tempfile.mkstemp(prefix=".tmp-registry-", suffix=".json", dir=self.path.parent)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(payload, handle, indent=2, ensure_ascii=False)
                    handle.write("\n")
                os.replace(tmp, self.path)
            finally:
                if os.path.exists(tmp):
                    os.unlink(tmp)
        return self.path

    def seed(self) -> int:
        """Add built-in rows that are missing (done when the file is first created, and on demand). Returns how many were added."""
        added = 0
        for host, message in SEED_SITES.items():
            if host not in self.rows:
                self.rows[host] = SiteRecord(host=host, status="forbidden", active=False, message=message, source="builtin", reason="terms")
                added += 1
        return added

    # -- queries ---------------------------------------------------------------

    def lookup(self, url_or_host: str) -> SiteRecord | None:
        host = host_of(url_or_host)
        if not host:
            return None
        if host in self.rows:
            return self.rows[host]
        best: SiteRecord | None = None
        for key, row in self.rows.items():
            if host.endswith("." + key) and (best is None or len(key) > len(best.host)):
                best = row
        return best

    def forbidden(self, url_or_host: str) -> SiteRecord | None:
        row = self.lookup(url_or_host)
        return row if row is not None and not row.active else None

    def guidance(self, url_or_host: str) -> str:
        row = self.lookup(url_or_host)
        return row.message if row is not None and not row.active else ""

    def list(self) -> list[SiteRecord]:
        return sorted(self.rows.values(), key=lambda r: (r.active, r.host))

    # -- updates ---------------------------------------------------------------

    def record(
        self, url: str, status: str, message: str, source: str = "probe", status_code: int = 0, save: bool = True, reason: str = ""
    ) -> SiteRecord:
        """Upsert the row for ``url``'s host from a live check.

        ``status``: ok | forbidden | empty | error. ``forbidden`` clears the active
        flag (``reason`` says why: http | robots | terms); ``ok``/``empty`` set it —
        **unless the row is a policy block** (``reason == "terms"``): a page that
        happens to load does not change what the site's terms say, so such rows
        keep ``active = False`` and their message; only ``set_active`` (an
        administrator override) lifts them. ``error`` leaves the flag unchanged.
        """
        host = host_of(url)
        if status not in STATUSES:
            status = "error"
        row = self.lookup(url)  # a seed row for the registrable domain also covers its sub-hosts
        if row is None or row.host != host and not row.policy_block:
            row = self.rows.get(host)
        if row is None:
            row = SiteRecord(host=host, source=source)
            self.rows[host] = row
        row.updated_at = _now()
        row.checks += 1
        row.last_url = url
        row.last_status_code = int(status_code or 0)
        if row.policy_block:
            # sticky: note the check, keep the verdict and the explanation
            row.status = "forbidden"
            row.source = source if source != "builtin" else row.source
            if save:
                self.save()
            return row
        row.status = status
        row.message = message
        row.source = source
        if status == "forbidden":
            row.active = False
            row.reason = reason if reason in REASONS and reason else (row.reason or "http")
        elif status in ("ok", "empty"):
            row.active = True
            row.reason = ""
        if save:
            self.save()
        return row

    def set_active(self, host: str, active: bool, message: str = "", save: bool = True, reason: str = "") -> SiteRecord | None:
        """Administrator override: activate a host, or block it (``reason`` = terms | http | robots)."""
        row = self.rows.get(host_of(host))
        if row is None:
            if active:
                return None
            row = SiteRecord(host=host_of(host), source="manual")
            self.rows[row.host] = row
        row.active = active
        row.status = "ok" if active else "forbidden"
        row.reason = "" if active else (reason if reason in REASONS and reason else "terms")
        row.source = "manual"
        row.updated_at = _now()
        if message:
            row.message = message
        if save:
            self.save()
        return row

    def remove(self, host: str, save: bool = True) -> bool:
        removed = self.rows.pop(host_of(host), None) is not None
        if removed and save:
            self.save()
        return removed


def load_registry(path: str | os.PathLike[str] | None = None) -> Registry:
    return Registry.load(path)


def block_reason(message: str, status_code: int = 0) -> str:
    """Guess the registry ``reason`` of a refusal from its explanation."""
    text = (message or "").lower()
    if "robots.txt" in text:
        return "robots"
    if status_code in (401, 403, 429) or "http 40" in text or "http 429" in text or "refused" in text:
        return "http"
    if "terms" in text or "prohibit" in text:
        return "terms"
    return "http"


def classify_outcome(error: str, denied: bool, empty: bool) -> tuple[str, str]:
    """Map a site outcome to (status, message) for the registry."""
    if denied:
        return "forbidden", error
    if error:
        return "error", error
    if empty:
        return "empty", "Reachable, but no job listings were found on the last check."
    return "ok", "Reachable; listings were returned on the last check."
