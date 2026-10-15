"""Operations the dashboards and CLI perform with search-form strategies.

* ``detect(url)`` — which strategy versions know this site, and which one
  matches the live page right now (plus the choices its dropdowns offer).
* ``test_form(site, config, criteria)`` — run the site's form with the
  criteria the user entered in the mirrored test panel; returns the jobs and
  whether the test passed (at least one job). The configuration dashboard
  refuses to add or enable a form-driven site until a test passes.
* ``site_with_criteria`` / ``form_site_options`` / ``mark_validated`` — build
  the ``search_form`` option block that records strategy, version, criteria
  and the last passing test.
* ``validation_status(site)`` — has the site passed a test (and with which
  version), for validation and display.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

from jobsearch_config.catalog import default_options
from jobsearch_config.schema import SearchSettings, SiteConfig

from .. import browser, robots
from ..http import FetchError, fetch_bytes
from .base import SearchFormStrategy
from .learn import learn_form
from .recipe import RecipeStrategy
from .registry import browser_plan, candidates as strategy_candidates, for_url, next_learned_version, resolve, resolve_key


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _soup(html: str) -> Any:
    from ..htmlpages import _soup as make_soup

    return make_soup(html)


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


@dataclass
class Detection:
    url: str
    host: str = ""
    candidates: list[dict[str, Any]] = field(default_factory=list)  # strategies known for this site (to_dict), newest first
    matched: str = ""  # key that matches the live page ("" = none)
    changed: bool = False
    live_options: dict[str, list[str]] = field(default_factory=dict)
    rendered: bool = False
    robots_allowed: bool | None = None
    http_status: int = 0
    denied: bool = False
    error: str = ""
    message: str = ""
    learned: dict[str, Any] | None = None  # a version derived from the page because no known one matched

    @property
    def known(self) -> bool:
        return bool(self.candidates)

    @property
    def ok(self) -> bool:
        return bool(self.matched) and not self.error

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def detect(
    url: str,
    settings: SearchSettings | None = None,
    options: dict[str, Any] | None = None,
    site_id: str = "",
    render: bool = True,
    record: bool = True,
    learn: bool = True,
) -> Detection:
    """Which search-form strategy applies to ``url``, and does its fingerprint match the live page?

    Uses the headless browser when available (the form's dropdowns are often
    filled by JavaScript), otherwise a plain fetch. Honours robots.txt and
    records a refusal (401/403) in the site registry like every other check.
    """
    settings = settings or SearchSettings()
    report = Detection(url=url, host=urlsplit(url).netloc.lower())
    found = strategy_candidates(options, url, site_id) if options else []
    if not found:
        found = for_url(url)
    report.candidates = [s.to_dict() for s in found]
    try:
        from jobsearch_config.registry import load_registry

        blocked = load_registry().forbidden(url)
    except (OSError, ValueError):
        blocked = None
    if blocked is not None and blocked.policy_block:
        report.denied = True
        report.error = f"{blocked.host} prohibits automated access by its terms of use — {blocked.message}"
        report.message = report.error
        return report
    if not found:
        report.message = (
            f"No search-form strategy is registered for {report.host}. Run Investigate on the page to list its controls, "
            "then add a recipe (Search form JSON) or a strategy class for the site."
        )
        return report
    verdict = robots.check(url, settings)
    report.robots_allowed = verdict.allowed
    if not verdict.allowed:
        report.error = verdict.reason
        report.message = verdict.reason
        if record and not verdict.unreachable:
            _record(url, "forbidden", verdict.reason)
        return report
    html = ""
    matched_key = ""
    if render and browser.available()[0]:
        plan = browser_plan(found, {}, pages=1)
        for candidate in plan["candidates"]:
            candidate["steps"] = []  # look, don't touch
        pages = browser.render_pages([url], settings, delay_seconds=0, plans={url: plan})
        page = pages[0] if pages else None
        if page is not None and page.denied:
            report.denied, report.http_status = True, page.status
            report.error = f"the site refused a real browser session (HTTP {page.status}); this app does not work around that."
            report.message = report.error
            if record:
                _record(url, "forbidden", report.error, page.status)
            return report
        if page is not None and (page.initial_html or page.html):
            html = page.initial_html or page.html
            matched_key = page.matched
            report.rendered = True
            report.http_status = page.status
        elif page is not None and page.error:
            report.message = f"browser rendering failed ({page.error}); checked the plain page instead."
    if not html:
        try:
            raw = fetch_bytes(url, timeout=settings.timeout_seconds, user_agent=settings.user_agent)
            html = raw.decode("utf-8", errors="replace")
            report.http_status = 200
        except FetchError as exc:
            report.http_status = exc.status
            report.denied = exc.status in (401, 403, 429)
            report.error = str(exc)
            report.message = report.error
            if record and report.denied:
                _record(url, "forbidden", f"the site refused automated access (HTTP {exc.status}).", exc.status)
            return report
    soup = _soup(html)
    resolution = resolve_key(matched_key, found) if report.rendered else resolve(soup, found)
    if report.rendered and not resolution.matched:
        resolution = resolve(soup, found)  # fingerprints are plain CSS: the static check is a fair second opinion
    report.matched = resolution.strategy.key if resolution.strategy else ""
    report.changed = resolution.changed
    if resolution.strategy is not None:
        try:
            report.live_options = resolution.strategy.live_options(soup)
        except Exception:  # noqa: BLE001
            report.live_options = {}
    report.message = resolution.message()
    if resolution.strategy is None and learn:
        learned = learn_form(soup, url, family=found[0].family, version=next_learned_version(found))
        if learned is not None:
            report.learned = learned.spec
            strategy = RecipeStrategy(learned.spec, site_id)
            report.matched = strategy.key
            report.changed = True
            report.live_options = {f.key: list(f.options) for f in strategy.fields() if f.options}
            report.message = (
                f"no known version of the search form matched this page, so a new version ({strategy.version}) was derived from it: "
                f"{learned.summary}. Fill in the form below and press Find jobs to validate it."
            )
    return report


def _record(url: str, status: str, message: str, status_code: int = 0) -> None:
    try:
        from jobsearch_config.registry import block_reason, load_registry

        load_registry().record(url, status, message, source="probe", status_code=status_code, reason=block_reason(message, status_code) if status == "forbidden" else "")
    except (OSError, ValueError):
        pass


# ---------------------------------------------------------------------------
# Site options
# ---------------------------------------------------------------------------


def form_block(
    strategy: SearchFormStrategy,
    criteria: dict[str, Any] | None = None,
    validated: dict[str, Any] | None = None,
    live_options: dict[str, list[str]] | None = None,
    existing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The ``search_form`` option block for a site using ``strategy``."""
    block: dict[str, Any] = dict(existing or {})
    if strategy.family.startswith("recipe") or getattr(strategy, "spec", None) is not None:
        block.setdefault("strategy", "recipe")
        spec = getattr(strategy, "spec", {}) or {}
        for key in ("fields", "steps", "fingerprint", "absent", "results", "viewport", "label", "version"):
            if key in spec and key not in block:
                block[key] = spec[key]
    else:
        block["strategy"] = strategy.family
        block["version"] = strategy.version
    block["criteria"] = strategy.normalise_criteria(criteria if criteria is not None else block.get("criteria"))
    if live_options:
        block["live_options"] = {k: list(v) for k, v in live_options.items()}
    if validated is not None:
        block["validated"] = dict(validated)
    return block


def form_site_options(strategy: SearchFormStrategy, url: str, criteria: dict[str, Any] | None = None, **kwargs: Any) -> dict[str, Any]:
    """Complete options for a new web-page site driven by ``strategy``."""
    options = default_options("html")
    options["url"] = url or strategy.start_url
    options["render"] = "always"
    options["follow_links"] = "always"  # result rows carry title/company/location only; job pages add description, salary, type
    options["search_form"] = form_block(strategy, criteria, kwargs.get("validated"), kwargs.get("live_options"))
    return options


def with_learned(block: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
    """Add a learned version spec to a ``search_form`` block (replacing one with the same version) and select it."""
    block = dict(block)
    version = str(spec.get("version") or "auto-1")
    kept = [s for s in (block.get("learned") or []) if isinstance(s, dict) and str(s.get("version")) != version]
    stored = {k: v for k, v in spec.items() if k not in ("strategy", "criteria")}
    block["learned"] = kept + [stored]
    block["version"] = version
    if not block.get("strategy"):
        block["strategy"] = str(spec.get("family") or "recipe")
    return block


def site_with_criteria(site: SiteConfig, criteria: dict[str, Any], strategy: SearchFormStrategy | None = None, learned: dict[str, Any] | None = None) -> SiteConfig:
    """A copy of ``site`` whose search form uses ``criteria`` (for a test run; nothing is saved).

    ``learned`` is a version spec derived from the live page (see ``learn.py``); it
    is added to the copy and selected, so the test runs with it.
    """
    strategy = strategy or _configured(site)
    if strategy is None and learned is None:
        raise ValueError(f"site {site.id} has no search-form strategy.")
    options = dict(site.options)
    existing = _block(options)
    if learned is not None:
        base = existing or {"strategy": str(learned.get("family") or "recipe")}
        options["search_form"] = with_learned(base, learned)
        strategy = RecipeStrategy({**learned, "family": options["search_form"]["strategy"] if options["search_form"]["strategy"] not in ("recipe", "auto") else learned.get("family", "recipe")}, site.id)
        options["search_form"]["criteria"] = strategy.normalise_criteria(criteria)
    elif existing is None and options.get("actions"):  # legacy recipe: keep its steps, replace the values
        options["form_values"] = strategy.normalise_criteria(criteria)
    else:
        options["search_form"] = form_block(strategy, criteria, existing=existing)
    if str(options.get("render") or "auto") == "never":
        options["render"] = "auto"
    return SiteConfig(id=site.id, provider=site.provider, name=site.name, enabled=site.enabled, max_results=site.max_results, options=options, notes=site.notes)


def _block(options: dict[str, Any]) -> dict[str, Any] | None:
    block = options.get("search_form")
    return block if isinstance(block, dict) and block else None


def _configured(site: SiteConfig) -> SearchFormStrategy | None:
    found = strategy_candidates(site.options, str(site.options.get("url") or ""), site.id)
    return found[0] if found else None


def mark_validated(site: SiteConfig, test: "FormTest") -> SiteConfig:
    """Write the criteria, the matched version and the passing test into the site's options (in place)."""
    strategy = _configured(site) or _configured(test.site)
    if strategy is None:
        raise ValueError(f"site {site.id} has no search-form strategy.")
    if test.matched and "@" in test.matched and not strategy.family.startswith("recipe") and not test.learned:
        from .registry import get

        family, version = test.matched.split("@", 1)
        strategy = get(family, version) or strategy
    existing = _block(site.options)
    if existing is None and site.options.get("actions"):  # upgrade legacy steps to a recipe block
        site.options["search_form"] = {"strategy": "recipe", "steps": list(site.options.pop("actions") or []), "criteria": strategy.normalise_criteria(test.criteria)}
        site.options.pop("form_values", None)
        site.options["actions"] = []
        existing = site.options["search_form"]
    if test.learned:
        existing = with_learned(existing or {"strategy": str(test.learned.get("family") or "recipe")}, test.learned)
        strategy = RecipeStrategy({**test.learned, "family": existing["strategy"] if existing["strategy"] not in ("recipe", "auto") else test.learned.get("family", "recipe")}, site.id)
        block = form_block(strategy, test.criteria, test.validated_record(), test.live_options, existing)
        block["strategy"], block["version"] = existing["strategy"], existing["version"]
        site.options["search_form"] = block
        return site
    site.options["search_form"] = form_block(strategy, test.criteria, test.validated_record(), test.live_options, existing)
    return site


def validation_status(site: SiteConfig) -> tuple[bool, str]:
    """(passed, text) — whether the site's search form has a recorded passing test."""
    block = _block(site.options)
    if block is None:
        if site.options.get("actions"):
            return False, "legacy search-form steps; not yet tested with Find jobs"
        return False, "no search form configured"
    validated = block.get("validated") if isinstance(block.get("validated"), dict) else None
    if not validated:
        return False, "not yet tested — press Find jobs in the site's search-form panel"
    jobs = int(validated.get("jobs") or 0)
    when = str(validated.get("at") or "")
    key = str(validated.get("strategy") or "")
    if jobs > 0:
        return True, f"passed {when} with {jobs} job(s) using {key}"
    return False, f"last test {when} returned no jobs ({key})"


# ---------------------------------------------------------------------------
# Test run
# ---------------------------------------------------------------------------


@dataclass
class FormTest:
    site: SiteConfig
    criteria: dict[str, Any]
    jobs: list[Any] = field(default_factory=list)
    error: str = ""
    denied: bool = False
    form_changed: bool = False
    configured: str = ""
    matched: str = ""
    changed: bool = False
    live_options: dict[str, list[str]] = field(default_factory=dict)
    unknown_choices: list[str] = field(default_factory=list)
    notes: str = ""
    total: int | None = None
    seconds: float = 0.0
    tested_at: str = field(default_factory=_now)
    learned: dict[str, Any] | None = None  # version derived from the live page during this test (saved by mark_validated)

    @property
    def strategy(self) -> SearchFormStrategy | None:
        """The strategy the test ran with (a learned one when applicable) — for rendering its fields."""
        return _configured(self.site)

    @property
    def ok(self) -> bool:
        """The test passed: the form was driven and at least one job came back."""
        return not self.error and len(self.jobs) > 0

    def validated_record(self) -> dict[str, Any]:
        return {
            "at": self.tested_at,
            "jobs": len(self.jobs),
            "strategy": self.matched or self.configured,
            "criteria": dict(self.criteria),
            "total": self.total,
            "error": self.error,
        }

    def summary(self) -> str:
        if self.error:
            return self.error
        what = f"{len(self.jobs)} job(s)"
        if self.total:
            what += f" of {self.total} the site reported"
        return f"{what} in {self.seconds}s using {self.matched or self.configured}"


def test_form(site: SiteConfig, config: Any, criteria: dict[str, Any], registry: Any = None, learned: dict[str, Any] | None = None) -> FormTest:
    """Drive the site's search form with ``criteria`` and return the unfiltered jobs (nothing is saved).

    ``learned`` = a version spec derived from the page by an earlier detect/test:
    the test runs with it (and ``FormTest.learned`` carries it on for saving).
    """
    from ..search import search_site  # local import: search -> providers -> htmlpages -> searchforms

    strategy = _configured(site)
    if strategy is None and learned is None:
        return FormTest(site=site, criteria=dict(criteria or {}), error="this site has no search-form strategy configured.")
    trial = site_with_criteria(site, criteria, strategy, learned=learned)
    strategy = _configured(trial)
    crit = strategy.normalise_criteria(criteria)
    keyword = str(crit.get("keyword") or "")
    if registry is None:
        try:
            from jobsearch_config.registry import load_registry

            registry = load_registry()
        except (OSError, ValueError):
            registry = None
    jobs, outcome = search_site(trial, config, [keyword] if keyword else [], registry, explicit=True)  # exactly what the panel shows
    info = outcome.details.get("search_form") or {}
    last = (info.get("runs") or [{}])[-1]
    learned_spec = info.get("learned") or learned
    if info.get("learned"):
        crit = dict(last.get("criteria") or crit)  # mapped onto the learned fields by the runner
    return FormTest(
        site=trial,
        criteria=crit,
        learned=learned_spec,
        jobs=list(jobs),
        error=outcome.error,
        denied=outcome.denied,
        form_changed=outcome.form_changed,
        configured=str(info.get("configured") or strategy.key),
        matched=str(info.get("matched") or ""),
        changed=bool(info.get("changed")),
        live_options=dict(info.get("live_options") or {}),
        unknown_choices=list(last.get("unknown_choices") or []),
        notes=outcome.note,
        total=last.get("total"),
        seconds=outcome.seconds,
    )
