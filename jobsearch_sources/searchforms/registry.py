"""Registry of search-form strategies: lookup by site (host), by family and by version.

The registry answers three questions:

* ``for_url(url)`` — which strategies (all versions, newest first) know this host?
* ``candidates(site_options, url, site_id)`` — which strategies should a run try,
  in which order? The configured family/version first, then the other versions
  of that family (newest first), so a changed form falls back gracefully. A
  ``recipe`` spec in the options (or legacy ``actions``) yields a
  ``RecipeStrategy``.
* ``resolve(url, html, candidates)`` — given the live page HTML, which candidate
  matches (fingerprint)? Returns a ``Resolution`` saying whether the form
  changed compared with the configured version.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .base import SearchFormStrategy
from .recipe import RecipeStrategy

_STRATEGIES: dict[str, SearchFormStrategy] = {}


def register(strategy: SearchFormStrategy) -> SearchFormStrategy:
    if not strategy.family or not strategy.version:
        raise ValueError("a strategy needs a family and a version")
    _STRATEGIES[strategy.key] = strategy
    return strategy


def all_strategies() -> list[SearchFormStrategy]:
    return sorted(_STRATEGIES.values(), key=lambda s: (s.family, tuple(-x if isinstance(x, int) else x for x in s.sort_key)))


def families() -> dict[str, list[SearchFormStrategy]]:
    out: dict[str, list[SearchFormStrategy]] = {}
    for strategy in _STRATEGIES.values():
        out.setdefault(strategy.family, []).append(strategy)
    for versions in out.values():
        versions.sort(key=lambda s: s.sort_key, reverse=True)
    return out


def versions_of(family: str) -> list[SearchFormStrategy]:
    return families().get(family, [])


def get(family: str, version: str | None = None) -> SearchFormStrategy | None:
    """The strategy for ``family`` at ``version`` (latest when omitted); ``None`` if unknown."""
    if version not in (None, "", "latest"):
        return _STRATEGIES.get(f"{family}@{version}")
    versions = versions_of(family)
    return versions[0] if versions else None


def for_url(url: str) -> list[SearchFormStrategy]:
    """Every registered strategy whose hosts include the URL's host, newest version first."""
    found = [s for s in _STRATEGIES.values() if s.applies_to(url)]
    found.sort(key=lambda s: (s.family, s.sort_key), reverse=True)
    return found


def candidates(options: dict[str, Any] | None, url: str = "", site_id: str = "") -> list[SearchFormStrategy]:
    """Ordered strategies a run should try for a web-page site (``[]`` = no search form configured).

    ``options["search_form"]`` = ``{"strategy": family, "version": v, ...}`` picks
    a registered family (the configured version first, then the other versions
    newest-first) or ``{"strategy": "recipe", ...}`` for a declarative one.
    Legacy ``actions``/``form_values`` options become a recipe.
    """
    options = options or {}
    spec = options.get("search_form")
    if isinstance(spec, dict) and spec:
        family = str(spec.get("strategy") or "").strip()
        learned = learned_versions(spec, site_id)
        if family in ("", "recipe"):
            own = [RecipeStrategy(spec, site_id)] if (spec.get("steps") or spec.get("actions") or (family and spec.get("fields"))) else []
            versions = own + learned
        elif family == "auto":
            versions = for_url(url) + learned
        else:
            versions = versions_of(family) + learned
        if not versions:
            return []
        wanted = str(spec.get("version") or "")
        preferred = next((v for v in versions if wanted and v.version == wanted), None)
        if preferred is None and family not in ("", "recipe", "auto"):
            preferred = get(family)  # newest registered version
        return ([preferred] if preferred else []) + [v for v in versions if v is not preferred]
    actions = [s for s in (options.get("actions") or []) if isinstance(s, dict)]
    if actions:
        return [RecipeStrategy.from_legacy(actions, options.get("form_values"), site_id)]
    return []


def learned_versions(block: dict[str, Any], site_id: str = "") -> list[RecipeStrategy]:
    """Strategy versions the app learned from the live page and the user saved (``search_form.learned``), newest first."""
    family = str(block.get("strategy") or "").strip()
    out: list[RecipeStrategy] = []
    for spec in block.get("learned") or []:
        if not isinstance(spec, dict) or not spec.get("steps"):
            continue
        merged = dict(spec)
        if family and family not in ("recipe", "auto"):
            merged["family"] = family
        merged.setdefault("learned", True)
        out.append(RecipeStrategy(merged, site_id))
    out.sort(key=lambda s: s.sort_key, reverse=True)
    return out


def next_learned_version(candidates_: list[SearchFormStrategy]) -> str:
    numbers = [int(m.group(1)) for s in candidates_ for m in [re.match(r"^auto-(\d+)$", str(s.version))] if m]
    return f"auto-{max(numbers, default=0) + 1}"


def configured_strategy(options: dict[str, Any] | None, site_id: str = "") -> SearchFormStrategy | None:
    """The strategy the site is configured with (first candidate), or None."""
    found = candidates(options, str((options or {}).get("url") or ""), site_id)
    return found[0] if found else None


@dataclass
class Resolution:
    """Which strategy version matched the live page."""

    strategy: SearchFormStrategy | None
    candidates: list[SearchFormStrategy] = field(default_factory=list)
    configured: SearchFormStrategy | None = None

    @property
    def matched(self) -> bool:
        return self.strategy is not None

    @property
    def changed(self) -> bool:
        """True when the live page matches a different version than the one configured."""
        return self.strategy is not None and self.configured is not None and self.strategy.key != self.configured.key

    @property
    def tried(self) -> tuple[str, ...]:
        return tuple(s.key for s in self.candidates)

    def message(self) -> str:
        if self.strategy is None:
            tried = ", ".join(f"{s.key} ({s.since or 'undated'})" for s in self.candidates) or "none registered"
            return (
                "the site's search form no longer matches any known version — tried: " + tried + ". The form has probably been "
                "redesigned; run Investigate on the page to see its current controls and add a new strategy version (or a recipe)."
            )
        if self.changed:
            return (
                f"the search form changed: configured version {self.configured.version} of {self.configured.family} did not match "
                f"the live page, version {self.strategy.version} ({self.strategy.since or 'undated'}) did and was used instead. "
                "Re-test the site in the configuration dashboard to update its criteria."
            )
        return f"search form matched {self.strategy.key}" + (f" ({self.strategy.since})" if self.strategy.since else "")


def resolve(soup: Any, candidates_: list[SearchFormStrategy]) -> Resolution:
    """Pick the first candidate whose fingerprint matches the (BeautifulSoup) document."""
    configured = candidates_[0] if candidates_ else None
    for strategy in candidates_:
        if strategy.fingerprint() and strategy.matches(soup):
            return Resolution(strategy, list(candidates_), configured)
    # a candidate without a fingerprint (e.g. a legacy recipe) cannot be told apart: assume it applies
    for strategy in candidates_:
        if not strategy.fingerprint():
            return Resolution(strategy, list(candidates_), configured)
    return Resolution(None, list(candidates_), configured)


def resolve_key(matched_key: str, candidates_: list[SearchFormStrategy]) -> Resolution:
    """Build a Resolution from the key the browser reported as matched (``""`` = none)."""
    configured = candidates_[0] if candidates_ else None
    strategy = next((s for s in candidates_ if s.key == matched_key), None) if matched_key else None
    return Resolution(strategy, list(candidates_), configured)


def browser_plan(candidates_: list[SearchFormStrategy], criteria: dict[str, Any], pages: int = 1) -> dict[str, Any]:
    """Payload for the headless browser: every candidate's fingerprint and steps, plus the viewport."""
    plan: dict[str, Any] = {"candidates": []}
    for strategy in candidates_:
        plan["candidates"].append(
            {
                "key": strategy.key,
                "require": strategy.fingerprint(),
                "absent": strategy.absent(),
                "steps": strategy.steps(criteria, pages=pages),
            }
        )
    viewport = next((s.viewport for s in candidates_ if s.viewport), None)
    if viewport:
        plan["viewport"] = dict(viewport)
    return plan


# built-in strategies --------------------------------------------------------------

from .yahoo import STRATEGIES as _YAHOO  # noqa: E402

for _strategy in _YAHOO:
    register(_strategy)
