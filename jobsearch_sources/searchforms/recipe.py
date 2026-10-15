"""Declarative search-form strategy built from JSON in the site's options.

For a site without a Python strategy class, the ``search_form`` option of a
web-page site can describe the form itself::

    {
      "strategy": "recipe",
      "version": "1",
      "fingerprint": ["input[placeholder='Key words']", "button:has-text('Find jobs')"],
      "fields": [
        {"key": "keyword", "label": "Key words", "kind": "text", "binds": "keyword"},
        {"key": "country", "label": "Select countries", "kind": "select", "options": ["United States", "Canada"]},
        {"key": "brands", "label": "Select brands", "kind": "multiselect", "options": ["Yahoo", "AOL"]}
      ],
      "steps": [
        {"fill": {"placeholder": "Key words"}, "value": "{keyword}"},
        {"select": {"label": "Select countries"}, "value": "{country}"},
        {"check": {"label": "{brands}"}},
        {"click": {"button": "Find jobs"}},
        {"wait": "networkidle"}
      ],
      "results": {"item_selector": "#results li", "title_selector": "a", "link_selector": "a"},
      "criteria": {"country": "United States", "brands": ["Yahoo"]}
    }

``steps`` use the browser step vocabulary with ``{placeholders}`` named after
the fields (a list value repeats its step per item). ``results`` is optional:
without it the provider's generic extraction reads the snapshots.

The legacy ``actions`` + ``form_values`` options of a web-page site are
upgraded to a recipe automatically (``from_legacy``), so existing
configurations keep working.
"""

from __future__ import annotations

import json
import re
from typing import Any

from .base import FormField, SearchFormStrategy

_PLACEHOLDER = re.compile(r"\{([a-zA-Z_][\w-]*)\}")
_RESERVED = {"page", "location", "limit"}


def expand_steps(steps: list[dict[str, Any]], values: dict[str, Any]) -> list[dict[str, Any]]:
    """Substitute ``{name}`` placeholders in a step list from ``values``.

    A placeholder whose value is a list expands the step into one step per
    item (e.g. ticking several brands); an empty list drops the step. Unknown
    placeholders are left as is.
    """

    def fill(node: Any, table: dict[str, Any]) -> Any:
        if isinstance(node, str):
            return _PLACEHOLDER.sub(lambda m: str(table.get(m.group(1), m.group(0))), node)
        if isinstance(node, dict):
            return {k: fill(v, table) for k, v in node.items()}
        if isinstance(node, list):
            return [fill(v, table) for v in node]
        return node

    out: list[dict[str, Any]] = []
    for step in steps:
        text = json.dumps(step)
        list_names = [name for name in _PLACEHOLDER.findall(text) if isinstance(values.get(name), list)]
        if list_names:
            name = list_names[0]
            for item in values[name]:
                out.append(fill(step, {**values, name: item}))
        else:
            out.append(fill(step, values))
    return out


def placeholders_in(steps: list[dict[str, Any]]) -> list[str]:
    names: list[str] = []
    for step in steps:
        for name in _PLACEHOLDER.findall(json.dumps(step)):
            if name not in names and name not in _RESERVED:
                names.append(name)
    return names


class RecipeStrategy(SearchFormStrategy):
    """A strategy whose fields, fingerprint, steps and result selectors come from a JSON spec."""

    family = "recipe"

    def __init__(self, spec: dict[str, Any], site_id: str = ""):
        spec = dict(spec or {})
        self.spec = spec
        self.site_id = site_id
        self.family = str(spec.get("family") or (f"recipe:{site_id}" if site_id else "recipe"))
        self.version = str(spec.get("version") or "1")
        self.since = str(spec.get("since") or "")
        self.label = str(spec.get("label") or f"Recipe for {site_id or 'this page'}")
        self.hosts = tuple(spec.get("hosts") or ())
        self.form_hint = str(spec.get("form_hint") or "")
        self.notes = str(spec.get("notes") or "")
        self.viewport = dict(spec["viewport"]) if isinstance(spec.get("viewport"), dict) else None
        self._steps = [s for s in (spec.get("steps") or spec.get("actions") or []) if isinstance(s, dict)]
        self._fingerprint = [str(s) for s in (spec.get("fingerprint") or []) if str(s).strip()]
        self._absent = [str(s) for s in (spec.get("absent") or []) if str(s).strip()]
        self._results = dict(spec.get("results") or {})
        self._fields = self._build_fields(spec.get("fields"), dict(spec.get("criteria") or {}))

    # -- construction ---------------------------------------------------------------

    def _build_fields(self, raw: Any, criteria: dict[str, Any]) -> list[FormField]:
        fields: list[FormField] = []
        if isinstance(raw, list) and raw:
            for item in raw:
                if not isinstance(item, dict) or not item.get("key"):
                    continue
                kind = str(item.get("kind") or ("multiselect" if isinstance(criteria.get(item["key"]), list) else "text"))
                fields.append(
                    FormField(
                        key=str(item["key"]),
                        label=str(item.get("label") or item["key"]),
                        kind=kind,
                        options=[str(o) for o in (item.get("options") or [])],
                        placeholder=str(item.get("placeholder") or ""),
                        help=str(item.get("help") or ""),
                        binds="keyword" if item["key"] == "keyword" else str(item.get("binds") or ""),
                    )
                )
        if not fields:  # derive from the placeholders used by the steps
            for name in placeholders_in(self._steps):
                kind = "multiselect" if isinstance(criteria.get(name), list) else "text"
                fields.append(FormField(name, name.replace("_", " ").capitalize(), kind, binds="keyword" if name == "keyword" else ""))
        if not any(f.key == "keyword" for f in fields) and "{keyword}" in json.dumps(self._steps):
            fields.insert(0, FormField("keyword", "Keyword", "text", binds="keyword"))
        return fields

    @classmethod
    def from_legacy(cls, actions: list[dict[str, Any]], form_values: dict[str, Any] | None, site_id: str = "") -> "RecipeStrategy":
        """Upgrade the old ``actions`` + ``form_values`` options to a recipe strategy."""
        return cls({"steps": list(actions or []), "criteria": dict(form_values or {}), "label": f"Search-form steps of {site_id or 'this site'}"}, site_id)

    # -- interface ------------------------------------------------------------------

    def fields(self) -> list[FormField]:
        return list(self._fields)

    def fingerprint(self) -> list[str]:
        return list(self._fingerprint)

    def absent(self) -> list[str]:
        return list(self._absent)

    def steps(self, criteria: dict[str, Any], pages: int = 1) -> list[dict[str, Any]]:
        crit = self.normalise_criteria(criteria)
        values = dict(self.spec.get("criteria") or {})  # saved defaults for whatever the caller left blank
        values.update({k: v for k, v in crit.items() if v not in ("", [], None, False)})
        values["page"] = pages
        values["load_more"] = max(0, pages - 1)
        keys = {f.key for f in self.fields()}
        out: list[dict[str, Any]] = []
        for step in expand_steps(self._steps, values):
            text = json.dumps(step)
            if any(f"{{{key}}}" in text for key in keys):
                continue  # the field this step needs was left blank: skip it (e.g. an untouched <select>)
            if str(step.get("repeat", "1")).strip() in ("0", "-0"):
                continue
            out.append(step)
        return out

    def parse_results(self, soup: Any, base_url: str) -> list[dict[str, str]]:
        if self._results.get("auto"):
            from .learn import learned_results

            return learned_results(soup, base_url)
        if not self._results.get("item_selector"):
            return []
        from ..htmlpages import extract_with_selectors  # local import: avoids a cycle at import time

        return extract_with_selectors(soup, self._results, base_url)

    @property
    def learned(self) -> bool:
        return bool(self.spec.get("learned"))

    @property
    def owns_results(self) -> bool:
        return bool(self._results.get("item_selector") or self._results.get("auto"))

    def no_results_message(self, soup: Any) -> str:
        selector = str(self._results.get("empty_selector") or "").strip()
        if not selector:
            return ""
        try:
            node = soup.select_one(selector)
        except Exception:  # invalid selector
            return ""
        return node.get_text(" ", strip=True) if node else ""

    @property
    def result_selectors(self) -> dict[str, Any]:
        return dict(self._results)

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["steps"] = list(self._steps)
        data["results"] = dict(self._results)
        return data
