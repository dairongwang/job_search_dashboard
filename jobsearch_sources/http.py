"""Tiny HTTP helper (stdlib only) with a swappable transport for tests."""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable

Fetcher = Callable[..., bytes]  # (url, headers, timeout, data=None) -> bytes


class FetchError(RuntimeError):
    """Raised when a provider request fails (network, HTTP status, bad payload).

    ``status`` holds the HTTP status code when the server answered (0 otherwise).
    """

    def __init__(self, message: str, status: int = 0, url: str = ""):
        super().__init__(message)
        self.status = status
        self.url = url


def _default_fetch(url: str, headers: dict[str, str], timeout: int, data: bytes | None = None) -> bytes:
    request = urllib.request.Request(url, headers=headers, data=data, method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        raise FetchError(f"HTTP {exc.code} from {urllib.parse.urlsplit(url).netloc}", status=exc.code, url=url) from exc
    except urllib.error.URLError as exc:
        raise FetchError(f"Cannot reach {urllib.parse.urlsplit(url).netloc} ({exc.reason})", url=url) from exc
    except TimeoutError as exc:
        raise FetchError(f"Timed out talking to {urllib.parse.urlsplit(url).netloc}", url=url) from exc


_fetcher: Fetcher = _default_fetch


def set_fetcher(fetcher: Fetcher | None) -> None:
    """Override the transport (tests / offline fixtures). ``None`` restores the default."""
    global _fetcher
    _fetcher = fetcher or _default_fetch


def fetch_bytes(
    url: str, *, headers: dict[str, str] | None = None, timeout: int = 15, user_agent: str = "", data: bytes | None = None
) -> bytes:
    """GET ``url`` (or POST when ``data`` is given) and return the raw body."""
    merged = {
        "User-Agent": user_agent or "Mozilla/5.0 (compatible; JobSearchDashboard/2.0; personal job tracker)",
        "Accept": "application/json, application/xml, text/xml, text/html;q=0.9, */*;q=0.8",
        "Accept-Language": "en-US,en;q=0.8",
    }
    merged.update(headers or {})
    if data is None:
        return _fetcher(url, merged, timeout)
    try:
        return _fetcher(url, merged, timeout, data)
    except TypeError:  # a test transport that only knows GET
        return _fetcher(url, merged, timeout)


def fetch_json(
    url: str, *, headers: dict[str, str] | None = None, timeout: int = 15, user_agent: str = "", data: bytes | None = None
) -> Any:
    raw = fetch_bytes(url, headers=headers, timeout=timeout, user_agent=user_agent, data=data)
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        kind = classify_body(raw)
        hint = " (it returned a web page, not JSON)" if kind == "html" else ""
        raise FetchError(f"Response from {urllib.parse.urlsplit(url).netloc} was not valid JSON{hint}", url=url) from exc


def classify_body(raw: bytes | str) -> str:
    """Rough content sniffing: 'feed' (RSS/Atom XML), 'html', 'json' or 'unknown'."""
    head = (raw[:4000].decode("utf-8", errors="ignore") if isinstance(raw, bytes) else raw[:4000]).lstrip().lower()
    if head.startswith("<!doctype html") or "<html" in head[:300]:
        return "html"
    if head.startswith(("{", "[")):
        return "json"
    if head.startswith("<?xml") or "<rss" in head or "<feed" in head or "<rdf:rdf" in head:
        if "<rss" in head or "<feed" in head or "<rdf:rdf" in head or "<channel" in head:
            return "feed"
        return "xml"
    if "<html" in head or "<body" in head:
        return "html"
    return "unknown"


def post_json(url: str, payload: Any, *, headers: dict[str, str] | None = None, timeout: int = 15, user_agent: str = "") -> Any:
    """POST a JSON body and parse the JSON response."""
    merged = {"Content-Type": "application/json", "Accept": "application/json"}
    merged.update(headers or {})
    return fetch_json(url, headers=merged, timeout=timeout, user_agent=user_agent, data=json.dumps(payload).encode("utf-8"))


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
