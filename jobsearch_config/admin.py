"""Administrator-controlled settings.

Web-page based search (reading HTML pages, driving search forms in a headless
browser) is the part of the app that touches third-party sites most. Whether
it is allowed at all is therefore an **administrator** decision, not a
per-user preference:

* the switch lives in the configuration (``search.web_page_search``) so every
  dashboard and the CLI see it,
* changing it requires the administrator token — the ``JOB_SEARCH_ADMIN_TOKEN``
  environment variable of the process (put it in ``.env`` / the secret store
  of the machine that runs the configuration dashboard; the main app does not
  need it),
* the stored value is signed (HMAC-SHA256 over the value with the token). A
  value edited by hand without the token fails verification and is treated as
  **off** (fail-safe) wherever the token is available to verify it.

``web_page_search_allowed(config)`` is the single place the rest of the app
asks; ``set_web_page_search(config, enabled, token)`` is the only writer.
"""

from __future__ import annotations

import hashlib
import hmac
import os
from datetime import datetime

from .schema import AppConfig

ENV_ADMIN_TOKEN = "JOB_SEARCH_ADMIN_TOKEN"
_SETTING = "web_page_search"


class AdminRequired(PermissionError):
    """The administrator token is missing or wrong."""


def admin_token() -> str:
    return os.environ.get(ENV_ADMIN_TOKEN, "").strip()


def admin_configured() -> bool:
    return bool(admin_token())


def _signature(enabled: bool, changed_at: str, token: str) -> str:
    message = f"{_SETTING}={'on' if enabled else 'off'}@{changed_at}".encode("utf-8")
    return hmac.new(token.encode("utf-8"), message, hashlib.sha256).hexdigest()


def verify_token(token: str) -> bool:
    expected = admin_token()
    return bool(expected) and hmac.compare_digest(expected, (token or "").strip())


def signature_valid(config: AppConfig, token: str | None = None) -> bool | None:
    """True/False when the stored switch can be verified; None when no administrator token is available to check."""
    settings = config.search
    token = admin_token() if token is None else token
    if not settings.web_page_search_signature:
        return None  # never touched by an administrator: the default applies
    if not token:
        return None
    return hmac.compare_digest(settings.web_page_search_signature, _signature(settings.web_page_search, settings.web_page_search_changed_at, token))


def web_page_search_allowed(config: AppConfig) -> tuple[bool, str]:
    """Is web-page based search allowed right now? Returns (allowed, explanation)."""
    settings = config.search
    valid = signature_valid(config)
    if not settings.web_page_search:
        when = f" since {settings.web_page_search_changed_at}" if settings.web_page_search_changed_at else ""
        return False, f"web-page search is switched off by the administrator{when}."
    if valid is False:
        return False, "web-page search is switched OFF: the stored setting does not verify against the administrator token (it was changed without the token)."
    if valid is None and settings.web_page_search_signature:
        return True, "web-page search is on (signed by the administrator; not verifiable in this process because JOB_SEARCH_ADMIN_TOKEN is not set)."
    if valid is None and not admin_configured():
        return True, "web-page search is on (default; no administrator token configured yet — set JOB_SEARCH_ADMIN_TOKEN to lock the setting)."
    if valid is None:
        return True, "web-page search is on (default; the administrator has not changed it)."
    return True, f"web-page search is on (set by the administrator {settings.web_page_search_changed_at})."


def set_web_page_search(config: AppConfig, enabled: bool, token: str) -> AppConfig:
    """Switch web-page search on/off. Requires the administrator token; signs the new state. Does not save."""
    if not admin_configured():
        raise AdminRequired(f"no administrator token is configured: set {ENV_ADMIN_TOKEN} in the environment of the configuration dashboard / CLI.")
    if not verify_token(token):
        raise AdminRequired("the administrator token is wrong.")
    settings = config.search
    settings.web_page_search = bool(enabled)
    settings.web_page_search_changed_at = datetime.now().isoformat(timespec="seconds")
    settings.web_page_search_signature = _signature(settings.web_page_search, settings.web_page_search_changed_at, admin_token())
    return config
