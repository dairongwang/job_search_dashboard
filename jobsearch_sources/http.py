"""Tiny HTTP helper (stdlib only) with a swappable transport for tests."""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable

Fetcher = Callable[[str, dict[str, str], int], bytes]


class FetchError(RuntimeError):
    """Raised when a provider request fails (network, HTTP status, bad payload)."""


def _default_fetch(url: str, headers: dict[str, str], timeout: int) -> bytes:
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        raise FetchError(f"HTTP {exc.code} from {urllib.parse.urlsplit(url).netloc}") from exc
    except urllib.error.URLError as exc:
        raise FetchError(f"Cannot reach {urllib.parse.urlsplit(url).netloc} ({exc.reason})") from exc
    except TimeoutError as exc:
        raise FetchError(f"Timed out talking to {urllib.parse.urlsplit(url).netloc}") from exc


_fetcher: Fetcher = _default_fetch


def set_fetcher(fetcher: Fetcher | None) -> None:
    """Override the transport (tests / offline fixtures). ``None`` restores the default."""
    global _fetcher
    _fetcher = fetcher or _default_fetch


def fetch_bytes(url: str, *, headers: dict[str, str] | None = None, timeout: int = 15, user_agent: str = "") -> bytes:
    merged = {"User-Agent": user_agent or "JobSearchDashboard/2.0", "Accept": "application/json, application/xml, text/xml, */*"}
    merged.update(headers or {})
    return _fetcher(url, merged, timeout)


def fetch_json(url: str, *, headers: dict[str, str] | None = None, timeout: int = 15, user_agent: str = "") -> Any:
    raw = fetch_bytes(url, headers=headers, timeout=timeout, user_agent=user_agent)
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FetchError(f"Response from {urllib.parse.urlsplit(url).netloc} was not valid JSON") from exc


def fetch_text(url: str, *, headers: dict[str, str] | None = None, timeout: int = 15, user_agent: str = "") -> str:
    raw = fetch_bytes(url, headers=headers, timeout=timeout, user_agent=user_agent)
    return raw.decode("utf-8", errors="replace")


def basic_auth(username: str, password: str = "") -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def build_url(base: str, params: dict[str, Any]) -> str:
    clean = {k: str(v) for k, v in params.items() if v not in (None, "", [], False)}
    if not clean:
        return base
    joiner = "&" if "?" in base else "?"
    return base + joiner + urllib.parse.urlencode(clean)
