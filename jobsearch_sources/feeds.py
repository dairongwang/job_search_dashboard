"""Feed probing, auto-discovery and guidance for sites that cannot be searched.

Used by the RSS adapter (to follow ``<link rel="alternate">`` from a page to
its feed) and by the configuration dashboard (to check a URL before saving it).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html import unescape
from urllib.parse import urljoin, urlsplit

from jobsearch_config.registry import SEED_SITES, load_registry
from jobsearch_config.schema import SearchSettings

from .http import FetchError, classify_body, fetch_bytes

# Seed knowledge lives in jobsearch_config.registry (SEED_SITES); kept under the old name for imports.
KNOWN_NO_FEED: dict[str, str] = SEED_SITES


class AccessDenied(ValueError):
    """The site forbids automated access (HTTP 401/403, robots.txt disallow, or a registry entry).

    ``transient`` marks a block that is not the site's decision (robots.txt
    unreachable); it stops the run but is recorded as an error, not as forbidden.
    """

    def __init__(self, message: str, status_code: int = 0, transient: bool = False):
        super().__init__(message)
        self.status_code = status_code
        self.transient = transient


class NoListings(ValueError):
    """The site was reachable but no job listings could be extracted."""


_LINK_TAG = re.compile(r"<link\b[^>]*>", re.IGNORECASE)
_ATTR = re.compile(r"""([a-zA-Z:-]+)\s*=\s*("([^"]*)"|'([^']*)'|([^\s"'>]+))""")
_ANCHOR = re.compile(r"""<a\b[^>]*href\s*=\s*["']([^"']+)["']""", re.IGNORECASE)
_FEED_TYPES = ("application/rss+xml", "application/atom+xml", "application/rdf+xml", "application/feed+json")


def known_site_guidance(url: str) -> str:
    """Warning for hosts the registry marks as forbidding automated access ("" otherwise)."""
    try:
        return load_registry().guidance(url)
    except (OSError, ValueError):
        host = urlsplit(url).netloc.lower()
        for fragment, text in SEED_SITES.items():
            if host == fragment or host.endswith("." + fragment):
                return text
        return ""


def _attrs(tag: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for match in _ATTR.finditer(tag):
        out[match.group(1).lower()] = unescape(match.group(3) or match.group(4) or match.group(5) or "")
    return out


def discover_feeds(html: str, base_url: str) -> list[str]:
    """Return feed URLs advertised by an HTML page (``<link rel="alternate" type="application/rss+xml">``).

    Falls back to anchors whose href looks like a feed (``.rss``, ``/feed``, ``format=rss``…).
    """
    found: list[str] = []
    for tag in _LINK_TAG.findall(html):
        attrs = _attrs(tag)
        rel = attrs.get("rel", "").lower()
        kind = attrs.get("type", "").lower()
        href = attrs.get("href", "")
        if href and "alternate" in rel and any(kind.startswith(t) for t in _FEED_TYPES):
            found.append(urljoin(base_url, href))
    if not found:
        for href in _ANCHOR.findall(html):
            lowered = href.lower()
            if re.search(r"(\.rss$|\.atom$|/feed/?$|/rss/?$|/atom/?$|[?&]format=(rss|atom)\b|feed\.xml$|rss\.xml$|atom\.xml$)", lowered):
                found.append(urljoin(base_url, unescape(href)))
    return list(dict.fromkeys(found))


@dataclass
class ProbeResult:
    status: str  # "feed" | "json" | "html" | "blocked" | "robots" | "error" | "unknown"
    message: str
    url: str
    feeds: list[str] = field(default_factory=list)  # discovered feed links when status == "html"
    items: int = 0
    expect: str = "feed"

    @property
    def ok(self) -> bool:
        if self.expect == "html":
            return self.status == "html"
        return self.status in ("feed", "json")

    @property
    def registry_status(self) -> str:
        """Map to a registry status: forbidden | ok | empty | error."""
        if self.status in ("blocked", "robots"):
            return "forbidden"
        if self.status == "error":
            return "error"
        if self.expect == "html" and self.status == "html" and self.items == 0:
            return "empty"
        if self.ok or self.status in ("feed", "json", "html"):
            return "ok"
        return "error"


def explain_fetch_error(exc: FetchError, url: str = "") -> str:
    """Turn an HTTP failure into actionable text."""
    target = url or exc.url
    guidance = known_site_guidance(target)
    if exc.status in (401, 403):
        base = f"the site refused automated access (HTTP {exc.status})"
        if guidance:
            return f"{base}. {guidance}"
        return (
            f"{base}. This URL is probably a web page rather than a feed/API, or the site blocks scripts. "
            "Use the site's RSS/Atom feed URL or a documented API endpoint."
        )
    if exc.status == 404:
        return "the URL was not found (HTTP 404). Check the feed/API address." + (f" {guidance}" if guidance else "")
    if exc.status == 429:
        return "the site is rate-limiting requests (HTTP 429). Lower 'max results' or wait before searching again."
    return str(exc) + (f". {guidance}" if guidance else "")


def probe(
    url: str,
    settings: SearchSettings | None = None,
    headers: dict[str, str] | None = None,
    expect: str = "feed",
    record: bool = True,
) -> ProbeResult:
    """Fetch ``url`` once and say what it is. ``expect`` is "feed", "json" or "html".

    The outcome is written to the site registry unless ``record`` is False.
    """
    try:
        blocked = load_registry().forbidden(url)
    except (OSError, ValueError):
        blocked = None
    if blocked is not None and blocked.policy_block:
        # the site's terms prohibit robots/scrapers: do not even fetch; the block is lifted only by an administrator
        result = ProbeResult("blocked", f"{blocked.host} prohibits automated access by its terms of use — {blocked.message}", url, expect=expect)
        if record:
            try:
                load_registry().record(url, "forbidden", blocked.message, source="probe", reason="terms")
            except (OSError, ValueError):
                pass
        return result
    result = _probe(url, settings, headers, expect)
    if record:
        try:
            status_code = 0
            if result.status == "blocked":
                match = re.search(r"HTTP (\d{3})", result.message)
                status_code = int(match.group(1)) if match else 403
            reason = "robots" if result.status == "robots" else ("http" if result.status == "blocked" else "")
            load_registry().record(url, result.registry_status, result.message, source="probe", status_code=status_code, reason=reason)
        except (OSError, ValueError):
            pass
    return result


def _probe(url: str, settings: SearchSettings | None, headers: dict[str, str] | None, expect: str) -> ProbeResult:
    settings = settings or SearchSettings()
    guidance = known_site_guidance(url)
    if expect == "html":
        from . import robots

        verdict = robots.check(url, settings)
        if not verdict.allowed:
            return ProbeResult("error" if verdict.unreachable else "robots", verdict.reason, url, expect=expect)
    try:
        raw = fetch_bytes(url, headers=headers, timeout=settings.timeout_seconds, user_agent=settings.user_agent)
    except FetchError as exc:
        status = "blocked" if exc.status in (401, 403) else "error"
        return ProbeResult(status, explain_fetch_error(exc, url), url, expect=expect)
    kind = classify_body(raw)
    text = raw.decode("utf-8", errors="replace")
    if expect == "html":
        return _probe_page(url, kind, text, guidance)
    if kind == "feed":
        count = len(re.findall(r"<item\b|<entry\b", text, re.IGNORECASE))
        if expect == "json":
            return ProbeResult("feed", "This URL is an RSS/Atom feed — add it as an 'RSS / Atom feed' site instead.", url, items=count)
        return ProbeResult("feed", f"Valid feed with {count} item(s).", url, items=count)
    if kind == "json":
        if expect == "feed":
            return ProbeResult("json", "This URL returns JSON — add it as a 'Generic JSON API' site instead.", url)
        return ProbeResult("json", "JSON response received.", url)
    if kind == "html":
        feeds = discover_feeds(text, url)
        if feeds:
            return ProbeResult("html", f"This URL is a web page, but it advertises a feed: {feeds[0]}", url, feeds=feeds)
        message = "This URL returns a web page (HTML), not an RSS/Atom feed or JSON API."
        if guidance:
            message += " " + guidance
        else:
            message += " Look for an RSS/Atom link on the site, or a documented API, and use that URL."
        return ProbeResult("html", message, url)
    return ProbeResult("unknown", "The response is neither a feed, JSON nor HTML; check the URL.", url)


def _probe_page(url: str, kind: str, text: str, guidance: str) -> ProbeResult:
    if kind == "feed":
        return ProbeResult("feed", "This URL is an RSS/Atom feed — add it as an 'RSS / Atom feed' site instead.", url, expect="html")
    if kind == "json":
        return ProbeResult("json", "This URL returns JSON — add it as a 'Generic JSON API' site instead.", url, expect="html")
    from .htmlpages import candidate_links, extract_jsonld, _soup  # local import: bs4 is optional

    try:
        soup = _soup(text)
    except ValueError as exc:
        return ProbeResult("error", str(exc), url, expect="html")
    postings, listed = extract_jsonld(soup)
    links = listed or candidate_links(soup, url)
    feeds = discover_feeds(text, url)
    parts = []
    if postings:
        parts.append(f"{len(postings)} schema.org JobPosting(s) on the page")
    if links:
        parts.append(f"{len(links)} job-looking link(s) to follow")
    if feeds:
        parts.append(f"an RSS/Atom feed is advertised ({feeds[0]}) — an 'RSS / Atom feed' site would be lighter")
    if parts:
        message = "Page fetched: " + "; ".join(parts) + "."
    else:
        text_len = len(soup.get_text(" ", strip=True))
        script_len = sum(len(s.get_text() or "") for s in soup.find_all("script"))
        if script_len > text_len * 2 and text_len < 3000:
            message = "Page fetched, but it contains no listings and looks JavaScript-rendered; this app does not execute JavaScript."
        else:
            message = "Page fetched, but no JobPosting data or job-looking links were detected. Configure CSS selectors for this site."
        if guidance:
            message += " " + guidance
    return ProbeResult("html", message, url, feeds=feeds, items=len(postings) + len(links), expect="html")
