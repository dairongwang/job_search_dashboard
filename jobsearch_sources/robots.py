"""robots.txt compliance for the web-page provider (RFC 9309 matching).

The standard library's ``urllib.robotparser`` treats ``*`` and ``$`` literally,
which mis-reads rules such as ``Disallow: /*rt=nc`` that large job boards
use. This small parser implements the RFC rules: group selection by
user-agent product token, longest-match precedence, ``*`` wildcards and the
``$`` end anchor. Results are cached per host for an hour.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from jobsearch_config.schema import SearchSettings

from .http import FetchError, fetch_text

CACHE_SECONDS = 3600
_cache: dict[str, tuple[float, "RobotsRules"]] = {}


@dataclass
class Rule:
    allow: bool
    pattern: str
    regex: re.Pattern


@dataclass
class RobotsRules:
    groups: dict[str, list[Rule]] = field(default_factory=dict)  # agent token (lower) -> rules
    delays: dict[str, float] = field(default_factory=dict)
    status: str = "ok"  # ok | missing | unreachable
    allow_all: bool = False
    disallow_all: bool = False

    def rules_for(self, token: str) -> list[Rule]:
        token = token.lower()
        for agent, rules in self.groups.items():
            if agent != "*" and agent in token:
                return rules
        return self.groups.get("*", [])

    def can_fetch(self, token: str, url: str) -> bool:
        if self.allow_all:
            return True
        if self.disallow_all:
            return False
        parts = urlsplit(url)
        path = parts.path or "/"
        if parts.query:
            path += "?" + parts.query
        best: Rule | None = None
        for rule in self.rules_for(token):
            if rule.regex.match(path):
                if best is None or len(rule.pattern) > len(best.pattern) or (len(rule.pattern) == len(best.pattern) and rule.allow):
                    best = rule
        return True if best is None else best.allow

    def crawl_delay(self, token: str) -> float | None:
        token = token.lower()
        for agent, delay in self.delays.items():
            if agent != "*" and agent in token:
                return delay
        return self.delays.get("*")


def _compile(pattern: str) -> re.Pattern:
    anchored = pattern.endswith("$")
    if anchored:
        pattern = pattern[:-1]
    regex = "".join(".*" if ch == "*" else re.escape(ch) for ch in pattern)
    return re.compile("^" + regex + ("$" if anchored else ""))


def parse(text: str) -> RobotsRules:
    rules = RobotsRules()
    current_agents: list[str] = []
    seen_rule_since_agent = False
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, value = (part.strip() for part in line.split(":", 1))
        key = key.lower()
        if key == "user-agent":
            if seen_rule_since_agent:
                current_agents = []
                seen_rule_since_agent = False
            current_agents.append(value.lower())
            for agent in current_agents:
                rules.groups.setdefault(agent, [])
        elif key in ("allow", "disallow"):
            seen_rule_since_agent = True
            if not current_agents:
                continue
            if value == "" and key == "disallow":
                continue  # "Disallow:" (empty) means allow everything
            if value == "":
                continue
            for agent in current_agents:
                rules.groups[agent].append(Rule(allow=key == "allow", pattern=value, regex=_compile(value)))
        elif key == "crawl-delay":
            seen_rule_since_agent = True
            try:
                for agent in current_agents:
                    rules.delays[agent] = float(value)
            except ValueError:
                pass
    return rules


def product_token(user_agent: str) -> str:
    """'Mozilla/5.0 (compatible; JobSearchDashboard/2.0; ...)' -> 'JobSearchDashboard'."""
    tokens = re.findall(r"([A-Za-z][A-Za-z0-9_-]*)/\d", user_agent)
    for token in tokens:
        if token.lower() != "mozilla":
            return token
    return tokens[0] if tokens else (user_agent.split()[0] if user_agent else "*")


def load(url: str, settings: SearchSettings | None = None) -> RobotsRules:
    settings = settings or SearchSettings()
    parts = urlsplit(url)
    host = f"{parts.scheme}://{parts.netloc}"
    cached = _cache.get(host)
    now = time.time()
    if cached and now - cached[0] < CACHE_SECONDS:
        return cached[1]
    try:
        text = fetch_text(f"{host}/robots.txt", timeout=settings.timeout_seconds, user_agent=settings.user_agent)
        rules = parse(text)
    except FetchError as exc:
        rules = RobotsRules()
        if exc.status and 400 <= exc.status < 500:
            rules.status, rules.allow_all = "missing", True  # RFC 9309 2.3.1.3: unavailable -> may crawl
        else:
            rules.status, rules.disallow_all = "unreachable", True  # RFC 9309 2.3.1.4: unreachable -> must not crawl
    _cache[host] = (now, rules)
    return rules


def clear_cache() -> None:
    _cache.clear()


@dataclass
class Verdict:
    allowed: bool
    reason: str = ""
    crawl_delay: float | None = None
    unreachable: bool = False  # robots.txt could not be fetched (network/server error): blocked for now, not a site decision


def check(url: str, settings: SearchSettings | None = None) -> Verdict:
    """Is ``url`` fetchable by this app according to the site's robots.txt?"""
    settings = settings or SearchSettings()
    rules = load(url, settings)
    token = product_token(settings.user_agent)
    host = urlsplit(url).netloc
    if rules.status == "unreachable":
        return Verdict(False, f"{host}/robots.txt could not be fetched (network or server error); crawling is not permitted until it is reachable.", unreachable=True)
    if rules.can_fetch(token, url):
        return Verdict(True, "", rules.crawl_delay(token))
    return Verdict(False, f"{host}/robots.txt disallows {urlsplit(url).path or '/'} for crawlers; this app honours robots.txt.", rules.crawl_delay(token))
