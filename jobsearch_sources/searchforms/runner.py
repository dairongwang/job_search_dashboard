"""Execute a search-form strategy against the live site and collect the result rows.

``run_form`` loads the site's page in the headless browser (through the
web-page provider's fetcher, so robots.txt, delays and the 401/403 policy
apply), lets the browser pick the strategy version whose fingerprint matches
the live form, drives the form with the user's criteria and parses every
result snapshot with the matched strategy. The outcome (``FormRun``) says
which version was used, whether the form changed, which chosen options the
live form does not offer, and carries the rows.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .base import FormChanged, SearchFormStrategy, map_criteria
from .learn import learn_form
from .recipe import RecipeStrategy
from .registry import Resolution, browser_plan, next_learned_version, resolve, resolve_key


@dataclass
class FormRun:
    url: str
    configured: str = ""  # strategy key the site is configured with
    tried: list[str] = field(default_factory=list)  # candidate keys, in the order they were tried
    matched: str = ""  # strategy key that matched the live page ("" = none)
    changed: bool = False  # matched a different version than configured
    message: str = ""
    rows: list[dict[str, str]] = field(default_factory=list)
    snapshots: list[str] = field(default_factory=list)
    live_options: dict[str, list[str]] = field(default_factory=dict)
    unknown_choices: list[str] = field(default_factory=list)
    steps_done: int = 0
    step_error: str = ""
    criteria: dict[str, Any] = field(default_factory=dict)
    total: int | None = None  # total hits the site reported, when the strategy can read it
    owns_results: bool = False  # the matched strategy parsed the result list itself (no generic fallback)
    site_message: str = ""  # the site's own "no jobs match your criteria" text, when shown
    learned: dict[str, Any] | None = None  # recipe spec of a version derived from the live page during this run

    @property
    def ok(self) -> bool:
        return bool(self.matched)

    def summary(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("snapshots", None)
        data["rows"] = len(self.rows)
        return data


def _soup(html: str) -> Any:
    from ..htmlpages import _soup as make_soup  # local import: bs4 is optional and htmlpages imports this package

    return make_soup(html)


def learn_from_page(html: str, url: str, candidates: list[SearchFormStrategy], site_id: str = "") -> RecipeStrategy | None:
    """Derive a new strategy version from the page HTML (family and version numbering taken from ``candidates``)."""
    family = candidates[0].family if candidates else f"recipe:{site_id or 'site'}"
    learned = learn_form(_soup(html), url, family=family, version=next_learned_version(candidates))
    if learned is None:
        return None
    return RecipeStrategy(learned.spec, site_id)


def run_form(
    fetcher: Any, url: str, candidates: list[SearchFormStrategy], criteria: dict[str, Any], pages: int = 1, learn: bool = True, site_id: str = ""
) -> FormRun:
    """Drive the form at ``url`` with the first matching candidate and return the parsed rows.

    ``fetcher`` is the web-page provider's ``_Fetcher`` (robots.txt, delays,
    access policy). Raises ``AccessDenied`` through the fetcher when the site
    refuses. When no version matches and ``learn`` is on, a new version is
    derived from the live page and used (``FormRun.learned`` carries its spec
    so it can be saved); ``FormRun.matched == ""`` when that is impossible too.
    """
    if not candidates:
        raise ValueError("no search-form strategy configured for this site.")
    configured = candidates[0]
    crit = configured.normalise_criteria(criteria)
    run = FormRun(url=url, configured=configured.key, tried=[c.key for c in candidates], criteria=crit)
    plan = browser_plan(candidates, crit, pages=pages)
    rendered = fetcher.rendered_with_plan(url, plan)
    if rendered is None:
        run.message = f"browser rendering failed: {fetcher.last_render_error or 'no content'}"
        return run
    resolution: Resolution = resolve_key(rendered.matched, candidates)
    if not resolution.matched and rendered.initial_html:
        # the browser saw none; double-check statically so the message can name the versions tried
        resolution = resolve(_soup(rendered.initial_html), [c for c in candidates if not c.fingerprint()]) if any(not c.fingerprint() for c in candidates) else resolution
    run.matched = resolution.strategy.key if resolution.strategy else ""
    run.changed = resolution.changed
    run.message = resolution.message()
    run.steps_done, run.step_error = rendered.steps_done, rendered.step_error
    if resolution.strategy is None and learn and rendered.initial_html:
        learned = learn_from_page(rendered.initial_html, url, candidates, site_id)
        if learned is not None:
            mapped = map_criteria(criteria, configured.fields(), learned.fields())
            mapped.setdefault("keyword", crit.get("keyword", ""))
            crit = learned.normalise_criteria(mapped)
            rendered = fetcher.rendered_with_plan(url, browser_plan([learned], crit, pages=pages))
            if rendered is not None and rendered.matched == learned.key:
                run.criteria = crit
                run.learned = learned.spec
                run.matched, run.changed = learned.key, True
                run.tried.append(learned.key)
                run.steps_done, run.step_error = rendered.steps_done, rendered.step_error
                run.message = (
                    f"no known version of the search form matched the page, so a new version ({learned.version}) was learned from it: "
                    f"{', '.join(f.label for f in learned.fields())} → {learned.form_hint}. Save the criteria to keep this version."
                )
                resolution = Resolution(learned, list(candidates) + [learned], configured)
            else:
                run.message += f" A version learned from the page ({learned.label}) could not be run either" + (f": {rendered.step_error}" if rendered is not None and rendered.step_error else ".")
    if resolution.strategy is None:
        return run
    strategy = resolution.strategy
    if rendered.initial_html:
        try:
            run.live_options = strategy.live_options(_soup(rendered.initial_html))
        except Exception:  # noqa: BLE001 - never let option discovery break a search
            run.live_options = {}
    run.unknown_choices = strategy.unknown_choices(crit, run.live_options)
    run.snapshots = list(rendered.pages)
    run.owns_results = strategy.owns_results
    seen: set[str] = set()
    for html in run.snapshots:
        soup = _soup(html)
        if run.total is None and hasattr(strategy, "results_total"):
            try:
                _shown, total = strategy.results_total(soup)
                run.total = total
            except Exception:  # noqa: BLE001
                pass
        if not run.site_message:
            try:
                run.site_message = strategy.no_results_message(soup)
            except Exception:  # noqa: BLE001
                run.site_message = ""
        for row in strategy.parse_results(soup, url):
            key = row.get("link") or row.get("title", "")
            if key in seen:
                continue
            seen.add(key)
            run.rows.append(row)
    return run


def ensure_matched(run: FormRun) -> None:
    """Raise ``FormChanged`` when no strategy version matched the live page."""
    if not run.matched:
        raise FormChanged(run.message, family=run.configured.split("@")[0], tried=tuple(run.tried))
