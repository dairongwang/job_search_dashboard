"""Search-form strategies: one object per *site* and per *version of its form*.

Job sites offer a search form (keywords, category / country / brand
dropdowns, a *Find jobs* button) but every site implements it differently,
and the same site changes it over time. The **Strategy pattern** keeps each
implementation in one place:

* ``SearchFormStrategy`` — the interface: which *fields* the form has (so the
  configuration dashboard can show the same form to the user), how to
  recognise this version of the form on the live page (*fingerprint*), how to
  drive it (*steps* for the headless browser) and how to read the result list
  (*parse_results*).
* ``family`` + ``version`` — a site's strategies share a family key
  (``yahoo-careers``) and carry a version (``2``, ``1`` …). The registry tries
  the newest version whose fingerprint matches the live page first and falls
  back to older ones, so a redesign of the form is detected instead of
  silently returning nothing; when no version matches, ``FormChanged`` is
  raised with the list of versions that were tried.
* ``RecipeStrategy`` (``recipe.py``) — a declarative strategy built from JSON
  in the site's options, for sites that have no Python class yet.

Strategies never fetch anything themselves; the runner (``runner.py``) and
the web-page provider do the HTTP/browser work, honouring robots.txt and the
access policy like every other request of the app.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from typing import Any
from urllib.parse import urlsplit

FIELD_KINDS = ("text", "select", "multiselect", "checkbox")


class FormChanged(ValueError):
    """No known version of the site's search form matches the live page."""

    def __init__(self, message: str, family: str = "", tried: tuple[str, ...] = ()):
        super().__init__(message)
        self.family = family
        self.tried = tried


@dataclass
class FormField:
    """One control of a site's search form, as shown to the user in the test panel."""

    key: str  # criteria key, e.g. "keyword", "categories"
    label: str  # visible label on the site, e.g. "Select job categories"
    kind: str = "text"  # text | select | multiselect | checkbox
    options: list[str] = field(default_factory=list)  # known choices (refreshed from the live page when possible)
    placeholder: str = ""
    help: str = ""
    binds: str = ""  # "keyword": filled from the app's search phrase at search time; "" = user-chosen criteria only

    def __post_init__(self) -> None:
        if self.kind not in FIELD_KINDS:
            raise ValueError(f"field {self.key!r}: unknown kind {self.kind!r} (expected one of {', '.join(FIELD_KINDS)})")
        self.options = [str(o) for o in self.options]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def css_string(value: Any) -> str:
    """Quote a value for use inside a CSS attribute selector: ``[value="..."]``."""
    text = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{text}"'


def host_matches(url: str, hosts: tuple[str, ...]) -> bool:
    host = urlsplit(url).netloc.lower().split("@")[-1].split(":")[0]
    host = host[4:] if host.startswith("www.") else host
    return any(host == h or host.endswith("." + h) for h in hosts if h)


def _norm_label(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).replace("select ", "").replace("choose ", "").strip()


def map_criteria(criteria: dict[str, Any], source: list[FormField], target: list[FormField]) -> dict[str, Any]:
    """Carry criteria entered for one version's fields over to another version's fields.

    Fields are matched by key, then by visible label (``Select countries`` ≈
    ``Countries``), then by identical option sets (the same 20 countries under
    another name). Unmatched target fields stay blank.
    """
    criteria = dict(criteria or {})
    by_key = {f.key: f for f in source}
    by_label = {_norm_label(f.label): f for f in source}
    by_options = {tuple(sorted(o.lower() for o in f.options)): f for f in source if f.options}
    out: dict[str, Any] = {}
    for field_ in target:
        match = by_key.get(field_.key) or by_label.get(_norm_label(field_.label))
        if match is None and field_.options:
            match = by_options.get(tuple(sorted(o.lower() for o in field_.options)))
        if match is None and field_.binds:
            match = next((f for f in source if f.binds == field_.binds), None)
        if match is not None and match.key in criteria:
            out[field_.key] = criteria[match.key]
    return out


def _version_key(version: str) -> tuple[int, str]:
    """Sort key: numbered versions (``2`` > ``1``) rank above learned ones (``auto-2`` > ``auto-1``)."""
    text = str(version)
    match = re.match(r"^(\d+)", text)
    if match:
        return int(match.group(1)), text
    learned = re.match(r"^auto-(\d+)$", text)
    if learned:
        return 0, f"{int(learned.group(1)):06d}"
    return -1, text


class SearchFormStrategy(ABC):
    """Interface every site/version strategy implements.

    Subclasses set the class attributes and override ``fields``, ``steps`` and
    (usually) ``parse_results`` and ``live_options``. ``fingerprint`` is a
    list of CSS selectors that must all be present on the live page for this
    version to apply — declarative, so it can be evaluated both on static HTML
    (BeautifulSoup) and inside the headless browser before any step runs.
    """

    family: str = ""  # shared by all versions of one site's strategy
    version: str = "1"
    since: str = ""  # when this layout was observed, e.g. "2026-02"
    label: str = ""
    hosts: tuple[str, ...] = ()  # registrable hosts this strategy applies to
    form_hint: str = ""  # human hint about the form, e.g. "form#collapseFilterJobs"
    start_url: str = ""  # page the form lives on (suggested URL when adding the site)
    viewport: dict[str, int] | None = None  # browser viewport needed for the form to be visible (None = default)
    notes: str = ""

    # -- identity -------------------------------------------------------------

    @property
    def key(self) -> str:
        return f"{self.family}@{self.version}"

    @property
    def sort_key(self) -> tuple[int, str]:
        return _version_key(self.version)

    def applies_to(self, url: str) -> bool:
        return host_matches(url, self.hosts)

    # -- the form as the user sees it ---------------------------------------------

    @abstractmethod
    def fields(self) -> list[FormField]:
        """Controls of the form, in the order the site shows them."""

    def field(self, key: str) -> FormField | None:
        return next((f for f in self.fields() if f.key == key), None)

    def normalise_criteria(self, criteria: dict[str, Any] | None) -> dict[str, Any]:
        """Coerce user criteria to the field kinds; unknown keys are dropped."""
        criteria = dict(criteria or {})
        out: dict[str, Any] = {}
        for spec in self.fields():
            value = criteria.get(spec.key)
            if spec.kind == "multiselect":
                if isinstance(value, str):
                    value = [v.strip() for v in value.split(",") if v.strip()]
                out[spec.key] = [str(v) for v in (value or []) if str(v).strip()]
            elif spec.kind == "checkbox":
                out[spec.key] = bool(value)
            else:
                out[spec.key] = "" if value is None else str(value).strip()
        return out

    def describe_criteria(self, criteria: dict[str, Any] | None) -> str:
        parts = []
        for spec in self.fields():
            value = (criteria or {}).get(spec.key)
            if value in (None, "", [], False):
                continue
            parts.append(f"{spec.label}: {', '.join(value) if isinstance(value, list) else value}")
        return "; ".join(parts) or "no criteria (all jobs)"

    def unknown_choices(self, criteria: dict[str, Any], live_options: dict[str, list[str]] | None = None) -> list[str]:
        """Chosen values that the form (static or live) does not offer."""
        problems: list[str] = []
        for spec in self.fields():
            if spec.kind not in ("select", "multiselect"):
                continue
            offered = (live_options or {}).get(spec.key) or spec.options
            if not offered:
                continue
            chosen = criteria.get(spec.key) or []
            chosen = chosen if isinstance(chosen, list) else [chosen]
            lowered = {o.lower() for o in offered}
            missing = [c for c in chosen if c and c.lower() not in lowered]
            if missing:
                problems.append(f"{spec.label}: {', '.join(missing)} not offered (available: {', '.join(offered[:12])}{'…' if len(offered) > 12 else ''})")
        return problems

    # -- recognising this version on the live page ----------------------------------

    def fingerprint(self) -> list[str]:
        """CSS selectors that must ALL be present for this version of the form."""
        return []

    def absent(self) -> list[str]:
        """CSS selectors that must NOT be present (to tell versions apart)."""
        return []

    def matches(self, soup: Any) -> bool:
        """Evaluate the fingerprint on a BeautifulSoup document (static or rendered HTML)."""
        try:
            if any(soup.select_one(sel) is None for sel in self.fingerprint()):
                return False
            return not any(soup.select_one(sel) is not None for sel in self.absent())
        except Exception:  # invalid selector for soupsieve
            return False

    def live_options(self, soup: Any) -> dict[str, list[str]]:
        """Choices the live page offers per field (``{}`` when the strategy cannot read them)."""
        return {}

    # -- driving the form and reading the results -----------------------------------

    @abstractmethod
    def steps(self, criteria: dict[str, Any], pages: int = 1) -> list[dict[str, Any]]:
        """Browser steps (see ``browser.run_steps``) that fill the form for ``criteria`` and submit it.

        ``pages`` = how many result pages / *Load more* clicks to collect.
        """

    def parse_results(self, soup: Any, base_url: str) -> list[dict[str, str]]:
        """Rows (title, link, company, location, salary, date, description, job_type) from a results snapshot.

        A strategy that overrides this **owns** the result list: an empty
        return means the site found no jobs, and the provider must not fall
        back to generic page extraction (which would pick up navigation links
        of the page and present them as jobs). Strategies that do not override
        it (``owns_results`` is False) let the provider read the snapshots
        generically (schema.org JobPosting data, CSS selectors, job links).
        """
        return []

    @property
    def owns_results(self) -> bool:
        """True when this strategy parses the site's result list itself (see ``parse_results``)."""
        return type(self).parse_results is not SearchFormStrategy.parse_results

    def no_results_message(self, soup: Any) -> str:
        """The site's own "no jobs match" message when the page shows one (``""`` otherwise)."""
        return ""

    # -- presentation -------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "family": self.family,
            "version": self.version,
            "since": self.since,
            "label": self.label,
            "hosts": list(self.hosts),
            "form_hint": self.form_hint,
            "start_url": self.start_url,
            "fingerprint": self.fingerprint(),
            "fields": [f.to_dict() for f in self.fields()],
            "notes": self.notes,
        }

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<{self.__class__.__name__} {self.key}>"
