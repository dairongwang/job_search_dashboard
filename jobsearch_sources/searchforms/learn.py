"""Learn a search-form strategy from the live page when no known version matches.

When a site redesigns its form (or the user points the app at another page
of the site), none of the registered versions fingerprints the page. Rather
than stopping, the app **derives a new version from the page itself**:

1. ``learn_form(soup, url)`` inspects the page's forms (and form-like
   containers): the keyword box, checkbox/radio groups (Bootstrap-style
   dropdowns, fieldsets), native ``<select>`` controls and the submit button.
   It picks the most search-like one and writes a **recipe spec** — fields
   (so the configuration dashboard can mirror the form), a fingerprint (so
   the version is recognised next time and told apart from future changes),
   browser steps (fill, tick, submit) and ``"results": {"auto": true}``.
2. ``learned_results(soup, url)`` reads the result list of the page that
   comes back: the dominant group of structurally identical links outside
   navigation/header/footer (a job list is a repeated row with a link each).
   Nothing repeated → zero jobs; the learner never turns a page's menu into
   listings.

The learned spec is a ``RecipeStrategy`` version (``auto-1``, ``auto-2`` …)
of the site's family. The run that learned it uses it straight away; the
configuration dashboard shows its fields, and *Save criteria* stores it in
the site's ``search_form.learned`` list so later searches use it directly.
Saved learned versions take part in version resolution like built-in ones.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any
from urllib.parse import urljoin, urlsplit

_KEYWORD_HINT = re.compile(r"keyword|search|what|title|query|\bq\b|job|role|skill", re.IGNORECASE)
_SUBMIT_HINT = re.compile(r"find|search|go\b|submit|apply|show|filter|view jobs|see jobs", re.IGNORECASE)
_NAV_ANCESTOR = re.compile(r"\bnav\b|navbar|navigation|menu|header|footer|breadcrumb|sidebar|cookie|social|pagination|pager|copyright|legal", re.IGNORECASE)
_JOB_LINK = re.compile(r"/(job|jobs|career|careers|position|positions|posting|postings|vacanc|opening|requisition|opportunit)[^ ]*|[?&](job|jobid|job_id|id|req)=|JR\d{3,}|R\d{5,}", re.IGNORECASE)
_LIST_CONTAINER = re.compile(r"result|job|listing|position|opening|vacanc|career|search|posting", re.IGNORECASE)
_COUNTRY_WORDS = (
    "remote", "united states", "usa", "u.s.", "canada", "united kingdom", "uk", "ireland", "india", "germany", "france", "spain", "italy",
    "australia", "japan", "taiwan", "singapore", "brazil", "mexico", "netherlands", "sweden", "norway", "denmark", "israel", "poland",
    "hong kong", "new zealand", "switzerland", "hybrid", "on-site", "onsite",
)


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_")[:40] or "field"


def _css_attr(value: str) -> str:
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _node_selector(node: Any, fallback: str = "") -> str:
    """Best stable CSS for a node: #id, else tag[name=…], else the fallback."""
    node_id = node.get("id")
    if node_id and re.match(r"^[A-Za-z][\w-]*$", node_id) and not re.search(r"\d{5,}|[a-f0-9]{12,}", node_id):
        return f"#{node_id}"
    name = node.get("name")
    if name:
        return f"{node.name}[name={_css_attr(name)}]"
    return fallback or node.name


def _form_selector(form: Any, index: int) -> str:
    if form.name != "form":
        return _node_selector(form, f"{form.name}")
    if form.get("id"):
        return f"form#{form['id']}"
    if form.get("action"):
        return f"form[action={_css_attr(form['action'])}]"
    return "form" if index == 0 else f"form:nth-of-type({index + 1})"


def _in_navigation(node: Any) -> bool:
    for parent in node.parents:
        if parent is None or parent.name in (None, "html", "body"):
            break
        if parent.name in ("nav", "header", "footer") or (parent.get("role") or "").lower() == "navigation":
            return True
        signature = " ".join([parent.get("id") or ""] + list(parent.get("class") or []))
        if signature and _NAV_ANCESTOR.search(signature):
            return True
    return False


def _group_label(group_nodes: list[Any], name: str, form: Any) -> str:
    """Visible label of a checkbox/radio group: dropdown toggle text, legend, heading, or the name."""
    first = group_nodes[0]
    for parent in first.parents:
        if parent is None or parent is form or parent.name in ("form", "body", "html"):
            break
        classes = " ".join(parent.get("class") or [])
        toggle = parent.find(["button", "a"], attrs={"data-toggle": True}) or (parent.find("button", class_=re.compile("toggle|dropdown", re.I)) if classes else None)
        if toggle is not None and _clean(toggle.get_text()):
            return _clean(toggle.get_text())[:60]
        legend = parent.find("legend")
        if legend is not None and _clean(legend.get_text()):
            return _clean(legend.get_text())[:60]
        heading = parent.find(["h2", "h3", "h4", "h5", "label"], recursive=False)
        if heading is not None and _clean(heading.get_text()) and not heading.get("for"):
            return _clean(heading.get_text())[:60]
        if "dropdown" in (parent.get("class") or []) or parent.name == "fieldset":
            break  # the dropdown wrapper (toggle + menu) or fieldset is the group's boundary
    return re.sub(r"\[\]$", "", name).replace("_", " ").replace("-", " ").strip().capitalize() or "Options"


def _option_text(node: Any, soup: Any) -> str:
    label = None
    if node.get("id"):
        label = soup.find("label", attrs={"for": node["id"]})
    if label is None:
        label = node.find_parent("label")
    text = _clean(label.get_text()) if label is not None else ""
    return text or _clean(str(node.get("value") or ""))


@dataclass
class LearnedForm:
    spec: dict[str, Any]
    score: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def summary(self) -> str:
        fields = self.spec.get("fields") or []
        return ", ".join(f"{f['label']} ({f['kind']}{', ' + str(len(f.get('options') or [])) + ' choices' if f.get('options') else ''})" for f in fields)


def _candidates(soup: Any) -> list[Any]:
    forms = list(soup.find_all("form"))
    if forms:
        return forms
    # form-less search bars: a container with a text input and a button
    found: list[Any] = []
    for node in soup.find_all("input"):
        if (node.get("type") or "text").lower() not in ("text", "search"):
            continue
        container = node
        for parent in node.parents:
            if parent is None or parent.name in ("body", "html"):
                break
            if parent.find("button") is not None or parent.find("input", attrs={"type": "submit"}) is not None:
                container = parent
                break
        if container is not node and container not in found:
            found.append(container)
    return found


def learn_form(soup: Any, url: str, family: str = "learned", version: str = "auto-1", label: str = "") -> LearnedForm | None:
    """Derive a recipe spec for the most search-like form on the page (None when there is none)."""
    best: LearnedForm | None = None
    for index, form in enumerate(_candidates(soup)):
        if _in_navigation(form) and form.name != "form":
            continue
        learned = _learn_one(soup, form, index, url, family, version, label)
        if learned is not None and (best is None or learned.score > best.score):
            best = learned
    return best


def _learn_one(soup: Any, form: Any, index: int, url: str, family: str, version: str, label: str) -> LearnedForm | None:
    form_sel = _form_selector(form, index)
    notes: list[str] = []
    score = 0
    fields: list[dict[str, Any]] = []
    steps: list[dict[str, Any]] = []
    fingerprint: list[str] = [form_sel]

    # keyword box ---------------------------------------------------------------
    text_inputs = [n for n in form.find_all("input") if (n.get("type") or "text").lower() in ("text", "search")]
    keyword_node = None
    for node in text_inputs:
        haystack = " ".join(str(node.get(a) or "") for a in ("name", "id", "placeholder", "aria-label"))
        if _KEYWORD_HINT.search(haystack):
            keyword_node = node
            break
    if keyword_node is None and text_inputs:
        keyword_node = text_inputs[0]
    if keyword_node is not None:
        kw_sel = _node_selector(keyword_node, f"{form_sel} input[type=text]")
        if not kw_sel.startswith("#"):
            kw_sel = f"{form_sel} {kw_sel}"
        placeholder = _clean(keyword_node.get("placeholder") or "")
        kw_label = placeholder or _clean(keyword_node.get("aria-label") or "")
        if keyword_node.get("id"):
            for_label = soup.find("label", attrs={"for": keyword_node["id"]})
            if for_label is not None and _clean(for_label.get_text()):
                kw_label = _clean(for_label.get_text())
        fields.append({"key": "keyword", "label": kw_label or "Keywords", "kind": "text", "placeholder": placeholder, "binds": "keyword"})
        fingerprint.append(kw_sel)
        steps.append({"fill": {"css": kw_sel}, "value": "{keyword}", "force": True})
        score += 3

    # checkbox / radio groups ----------------------------------------------------------
    groups: dict[str, list[Any]] = {}
    for node in form.find_all("input", attrs={"type": re.compile(r"^(checkbox|radio)$", re.I)}):
        name = node.get("name") or ""
        if not name:
            container = node.find_parent(class_=re.compile(r"dropdown|menu|fieldset|group|filter", re.I)) or node.find_parent("fieldset")
            name = f"#{container.get('id')}" if container is not None and container.get("id") else f"group{len(groups)}"
        groups.setdefault(name, []).append(node)
    used_keys = {"keyword"}
    for name, nodes in groups.items():
        if len(nodes) < 2:
            continue
        kind_attr = (nodes[0].get("type") or "").lower()
        label_text = _group_label(nodes, name, form)
        key = _slug(re.sub(r"\[\]$", "", name.lstrip("#")) if not name.startswith("group") else label_text)
        while key in used_keys:
            key += "_"
        used_keys.add(key)
        options = [_option_text(n, soup) for n in nodes]
        options = [o for o in options if o]
        # container of the group (dropdown menu / fieldset): part of the fingerprint and the option selector
        container = nodes[0].find_parent(id=True)
        container_sel = f"#{container['id']}" if container is not None and container is not form and container.get("id") else ""
        if name.startswith("#") or not nodes[0].get("name"):
            option_sel = f"{container_sel or form_sel} input[type={kind_attr}][value=\"{{{key}}}\"]"
        else:
            option_sel = f"input[type={kind_attr}][name={_css_attr(nodes[0]['name'])}][value=\"{{{key}}}\"]"
        if container_sel:
            fingerprint.append(container_sel)
        else:
            fingerprint.append(f"{form_sel} input[type={kind_attr}][name={_css_attr(nodes[0]['name'])}]" if nodes[0].get("name") else form_sel)
        toggle = None
        for parent in nodes[0].parents:
            if parent is None or parent is form:
                break
            toggle = parent.find(["button", "a"], attrs={"data-toggle": True})
            if toggle is not None:
                break
            if parent.name == "fieldset":
                break
        toggle_step = None
        if toggle is not None:
            toggle_sel = _node_selector(toggle, "")
            if not toggle_sel.startswith("#"):
                classes = [c for c in (toggle.get("class") or []) if c not in ("btn",)]
                toggle_sel = f"{form_sel} {toggle.name}" + "".join(f".{c}" for c in classes[:3]) if classes else ""
            if toggle_sel:
                toggle_step = {"click": {"css": toggle_sel}, "optional": True, "force": True, "timeout_ms": 2000}
        fields.append({"key": key, "label": label_text, "kind": "multiselect" if kind_attr == "checkbox" else "select", "options": options})
        if toggle_step:
            steps.append(toggle_step)
        steps.append({"check": {"css": option_sel}, "force": True})
        if toggle_step:
            steps.append(dict(toggle_step))
        score += 1

    # native selects ----------------------------------------------------------------------
    for node in form.find_all("select"):
        options = [_clean(o.get_text()) for o in node.find_all("option")]
        options = [o for o in options if o and not re.match(r"^(select|choose|all|any|--)", o, re.I)]
        if not options:
            continue
        sel = _node_selector(node, "select")
        if not sel.startswith("#"):
            sel = f"{form_sel} {sel}"
        label_node = soup.find("label", attrs={"for": node.get("id")}) if node.get("id") else None
        label_text = _clean(label_node.get_text()) if label_node is not None else (_clean(node.get("aria-label") or "") or _clean(node.get("name") or "").replace("_", " ").capitalize() or "Select")
        key = _slug(node.get("name") or node.get("id") or label_text)
        while key in used_keys:
            key += "_"
        used_keys.add(key)
        multiple = node.has_attr("multiple")
        fields.append({"key": key, "label": label_text, "kind": "multiselect" if multiple else "select", "options": options})
        fingerprint.append(sel)
        steps.append({"select": {"css": sel}, "value": f"{{{key}}}"})
        score += 1

    # submit ---------------------------------------------------------------------------
    submit = None
    for node in form.find_all(["button", "input"]):
        if node.name == "input" and (node.get("type") or "").lower() != "submit":
            continue
        text = _clean(node.get_text()) if node.name == "button" else _clean(node.get("value") or "")
        is_submit = (node.get("type") or ("submit" if node.name == "button" else "")).lower() == "submit"
        if is_submit and (_SUBMIT_HINT.search(text) or submit is None):
            submit = node
            if _SUBMIT_HINT.search(text):
                break
    if submit is None:
        for node in form.find_all("button"):
            if _SUBMIT_HINT.search(_clean(node.get_text())):
                submit = node
                break
    if submit is None:
        return None
    submit_sel = _node_selector(submit, "")
    if not submit_sel.startswith("#"):
        submit_sel = f"{form_sel} {submit.name}[type=submit]" if (submit.get("type") or "").lower() == "submit" else f"{form_sel} button"
    submit_text = _clean(submit.get_text()) if submit.name == "button" else _clean(submit.get("value") or "")
    fingerprint.append(submit_sel)
    score += 2 + (2 if _SUBMIT_HINT.search(submit_text) else 0)
    if not fields:
        return None
    if keyword_node is None and score < 4:
        return None
    steps += [
        {"click": {"css": submit_sel}, "force": True},
        {"wait": "load", "optional": True},
        {"wait": "networkidle", "optional": True},
        {"wait": {"seconds": 1}},
    ]
    steps.append({"click": {"button": "Load more"}, "repeat": "{load_more}", "optional": True, "force": True, "snapshot": True, "settle_ms": 800, "timeout_ms": 2000})
    name = label or f"Learned from {urlsplit(url).netloc}{urlsplit(url).path}"
    spec = {
        "strategy": "recipe",
        "family": family,
        "version": version,
        "since": date.today().isoformat()[:7],
        "label": f"{name} — {form_sel}, submit {submit_text or submit_sel!r}",
        "form_hint": f"{form_sel} → {submit_sel} {submit_text!r}",
        "learned": True,
        "learned_from": url,
        "fingerprint": fingerprint,
        "fields": fields,
        "steps": steps,
        "results": {"auto": True},
    }
    notes.append(f"form {form_sel}: {len(fields)} field(s), submit {submit_text or submit_sel!r}")
    return LearnedForm(spec=spec, score=score, notes=notes)


# ---------------------------------------------------------------------------
# Result list learning
# ---------------------------------------------------------------------------


def _signature(anchor: Any, depth: int = 3) -> str:
    parts = []
    node = anchor
    for _ in range(depth):
        if node is None or node.name in (None, "body", "html"):
            break
        classes = ".".join(sorted(node.get("class") or []))[:60]
        parts.append(f"{node.name}.{classes}")
        node = node.parent
    return ">".join(reversed(parts))


def _common_ancestor(nodes: list[Any]) -> Any:
    chains = []
    for node in nodes:
        chain = [node] + list(node.parents)
        chains.append(chain)
    first = chains[0]
    for candidate in first[1:]:
        if all(candidate in chain for chain in chains[1:]):
            return candidate
    return None


def _row_of(anchor: Any, container: Any) -> Any:
    row = anchor
    for parent in anchor.parents:
        if parent is container:
            return row
        row = parent
    return anchor


def _location_guess(segments: list[str]) -> str:
    for segment in segments:
        lowered = segment.lower()
        if any(word in lowered for word in _COUNTRY_WORDS) and len(segment) <= 80:
            return segment
    return ""


def learned_results(soup: Any, base_url: str, min_rows: int = 2) -> list[dict[str, str]]:
    """Rows of the dominant repeated link list on a results page (``[]`` when the page has no such list)."""
    host = urlsplit(base_url).netloc
    base_path = urlsplit(base_url).path.rstrip("/")
    groups: dict[str, list[Any]] = {}
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"].strip()
        text = _clean(anchor.get_text())
        if not text or len(text) < 3 or len(text) > 160 or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        if _in_navigation(anchor):
            continue
        absolute = urljoin(base_url, href).split("#", 1)[0]
        parts = urlsplit(absolute)
        if parts.netloc == host and not parts.query and parts.path.rstrip("/") in ("", base_path) or absolute.rstrip("/") == base_url.rstrip("/"):
            continue
        groups.setdefault(_signature(anchor), []).append(anchor)

    best_key, best_score = "", 0.0
    for key, anchors in groups.items():
        hrefs = {urljoin(base_url, a["href"]) for a in anchors}
        if len(hrefs) < min_rows:
            continue
        score = float(len(hrefs))
        job_like = sum(1 for h in hrefs if _JOB_LINK.search(h))
        score += job_like * 2
        container = _common_ancestor(anchors)
        list_like = False
        if container is not None:
            signature = " ".join([container.get("id") or ""] + list(container.get("class") or []) + [container.name])
            for node in [container] + list(container.parents)[:3]:
                if node is None or node.name in (None, "body", "html"):
                    break
                signature += " " + " ".join([node.get("id") or ""] + list(node.get("class") or []))
            list_like = bool(_LIST_CONTAINER.search(signature))
            if list_like or container.name in ("table", "tbody", "ul", "ol"):
                score += 3
        if not job_like and not list_like:
            continue  # a repeated list of links that are neither job-like nor inside a results container (e.g. a footer)
        if score > best_score:
            best_key, best_score = key, score
    if not best_key:
        return []
    anchors = groups[best_key]
    container = _common_ancestor(anchors)
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for anchor in anchors:
        link = urljoin(base_url, anchor["href"]).split("#", 1)[0]
        if link in seen:
            continue
        seen.add(link)
        title = _clean(anchor.get_text())
        row_node = _row_of(anchor, container) if container is not None else anchor
        segments = [s for s in (_clean(t) for t in row_node.stripped_strings) if s and s != title] if row_node is not anchor else []
        rows.append(
            {
                "title": title,
                "link": link,
                "company": "",
                "location": _location_guess(segments),
                "salary": "",
                "date": "",
                "description": " · ".join(segments)[:300],
                "job_type": "",
            }
        )
    return rows
