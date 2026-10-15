"""Configuration dashboard for the Job Search Dashboard.

Runs as its own Streamlit app (separate process / port / container) and edits
the JSON configuration file that the main app reads:

    streamlit run config_dashboard.py --server.port 8502

Tabs:
  1. Job sites        - which sites to search, per-site options and API keys
  2. Job preferences  - titles, industry, skills, location, salary, job types
  3. Search behaviour - timeouts, strict filtering, de-duplication
  4. Review & backup  - validation, JSON preview, import/export, reset
"""

from __future__ import annotations

import json
import os
import re
from typing import Any
from urllib.parse import quote_plus

import streamlit as st

import jobsearch_config as jc
from jobsearch_config.validate import ENV_REF_RE
from ui_help import COLUMNS, column_config, h, sec

try:  # optional: live "Test site" / URL checks need the adapters
    import jobsearch_sources as js
    from jobsearch_sources import browser
    from jobsearch_sources import searchforms as sf
    from jobsearch_sources.feeds import known_site_guidance
except Exception:  # pragma: no cover - sources are optional for the config UI
    js = None  # type: ignore[assignment]
    sf = None  # type: ignore[assignment]
    browser = None  # type: ignore[assignment]

    def known_site_guidance(url: str) -> str:  # type: ignore[misc]
        return ""

MAIN_APP_URL = os.environ.get("JOB_SEARCH_APP_URL", "http://localhost:8501")

st.set_page_config(page_title="Job Search — Configuration", page_icon="⚙", layout="wide")

st.markdown(
    """
    <style>
      :root { --ink:#1c1917; --muted:#57534e; --line:#e7e5e4; --paper:#f6f5f2; --accent:#7c2d12; --accent-soft:#fdf1ea; }
      .stApp { background: var(--paper); color: var(--ink); }
      [data-testid="stSidebar"] { background: #292524; }
      [data-testid="stSidebar"] * { color: #faf7f2; }
      [data-testid="stSidebar"] button, [data-testid="stSidebar"] button * { color: #1c1917 !important; }
      [data-testid="stSidebar"] a { color: #fdba74 !important; }
      h1, h2, h3 { letter-spacing: -0.03em; }
      .pill { display:inline-block; background:var(--accent-soft); color:var(--accent); border-radius:999px; padding:2px 9px; font-size:.75rem; font-weight:600; margin-right:4px; }
      .pill.ok { background:#e7f3f2; color:#0f6e6b; }
      .pill.off { background:#eee; color:#777; }
      .note { color: var(--muted); font-size: .92rem; }
      .summary { background:#fff; border:1px solid var(--line); border-radius:12px; padding:12px 16px; }
    </style>
    """,
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------------
# State helpers
# ---------------------------------------------------------------------------


def config_file() -> str:
    return str(jc.config_path())


def load() -> jc.AppConfig:
    """(Re)load the config from disk into session state."""
    config = jc.load_config(create=True)
    st.session_state["config"] = config
    st.session_state["config_mtime"] = jc.mtime()
    return config


def current() -> jc.AppConfig:
    config = st.session_state.get("config")
    if config is None or jc.mtime() != st.session_state.get("config_mtime"):
        # picked up external edits (CLI, hand edit, another dashboard tab)
        config = load()
    return config


def persist(config: jc.AppConfig, message: str = "Saved.") -> None:
    issues = jc.validate(config)
    if jc.has_errors(issues):
        for issue in issues:
            if issue.level == "error":
                st.error(str(issue))
        st.warning("Not saved — fix the errors above.")
        return
    jc.save_config(config)
    st.session_state["config"] = config
    st.session_state["config_mtime"] = jc.mtime()
    st.session_state["flash"] = message
    st.rerun()


def flash() -> None:
    message = st.session_state.pop("flash", None)
    if message:
        st.success(message)


def lines_to_list(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"[\n,]", text or "") if part.strip()]


def list_to_lines(values: list[str]) -> str:
    return "\n".join(values)


# ---------------------------------------------------------------------------
# Site editor
# ---------------------------------------------------------------------------


def render_option(site: jc.SiteConfig, opt: jc.OptionSpec, key_prefix: str) -> Any:
    key = f"{key_prefix}:{opt.key}"
    value = site.options.get(opt.key, opt.default)
    label = opt.label + (" *" if opt.required else "")
    if opt.kind == "select":
        choices = list(opt.choices)
        index = choices.index(value) if value in choices else 0
        return st.selectbox(label, choices, index=index, key=key, help=opt.help, format_func=lambda x: x or "(any)")
    if opt.kind == "int":
        try:
            number = int(value) if value not in (None, "") else int(opt.default or 1)
        except (TypeError, ValueError):
            number = int(opt.default or 1)
        return st.number_input(label, min_value=0, max_value=1000, value=number, step=1, key=key, help=opt.help)
    if opt.kind == "bool":
        return st.checkbox(label, value=bool(value), key=key, help=opt.help)
    if opt.kind == "secret":
        text = st.text_input(label, value=str(value or ""), key=key, help=opt.help, type="password")
        match = ENV_REF_RE.match(text or "")
        if match:
            present = bool(os.environ.get(match.group(1)))
            st.caption(f"Reads `${{{match.group(1)}}}` from the environment — {'set ✓' if present else 'NOT set in this process ✗'}")
        return text
    if opt.kind == "json":
        empty: Any = [] if isinstance(opt.default, list) else {}
        default_text = json.dumps(value if isinstance(value, (dict, list)) else (opt.default or empty), indent=2)
        text = st.text_area(label, value=default_text, key=key, help=opt.help, height=180)
        try:
            parsed = json.loads(text) if text.strip() else empty
        except json.JSONDecodeError as exc:
            st.error(f"{opt.label}: invalid JSON ({exc.msg} at line {exc.lineno}).")
            return value
        return parsed
    if opt.kind == "textarea":
        return st.text_area(label, value=str(value or ""), key=key, help=opt.help)
    return st.text_input(label, value=str(value or ""), key=key, help=opt.help)


def site_form(config: jc.AppConfig, site: jc.SiteConfig) -> None:
    spec = jc.provider(site.provider)
    if spec is None:
        st.error(f"Unknown provider '{site.provider}'. Remove this site or fix the JSON.")
        if st.button("Remove", key=f"rm-{site.id}", help=h("site_remove_unknown")):
            config.remove_site(site.id)
            persist(config, f"Removed {site.id}.")
        return

    st.markdown(f'<p class="note">{spec.description}</p>', unsafe_allow_html=True)
    meta = []
    if spec.homepage:
        meta.append(f"[API docs]({spec.homepage})")
    if spec.server_side:
        meta.append("Pushed to the site: " + ", ".join(spec.server_side))
    else:
        meta.append("Everything is filtered locally after fetching.")
    if spec.requires_key:
        meta.append("Needs credentials.")
    st.caption(" · ".join(meta))

    with st.form(f"site-{site.id}"):
        c1, c2, c3 = st.columns([1, 2, 1])
        enabled = c1.checkbox("Enabled", value=site.enabled, help=h("site_enabled"))
        name = c2.text_input("Display name", value=site.name, help=h("site_name"))
        max_results = c3.number_input("Max results", min_value=1, max_value=200, value=int(site.max_results), step=5, help=h("site_max"))
        values: dict[str, Any] = {}
        if spec.options:
            cols = st.columns(2) if len(spec.options) > 1 else [st.container()]
            for index, opt in enumerate(spec.options):
                with cols[index % len(cols)] if len(spec.options) > 1 else cols[0]:
                    values[opt.key] = render_option(site, opt, f"opt:{site.id}")
        notes = st.text_input("Notes", value=site.notes, placeholder="Why this site, rate-limit reminders, …", help=h("site_notes"))
        b1, b2 = st.columns([1, 1])
        save = b1.form_submit_button("Save site", type="primary", help=h("site_save"))
        remove = b2.form_submit_button("Remove site", help=h("site_remove"))
    if save:
        site.enabled = enabled
        site.name = name.strip() or site.id
        site.max_results = int(max_results)
        site.options = values
        site.notes = notes.strip()
        persist(config, f"Saved {site.name}.")
    if remove:
        config.remove_site(site.id)
        persist(config, f"Removed {site.id}.")

    if spec.custom:
        blocked = jc.load_registry().forbidden(str(site.options.get("url") or ""))
        if blocked is not None:
            st.error(
                f"This site cannot be searched — {blocked.host} forbids automated access (checked {blocked.checks}×, "
                f"last {blocked.updated_at}): {blocked.message}"
            )
    if js is not None:
        if st.button("Test this site now", key=f"test-{site.id}", help=h("site_test")):
            with st.spinner(f"Contacting {site.name}…"):
                jobs, outcome = js.test_site(site, config)
            if outcome.error:
                (st.error if outcome.denied else st.warning)(f"{site.name}: {outcome.error}")
                if spec.custom and spec.key == "rss":
                    st.caption("Tip: the URL must point at an RSS/Atom feed. Check the page for an RSS link, or use 'Generic JSON API' if the site has an API.")
                if outcome.note:
                    st.caption(outcome.note)
            if spec.custom:
                row = jc.load_registry().lookup(str(site.options.get("url") or ""))
                if row is not None:
                    st.caption(
                        f"Site registry — {row.host}: status **{row.status}**, active **{'yes' if row.active else 'no'}**, "
                        f"checked {row.checks}× · created {row.created_at} · updated {row.updated_at}"
                    )
                    if not row.active and site.enabled:
                        st.error("This site forbids automated access; it cannot stay enabled. Disable it or remove it.")
            else:
                st.success(f"{site.name} returned {outcome.fetched} listing(s) in {outcome.seconds}s.")
                if jobs:
                    st.dataframe(
                        [
                            {
                                "title": j.title,
                                "organization": j.organization,
                                "location": j.location,
                                "job_type": j.job_type or "?",
                                "salary": j.salary_text,
                                "published": j.published,
                            }
                            for j in jobs[:8]
                        ],
                        hide_index=True,
                        width="stretch",
                        column_config=column_config(["title", "organization", "location", "job_type", "salary", "published"], salary=st.column_config.Column("salary", help=COLUMNS["salary_text"])),
                    )
    if spec.key == "html":
        st.divider()
        search_form_panel(config, site)


# ---------------------------------------------------------------------------
# Search-form panel (mirrors the site's own search form)
# ---------------------------------------------------------------------------


def _form_options(strategy: Any, field: Any, live_options: dict[str, list[str]], saved: Any) -> list[str]:
    """Choices to show for a dropdown field: live page > saved snapshot > strategy defaults, plus saved values."""
    options = list(live_options.get(field.key) or field.options)
    chosen = saved if isinstance(saved, list) else ([saved] if saved else [])
    for value in chosen:
        if value and value not in options:
            options.append(value)  # keep a saved choice visible even if the site dropped it (the test will report it)
    return options


def render_form_fields(strategy: Any, criteria: dict[str, Any], live_options: dict[str, list[str]], key_prefix: str) -> dict[str, Any]:
    """Render the strategy's fields as Streamlit widgets laid out like the site's form; returns the criteria entered."""
    fields = strategy.fields()
    values: dict[str, Any] = {}
    text_fields = [f for f in fields if f.kind == "text"]
    others = [f for f in fields if f.kind != "text"]
    for field in text_fields:
        values[field.key] = st.text_input(
            field.label,
            value=str(criteria.get(field.key) or ""),
            placeholder=field.placeholder or field.label,
            key=f"{key_prefix}:{field.key}",
            help=field.help or f"The '{field.label}' box of the site's search form. Example: `data analyst`.",
        )
    if others:
        cols = st.columns(min(len(others), 4))
        for index, field in enumerate(others):
            with cols[index % len(cols)]:
                help_text = field.help or f"The '{field.label}' control of the site's search form; choose the values you would tick on the website."
                saved = criteria.get(field.key)
                if field.kind == "multiselect":
                    options = _form_options(strategy, field, live_options, saved)
                    default = [v for v in (saved or []) if v in options] if isinstance(saved, list) else []
                    values[field.key] = st.multiselect(field.label, options, default=default, key=f"{key_prefix}:{field.key}", help=help_text)
                elif field.kind == "select":
                    options = [""] + _form_options(strategy, field, live_options, saved)
                    index_ = options.index(saved) if saved in options else 0
                    values[field.key] = st.selectbox(field.label, options, index=index_, key=f"{key_prefix}:{field.key}", help=help_text, format_func=lambda x: x or "(any)")
                else:
                    values[field.key] = st.checkbox(field.label, value=bool(saved), key=f"{key_prefix}:{field.key}", help=help_text)
    return values


def _adopt_learned(spec: dict[str, Any], learned_key: str, widget_prefix: str, previous: Any, entered: dict[str, Any] | None = None) -> None:
    """Switch the panel to a version learned from the live page: its fields replace the previous ones on rerun.

    What the user had entered is carried over where the new form has a matching control.
    """
    st.session_state[learned_key] = spec
    learned = sf.RecipeStrategy(spec, "learned")
    carried = sf.map_criteria(entered or {}, previous.fields(), learned.fields())
    if entered and entered.get("keyword"):
        carried["keyword"] = entered["keyword"]
    st.session_state[learned_key + ":criteria"] = carried
    for field in previous.fields():
        st.session_state.pop(f"{widget_prefix}:{field.key}", None)
    st.rerun()


def _refresh_form(url: str, config: jc.AppConfig, options: dict[str, Any] | None, site_id: str, strategy: Any, live_key: str, widget_prefix: str, learned_key: str = "") -> None:
    """Read the live page's form (version + dropdown choices) and refresh the panel's widgets with it."""
    with st.spinner(f"Loading {url} to read its search form…"):
        detection = sf.detect(url, config.search, options, site_id)
    level = "error" if detection.error else ("success" if detection.ok else "warning")
    message = detection.message + (" (read in a real browser)" if detection.rendered else (" (read from the plain page)" if not detection.error else ""))
    st.session_state[live_key + ":message"] = (level, message)
    if detection.learned and learned_key:
        st.session_state[live_key] = detection.live_options
        _adopt_learned(detection.learned, learned_key, widget_prefix, strategy)
    if detection.live_options:
        st.session_state[live_key] = detection.live_options
        if learned_key and not detection.learned:
            st.session_state.pop(learned_key, None)  # a saved version matches again
        for field in strategy.fields():
            st.session_state.pop(f"{widget_prefix}:{field.key}", None)  # widgets pick up the new choices on rerun
        st.rerun()


def _show_refresh_message(live_key: str) -> None:
    stored = st.session_state.pop(live_key + ":message", None)
    if stored:
        level, message = stored
        getattr(st, level)(message)


def _keyword_mode_text(block: dict[str, Any], criteria: dict[str, Any], config: jc.AppConfig) -> str:
    """Plain-words statement of what the keyword box receives on a real search."""
    saved = str((block.get("criteria") or {}).get("keyword") or "")
    titles = ", ".join(config.preferences.titles[:3]) or "(no titles configured)"
    if str(block.get("keyword_mode") or "criteria") == "titles":
        return f"On every search the keyword box gets your preferred titles — {titles} — one search per title. A keyword typed on the Research page replaces them for that run."
    if saved:
        return f"On every search the keyword box gets the saved keyword **{saved}** (exactly what you tested). A keyword typed on the Research page replaces it for that run."
    return "On every search the keyword box is left **empty** — the site's own filters (the dropdowns) do the work. A keyword typed on the Research page is used for that run."


def _test_results(test: Any, strategy: Any) -> None:
    """Show the outcome of a Find jobs test."""
    if test.error:
        (st.error if test.denied or test.form_changed else st.warning)(f"Search test failed — {test.error}")
    elif not test.jobs:
        st.error("Search test returned no jobs. The site is not added / enabled until a test returns at least one job.")
    else:
        st.success(f"Search test passed — {test.summary()}.")
    facts = [f"strategy {test.matched or test.configured}"]
    if test.learned:
        facts.append(f"🧭 version {test.learned.get('version')} was learned from the live page — saving keeps it")
    elif test.changed:
        facts.append("⚠ the live form matched a different version than configured")
    if test.total is not None:
        facts.append(f"site reported {test.total} matching job(s)")
    if test.live_options:
        facts.append("dropdown choices refreshed from the live page")
    st.caption(" · ".join(facts) + (f" · {test.notes}" if test.notes else ""))
    for problem in test.unknown_choices:
        st.warning(f"The live form does not offer one of your choices — {problem}")
    if test.jobs:
        st.dataframe(
            [
                {
                    "title": j.title, "organization": j.organization, "location": j.location, "job_type": j.job_type or "?",
                    "salary": j.salary_text, "published": j.published, "url": j.url,
                }
                for j in test.jobs[:12]
            ],
            hide_index=True,
            width="stretch",
            column_config=column_config(
                ["title", "organization", "location", "job_type", "salary", "published", "url"],
                salary=st.column_config.Column("salary", help=COLUMNS["salary_text"]),
                url=st.column_config.LinkColumn("listing", help=COLUMNS["url"]),
            ),
        )


def search_form_panel(config: jc.AppConfig, site: jc.SiteConfig) -> None:
    """Per-site panel that mirrors the website's search form so the user can test it with real criteria."""
    if sf is None:
        return
    url = str(site.options.get("url") or "")
    strategy = sf.configured_strategy(site.options, site.id)
    known = sf.for_url(url) if url else []
    st.markdown("##### Search form", help=sec("site_search_form"))
    web_ok, web_why = jc.web_page_search_allowed(config)
    if not web_ok:
        st.error(f"{web_why} Tests and searches of web-page sites are not run; only an administrator can switch it on (Search behaviour tab).")
        return
    if strategy is None and not known:
        st.caption(
            "No search-form strategy is known for this page. If the site has a search form, run *Investigate a careers URL* "
            "to list its controls and describe it as a recipe in *Search form (JSON)*, or add a strategy class for the site."
        )
        return
    if strategy is None:
        st.info(f"A search-form strategy is available for this host: **{known[0].label}** (version {known[0].version}). Fill in the form below and press Find jobs to validate it.")
        strategy = known[0]
    passed, status_text = jc.search_form_status(site)
    versions = sf.candidates(site.options, url, site.id) or sf.versions_of(strategy.family)
    version_text = ", ".join(f"v{v.version} ({v.since or 'undated'}{', learned' if getattr(v, 'learned', False) else ''})" for v in sorted(versions, key=lambda v: v.sort_key, reverse=True))
    st.caption(
        f"Strategy **{strategy.label}** — configured version {strategy.version}"
        + (f" · known versions: {version_text}" if len(versions) > 1 else "")
        + (f" · form: {strategy.form_hint}" if strategy.form_hint else "")
    )
    if passed:
        st.caption(f"✅ {status_text}")
    elif passed is False:
        st.caption(f"⚠ {status_text} — the site cannot be enabled until a test returns jobs.")
    block = site.options.get("search_form") if isinstance(site.options.get("search_form"), dict) else {}
    criteria = dict(block.get("criteria") or (site.options.get("form_values") or {}))
    if not criteria.get("keyword") and config.preferences.titles:
        criteria["keyword"] = config.preferences.titles[0]
    live_key = f"formopts:{site.id}"
    learned_key = f"formlearned:{site.id}"
    learned_spec = st.session_state.get(learned_key)
    if learned_spec:  # a version derived from the live page (not saved yet): show *its* controls
        learned_strategy = sf.RecipeStrategy(learned_spec, site.id)
        criteria = {**sf.map_criteria(criteria, strategy.fields(), learned_strategy.fields()), "keyword": criteria.get("keyword", ""), **(st.session_state.get(learned_key + ":criteria") or {})}
        strategy = learned_strategy
        st.info(
            f"No saved version of the search form matched the live page, so version **{strategy.version}** was learned from it "
            f"({strategy.form_hint}). Fill in its form below and press Find jobs; saving keeps this version for future searches.",
            icon="🧭",
        )
    live_options = st.session_state.get(live_key) or dict(block.get("live_options") or {})
    if not browser.available(install=False)[0]:
        st.caption("Headless Chromium is not installed yet — it is downloaded automatically on the first Find jobs (about 150 MB, one minute).")

    st.caption(_keyword_mode_text(block, criteria, config))
    with st.form(f"searchform-{site.id}"):
        entered = render_form_fields(strategy, criteria, live_options, f"sf:{site.id}")
        use_titles = st.checkbox(
            "At search time, put my preferred titles in the keyword box instead (one search per title)",
            value=str(block.get("keyword_mode") or "criteria") == "titles",
            key=f"sf:{site.id}:keyword_mode",
            help=h("sf_keyword_mode"),
        )
        b1, b2 = st.columns([1, 1])
        find = b1.form_submit_button("Find jobs", type="primary", help=h("sf_find"))
        refresh = b2.form_submit_button("Refresh form from the site", help=h("sf_refresh"))
    result_key = f"formtest:{site.id}"
    if refresh:
        _refresh_form(url, config, site.options, site.id, strategy, live_key, f"sf:{site.id}", learned_key)
    _show_refresh_message(live_key)
    if find:
        with st.spinner(f"Filling in the search form on {url} and pressing Find jobs…"):
            test = sf.test_form(site, config, entered, learned=learned_spec)
        st.session_state[result_key] = test
        if test.live_options:
            st.session_state[live_key] = test.live_options
        if test.learned and test.learned is not learned_spec:
            _adopt_learned(test.learned, learned_key, f"sf:{site.id}", strategy, entered)
    test = st.session_state.get(result_key)
    if test is not None:
        _test_results(test, strategy)
        if test.ok:
            label = "Save criteria & enable site" if not site.enabled else "Save criteria"
            if test.learned:
                label += f" (keeps learned version {test.learned.get('version')})"
            if st.button(label, key=f"sf-save-{site.id}", type="primary", help=h("sf_save")):
                sf.mark_validated(site, test)
                site.options["search_form"]["keyword_mode"] = "titles" if use_titles else "criteria"
                site.enabled = True
                for key in (f"opt:{site.id}:search_form", f"opt:{site.id}:actions", f"opt:{site.id}:form_values", result_key, learned_key, learned_key + ":criteria", f"sf:{site.id}:keyword_mode"):
                    st.session_state.pop(key, None)
                persist(config, f"{site.name}: search criteria saved and validated with {len(test.jobs)} job(s); the site is enabled.")
        elif site.enabled and (test.form_changed or test.error or not test.jobs):
            st.warning("This site is enabled but its search form no longer returns jobs. Fix the criteria and test again, or disable the site.")


def add_form_site_panel(config: jc.AppConfig) -> None:
    """Add a web-page site that searches through its own form — only after a test returned jobs."""
    if sf is None:
        st.caption("Install the search adapters (requirements.txt) to add form-driven sites.")
        return
    web_ok, web_why = jc.web_page_search_allowed(config)
    if not web_ok:
        st.error(f"{web_why} Web-page sites cannot be added or tested; only an administrator can switch it on (Search behaviour tab).")
        return
    families = sf.families()
    labels = {"": "Detect from the URL (by host)"}
    for family, versions in families.items():
        labels[family] = f"{versions[0].label} ({family}, {len(versions)} version(s))"
    c1, c2 = st.columns([1, 1])

    def _strategy_chosen() -> None:  # prefill the page address with the strategy's known form page
        chosen = sf.get(st.session_state.get("add-form-strategy") or "")
        if chosen is not None and chosen.start_url and not (st.session_state.get("add-form-url") or "").strip():
            st.session_state["add-form-url"] = chosen.start_url

    family = c1.selectbox("Site strategy", list(labels), format_func=lambda k: labels[k], key="add-form-strategy", help=h("add_form_strategy"), on_change=_strategy_chosen)
    url = c2.text_input("Page with the search form", placeholder="https://www.yahooinc.com/careers/search.html", key="add-form-url", help=h("add_form_url"))
    c3, c4 = st.columns(2)
    site_id = c3.text_input("Site id", placeholder="yahoo-careers", key="add-form-id", help=h("add_form_id"))
    name = c4.text_input("Display name", placeholder="Yahoo careers (search form)", key="add-form-name", help=h("add_form_name"))
    url = url.strip()
    blocked_text = _blocked_message(url)
    if blocked_text:
        st.error(blocked_text)
        return
    strategies = sf.versions_of(family) if family else (sf.for_url(url) if url else [])
    if not strategies:
        st.info("Paste the page address of a site with a known strategy (e.g. yahooinc.com), or pick a strategy explicitly. For other sites, run Investigate and describe the form as a recipe.")
        return
    strategy = strategies[0]
    configured = strategy
    st.caption(f"Strategy **{strategy.label}** · versions: " + ", ".join(f"v{s.version} ({s.since or 'undated'})" for s in strategies) + (f" · form: {strategy.form_hint}" if strategy.form_hint else ""))
    live_key = "formopts:new"
    learned_key = "formlearned:new"
    learned_spec = st.session_state.get(learned_key)
    if learned_spec and learned_spec.get("learned_from") == url:
        strategy = sf.RecipeStrategy(learned_spec, site_id.strip().lower() or "new-site")
        st.info(
            f"No known version of the search form matched this page, so version **{strategy.version}** was learned from it "
            f"({strategy.form_hint}). Fill in its form below and press Find jobs; adding the site keeps this version.",
            icon="🧭",
        )
    else:
        learned_spec = None
    live_options = st.session_state.get(live_key) or {}
    criteria = {"keyword": config.preferences.titles[0] if config.preferences.titles else ""}
    if learned_spec:
        criteria.update(st.session_state.get(learned_key + ":criteria") or {})
    if not browser.available(install=False)[0]:
        st.caption("Headless Chromium is not installed yet — it is downloaded automatically on the first Find jobs (about 150 MB, one minute).")
    with st.form("searchform-new"):
        entered = render_form_fields(strategy, criteria, live_options, "sf:new")
        use_titles = st.checkbox(
            "At search time, put my preferred titles in the keyword box instead (one search per title)",
            value=False,
            key="sf:new:keyword_mode",
            help=h("sf_keyword_mode"),
        )
        b1, b2 = st.columns([1, 1])
        find = b1.form_submit_button("Find jobs", type="primary", help=h("sf_find"))
        refresh = b2.form_submit_button("Refresh form from the site", help=h("sf_refresh"))
    if (find or refresh) and not url.lower().startswith(("http://", "https://")):
        st.error("The page address must start with http:// or https://.")
        return
    if refresh:
        _refresh_form(url, config, {"search_form": {"strategy": configured.family}} if family else None, "", strategy, live_key, "sf:new", learned_key)
    _show_refresh_message(live_key)
    trial = jc.SiteConfig(id=site_id.strip().lower() or "new-site", provider="html", name=name.strip() or "New site", enabled=False, options=sf.form_site_options(configured, url, {}))
    if find:
        with st.spinner(f"Filling in the search form on {url} and pressing Find jobs…"):
            test = sf.test_form(trial, config, entered, learned=learned_spec)
        st.session_state["formtest:new"] = (url, test)
        if test.live_options:
            st.session_state[live_key] = test.live_options
        if test.learned and test.learned is not learned_spec:
            _adopt_learned(test.learned, learned_key, "sf:new", strategy, entered)
    stored = st.session_state.get("formtest:new")
    if not stored or stored[0] != url:
        return
    test = stored[1]
    _test_results(test, strategy)
    if not test.ok:
        st.caption("Not added: a web-form site joins the job search list only when its test returns jobs.")
        return
    if st.button("Add site (validated)", key="add-form-btn", type="primary", help=h("add_form_create")):
        sid = site_id.strip().lower()
        if not re.match(r"^[a-z0-9][a-z0-9_-]{0,39}$", sid):
            st.error("Site id must be lowercase letters, digits, '-' or '_'.")
        elif config.get_site(sid):
            st.error("That site id already exists.")
        elif jc.load_registry().forbidden(url) is not None:
            st.error(f"Not saved — {jc.load_registry().forbidden(url).host} forbids automated access (site registry).")
        else:
            site = jc.SiteConfig(id=sid, provider="html", name=name.strip() or sid, enabled=True, options=sf.form_site_options(configured, url, {}))
            sf.mark_validated(site, test)
            site.options["search_form"]["keyword_mode"] = "titles" if use_titles else "criteria"
            config.upsert_site(site)
            st.session_state.pop("formtest:new", None)
            st.session_state.pop(learned_key, None)
            st.session_state.pop(learned_key + ":criteria", None)
            persist(config, f"Added {site.name} — validated with {len(test.jobs)} job(s) and enabled. Searches will fill in its form with these criteria.")


def compliance_panel(config: jc.AppConfig, registry: Any) -> None:
    """Daily access-policy scan of the configured sites: status, run now, last results."""
    st.subheader("Compliance scan", help=sec("cfg_compliance"))
    stamp, summary = js.compliance.last_scan(registry) if js is not None else ("", "")
    hours = int(config.search.compliance_scan_hours or 0)
    st.caption(
        (f"Last scan: **{stamp}** — {summary}" if stamp else "No scan has run yet.")
        + (f" · runs automatically every {hours} h from the main dashboard" if hours else " · automatic scans are off (compliance_scan_hours = 0)")
        + " · cron / Task Scheduler: `python -m jobsearch_sources compliance-scan`"
    )
    if js is not None and st.button("Scan all sites now", key="compliance-scan-now", help=h("compliance_scan_now")):
        with st.spinner("Re-checking every custom and careers-platform site against robots.txt, HTTP access and the registry policy…"):
            report = js.compliance.scan(config, registry)
        st.session_state["compliance-report"] = report.to_dict()
        if report.config_saved:
            st.session_state.pop("config", None)
            st.session_state["flash"] = f"Compliance scan: {report.summary()}"
            st.rerun()
    data = st.session_state.get("compliance-report")
    if data:
        (st.success if not any(r["compliant"] is False for r in data["results"]) else st.error)(f"{data['checked_at']}: {data['summary']}")
        st.dataframe(
            [
                {"site": r["name"], "host": r["host"], "compliant": bool(r["compliant"]), "reason": r["reason"], "disabled": r["disabled"], "message": r["message"]}
                for r in data["results"]
            ],
            hide_index=True,
            width="stretch",
            column_config=column_config(
                ["site", "host", "compliant", "reason", "disabled", "message"],
                compliant=st.column_config.CheckboxColumn(disabled=True, help=COLUMNS["compliant"]),
                disabled=st.column_config.CheckboxColumn(disabled=True, help=COLUMNS["disabled"]),
            ),
        )


def _blocked_message(url: str) -> str:
    """Refusal text when the URL's host forbids automated access ("" when it does not)."""
    blocked = jc.load_registry().forbidden(url) if url else None
    if blocked is None:
        return ""
    why = "by its terms of use" if blocked.policy_block else {"robots": "by robots.txt", "http": "(it answers scripts with HTTP 401/403)"}.get(blocked.reason, "")
    return f"{blocked.host} prohibits automated access {why} — {blocked.message} The site cannot be added."


def investigate_panel(config: jc.AppConfig) -> None:
    st.subheader("Investigate a careers URL", help=sec("cfg_investigate"))
    st.markdown(
        '<p class="note">Paste any careers page. The app checks whether robots allow it, whether the host answers scripts, which '
        "platform powers it (those have public job APIs), what the page contains, and which search-form controls exist — "
        "then suggests the right site type, ready to add.</p>",
        unsafe_allow_html=True,
    )
    c1, c2, c3 = st.columns([3, 1, 1])
    url = c1.text_input("Careers URL", placeholder="https://www.yahooinc.com/careers/", key="inv-url", help=h("inv_url"))
    render = c2.checkbox("Render in browser", value=False, key="inv-render", help=h("inv_render"))
    c3.write("")
    c3.write("")
    if c3.button("Investigate", key="inv-run", disabled=js is None or not url.strip(), help=h("inv_run")):
        with st.spinner("Checking robots.txt, fetching the page…"):
            st.session_state["investigation"] = js.investigate(url.strip(), config.search, render=render).to_dict()
    data = st.session_state.get("investigation")
    if not data or data.get("url") != url.strip():
        return
    report = data
    verdict = report["verdict"]
    (st.success if verdict == "crawlable" else st.error)(f"**{verdict}** — {report['summary']}")
    facts = [
        f"robots.txt: {'allowed' if report['robots_allowed'] else 'disallowed'}" + (f" (crawl-delay {report['crawl_delay']}s)" if report.get("crawl_delay") else ""),
        f"reachable: {'yes' if report['reachable'] else 'no'}" if report["reachable"] is not None else "",
        f"platform: {report['platform_label'] or 'none detected'}",
        f"JobPosting objects: {report['jsonld_postings']}",
        f"job links: {report['job_links']}",
        f"feeds: {', '.join(report['feeds']) or 'none'}",
        f"JavaScript-rendered: {'yes' if report['js_rendered'] else 'no'}" + (" (inspected in browser)" if report["rendered"] else ""),
    ]
    st.caption(" · ".join(f for f in facts if f))
    if report.get("registry_status"):
        st.caption(f"Site registry: {report['registry_status']} — {report['registry_message']}")
    if report["form_controls"]:
        with st.expander(f"Search form controls ({len(report['form_controls'])}) — use these labels in a search recipe", expanded=True):
            st.dataframe(
                [{"kind": c["kind"], "label": c["label"], "options": ", ".join(c["options"][:10]), "css hint": c["selector"]} for c in report["form_controls"]],
                hide_index=True,
                width="stretch",
                column_config=column_config(["kind", "label", "options", "css hint"]),
            )
            st.caption(
                "Recipe targets by visible text: `{\"fill\": {\"placeholder\": \"Key words\"}, \"value\": \"{keyword}\"}`, "
                "`{\"click\": {\"text\": \"Select countries\"}}`, `{\"click\": {\"option\": \"{country}\"}}`, `{\"click\": {\"button\": \"Find jobs\"}}`."
            )
    if report.get("form_strategies"):
        matched = report.get("form_strategy_matched")
        (st.success if matched else st.warning)(
            f"Search-form strategies registered for this site: {', '.join(report['form_strategies'])} — "
            + (f"the live page matches **{matched}**." if matched else "none matches this page (redesigned form, or the form lives on another page).")
        )
    blocked_text = _blocked_message(url.strip())
    if blocked_text:
        st.error(blocked_text)
    web_ok, web_why = jc.web_page_search_allowed(config)
    suggestion = report.get("suggested_site")
    if suggestion and blocked_text:
        st.caption("No site is suggested for a host that forbids automated access.")
        suggestion = None
    if suggestion and suggestion.get("provider") == "html" and not web_ok:
        st.warning(f"The suggested web-page site cannot be added: {web_why}")
        suggestion = None
    if suggestion:
        with st.expander("Suggested site configuration", expanded=True):
            st.code(json.dumps(suggestion, indent=2), language="json")
            if config.get_site(suggestion["id"]):
                st.info(f"A site with id `{suggestion['id']}` already exists.")
            elif st.button("Add suggested site", key="inv-add", type="primary", help=h("inv_add")):
                config.upsert_site(jc.SiteConfig.from_dict(suggestion))
                persist(config, f"Added {suggestion['name']}. Open its card to adjust filters, then test it.")
    form_suggestion = report.get("suggested_form_site")
    if form_suggestion and (blocked_text or not web_ok):
        form_suggestion = None
    if form_suggestion and form_suggestion != suggestion:
        with st.expander("Suggested search-form site (fills in the page's own form on every search)", expanded=True):
            st.code(json.dumps({k: v for k, v in form_suggestion.items() if k != "options"} | {"options": {k: v for k, v in form_suggestion["options"].items() if v not in ("", [], {}, None)}}, indent=2), language="json")
            if config.get_site(form_suggestion["id"]):
                st.info(f"A site with id `{form_suggestion['id']}` already exists.")
            elif st.button("Add search-form site (disabled until tested)", key="inv-add-form", help=h("inv_add_form")):
                config.upsert_site(jc.SiteConfig.from_dict(form_suggestion))
                persist(config, f"Added {form_suggestion['name']} (disabled). Open its card, fill in the Search form panel and press Find jobs to validate and enable it.")


def add_site_panel(config: jc.AppConfig) -> None:
    st.subheader("Add a site", help=sec("cfg_add_site"))
    existing = {s.provider for s in config.sites}
    tab_builtin, tab_form, tab_custom = st.tabs(["From the catalog", "Web page with a search form", "Custom feed, API"])

    with tab_form:
        st.markdown(
            '<p class="note">For sites whose jobs are found through their own search form (keywords, category / country / brand '
            "dropdowns, a <em>Find jobs</em> button). The same form is shown here; fill it in as you would on the website and "
            "press <em>Find jobs</em>. The site is added to the job search list only when the test returns jobs, and every "
            "later search fills in the form with these criteria.</p>",
            unsafe_allow_html=True,
        )
        add_form_site_panel(config)

    with tab_builtin:
        candidates = [spec for spec in jc.builtin_providers() if spec.key not in existing]
        if not candidates:
            st.caption("All built-in providers are already configured. Enable them above.")
        else:
            spec = st.selectbox(
                "Provider",
                candidates,
                format_func=lambda s: f"{s.label} — {'needs key' if s.requires_key else 'no key'}",
                key="add-builtin",
                help=h("add_builtin_provider"),
            )
            st.caption(spec.description)
            if st.button("Add to my sites", key="add-builtin-btn", help=h("add_builtin")):
                entry = dict(spec.default_site or {})
                site = jc.SiteConfig(
                    id=entry.get("id", spec.key),
                    provider=spec.key,
                    name=entry.get("name", spec.label),
                    enabled=True,
                    max_results=int(entry.get("max_results", 20)),
                    options=jc.default_options(spec.key),
                )
                config.upsert_site(site)
                persist(config, f"Added {site.name}. Review its options below, then enable it.")

    with tab_custom:
        feed_or_api = [spec for spec in jc.custom_providers() if spec.key in ("rss", "json")]
        spec = st.selectbox("Type", feed_or_api, format_func=lambda s: s.label, key="add-custom-kind", help=h("add_custom_type"))
        st.caption(spec.description)
        st.info(
            "Paste the address of an **RSS/Atom feed or a JSON API**. A careers page that advertises a feed is switched to "
            "that feed automatically. For a page whose jobs are behind a search form use the *Web page with a search form* "
            "tab; other web pages and company careers platforms (Workday, Greenhouse, …) are added through *Investigate a "
            "careers URL* above. Indeed, Monster, LinkedIn, Glassdoor and Craigslist prohibit automated access and block "
            "scripts; Adzuna carries much of the same inventory.",
            icon="ℹ️",
        )
        c1, c2 = st.columns(2)
        site_id = c1.text_input("Site id", placeholder="acme-careers", key="add-custom-id", help=h("add_custom_id"))
        name = c2.text_input("Display name", placeholder="Acme careers feed", key="add-custom-name", help=h("add_custom_name"))
        url = st.text_input("URL", placeholder="https://example.com/jobs.rss?q={keyword}", key="add-custom-url", help=h("add_custom_url"))
        guidance = known_site_guidance(url) if url.strip() else ""
        if guidance:
            st.warning(guidance)
        skip_check = st.checkbox(
            "Skip the URL check (not recommended)",
            value=False,
            key="add-custom-skip",
            help=h("add_custom_skip"),
        )
        if st.button("Create site", key="add-custom-btn", help=h("add_custom_create")):
            sid = site_id.strip().lower()
            clean_url = url.strip()
            if not re.match(r"^[a-z0-9][a-z0-9_-]{0,39}$", sid):
                st.error("Site id must be lowercase letters, digits, '-' or '_'.")
            elif config.get_site(sid):
                st.error("That site id already exists.")
            elif not clean_url.lower().startswith(("http://", "https://")):
                st.error("URL must start with http:// or https://.")
            else:
                message = ""
                registry = jc.load_registry()
                if skip_check and registry.forbidden(clean_url) is not None:
                    blocked = registry.forbidden(clean_url)
                    st.error(f"Not saved — {blocked.host} forbids automated access (site registry, {blocked.updated_at}): {blocked.message}")
                    st.stop()
                if not skip_check and js is not None:
                    probe_url = (
                        clean_url.replace("{keyword}", quote_plus(config.preferences.titles[0] if config.preferences.titles else "analyst"))
                        .replace("{location}", "")
                        .replace("{limit}", "10")
                        .replace("{page}", "1")
                    )
                    with st.spinner("Checking the URL…"):
                        result = js.probe(probe_url, config.search, expect="json" if spec.key == "json" else "feed")
                    if result.status == "html" and result.feeds and spec.key == "rss":
                        clean_url = result.feeds[0]
                        message = f" The page advertised a feed, so the site uses {clean_url} instead."
                    elif not result.ok:
                        st.error(f"Not saved — {result.message}")
                        if result.registry_status == "forbidden":
                            st.caption("Recorded in the site registry as forbidden; the site cannot be added until a re-check succeeds.")
                        st.stop()
                    else:
                        message = f" Check: {result.message}"
                options = jc.default_options(spec.key)
                options["url"] = clean_url
                config.upsert_site(jc.SiteConfig(id=sid, provider=spec.key, name=name.strip() or sid, enabled=True, options=options))
                persist(config, f"Created {name or sid}.{message} Adjust its options below if needed.")


def page_sites(config: jc.AppConfig) -> None:
    st.header("Job sites", help=sec("cfg_sites"))
    st.markdown(
        '<p class="note">Tick the sites you want the main app to query. Built-in providers have ready-made adapters; '
        "custom RSS/JSON sites let you add any board that exposes a feed. Secrets may be written as "
        "<code>${ENV_VAR}</code> so the file stays shareable.</p>",
        unsafe_allow_html=True,
    )
    enabled = config.enabled_sites()
    st.markdown(
        " ".join(
            f'<span class="pill {"ok" if s.enabled else "off"}">{s.name}</span>' for s in config.sites
        )
        or '<span class="pill off">no sites</span>',
        unsafe_allow_html=True,
    )
    st.caption(f"{len(enabled)} of {len(config.sites)} sites enabled.")

    quick = st.multiselect(
        "Quick toggle — enabled sites",
        [s.id for s in config.sites],
        default=[s.id for s in enabled],
        format_func=lambda sid: config.get_site(sid).name if config.get_site(sid) else sid,
        help=h("cfg_quick_toggle"),
    )
    if st.button("Apply quick toggle", help=h("cfg_quick_apply")):
        for site in config.sites:
            site.enabled = site.id in quick
        persist(config, "Updated enabled sites.")

    st.divider()
    for site in list(config.sites):
        spec = jc.provider(site.provider)
        provider_label = spec.label if spec else site.provider
        label = f"{'🟢' if site.enabled else '⚪'} {site.name}" + (f"  ·  {provider_label}" if provider_label != site.name else "")
        with st.expander(label, expanded=False):
            site_form(config, site)

    st.divider()
    investigate_panel(config)
    st.divider()
    add_site_panel(config)


# ---------------------------------------------------------------------------
# Preferences editor
# ---------------------------------------------------------------------------


def page_preferences(config: jc.AppConfig) -> None:
    st.header("Job preferences", help=sec("cfg_prefs"))
    st.markdown(
        '<p class="note">Describe the jobs you want. Titles and skills are sent to sites that support keyword search and '
        "used to rank every result; location, salary, job type and workplace are applied as filters.</p>",
        unsafe_allow_html=True,
    )
    prefs = config.preferences
    with st.form("prefs"):
        st.subheader("Role", help=sec("pref_role"))
        c1, c2 = st.columns(2)
        titles = c1.multiselect(
            "Target titles / keywords",
            options=sorted(set(prefs.titles)),
            default=prefs.titles,
            accept_new_options=True,
            help=h("pref_titles"),
        )
        industries = c2.multiselect(
            "Industries",
            options=sorted(set(jc.INDUSTRIES) | set(prefs.industries)),
            default=prefs.industries,
            accept_new_options=True,
            help=h("pref_industries"),
        )
        c3, c4 = st.columns([2, 1])
        skills = c3.multiselect(
            "Skills",
            options=sorted(set(prefs.skills)),
            default=prefs.skills,
            accept_new_options=True,
            help=h("pref_skills"),
        )
        min_skills = c4.number_input(
            "Require at least N skills",
            min_value=0,
            max_value=20,
            value=int(prefs.min_skill_matches),
            help=h("pref_min_skills"),
        )
        exclude = st.multiselect(
            "Exclude keywords",
            options=sorted(set(prefs.exclude_keywords)),
            default=prefs.exclude_keywords,
            accept_new_options=True,
            help=h("pref_exclude"),
        )

        st.subheader("Location", help=sec("pref_location"))
        c5, c6 = st.columns([2, 1])
        locations = c5.multiselect(
            "Preferred locations",
            options=sorted(set(prefs.locations)),
            default=prefs.locations,
            accept_new_options=True,
            help=h("pref_locations"),
        )
        workplaces = c6.multiselect(
            "Workplace",
            options=list(jc.WORKPLACES),
            default=prefs.workplaces,
            format_func=lambda k: jc.WORKPLACES[k],
            help=h("pref_workplaces"),
        )

        st.subheader("Employment", help=sec("pref_employment"))
        c7, c8 = st.columns([2, 1])
        job_types = c7.multiselect(
            "Job types",
            options=list(jc.JOB_TYPES),
            default=prefs.job_types,
            format_func=lambda k: jc.JOB_TYPES[k],
            help=h("pref_job_types"),
        )
        schedules = c8.multiselect(
            "Schedule",
            options=list(jc.SCHEDULES),
            default=prefs.schedules,
            format_func=lambda k: jc.SCHEDULES[k],
            help=h("pref_schedules"),
        )
        include_unknown = st.checkbox(
            "Keep listings that don't state a job type",
            value=prefs.include_unknown_job_type,
            help=h("pref_include_unknown"),
        )

        st.subheader("Salary", help=sec("pref_salary"))
        s1, s2, s3, s4, s5 = st.columns([1, 1, 1, 1, 1.4])
        minimum = s1.number_input("Minimum", min_value=0, value=int(prefs.salary.minimum or 0), step=5000, help=h("pref_salary_min"))
        maximum = s2.number_input("Maximum", min_value=0, value=int(prefs.salary.maximum or 0), step=5000, help=h("pref_salary_max"))
        currency = s3.selectbox(
            "Currency",
            options=sorted(set(jc.CURRENCIES) | {prefs.salary.currency}),
            index=sorted(set(jc.CURRENCIES) | {prefs.salary.currency}).index(prefs.salary.currency),
            help=h("pref_salary_currency"),
        )
        period = s4.selectbox(
            "Period",
            options=list(jc.SALARY_PERIODS),
            index=list(jc.SALARY_PERIODS).index(prefs.salary.period),
            format_func=lambda k: jc.SALARY_PERIODS[k],
            help=h("pref_salary_period"),
        )
        include_unlisted = s5.checkbox(
            "Keep listings without pay info",
            value=prefs.salary.include_unlisted,
            help=h("pref_include_unlisted"),
        )

        st.subheader("Freshness", help=sec("pref_freshness"))
        posted = st.number_input(
            "Only listings posted within the last N days",
            min_value=0,
            max_value=365,
            value=int(prefs.posted_within_days or 0),
            help=h("pref_posted_within"),
        )

        if st.form_submit_button("Save preferences", type="primary", help=h("pref_save")):
            config.preferences = jc.JobPreferences(
                titles=titles,
                industries=industries,
                skills=skills,
                min_skill_matches=int(min_skills),
                exclude_keywords=exclude,
                locations=locations,
                workplaces=workplaces,
                job_types=job_types,
                schedules=schedules,
                include_unknown_job_type=include_unknown,
                salary=jc.SalaryRange(
                    minimum=int(minimum) or None,
                    maximum=int(maximum) or None,
                    currency=currency,
                    period=period,
                    include_unlisted=include_unlisted,
                ),
                posted_within_days=int(posted) or None,
            )
            persist(config, "Preferences saved.")

    st.subheader("Effective filter summary", help=sec("pref_summary"))
    st.markdown(f'<div class="summary">{summary_html(config)}</div>', unsafe_allow_html=True)


def summary_html(config: jc.AppConfig) -> str:
    p = config.preferences
    rows = [
        ("Titles", ", ".join(p.titles) or "—"),
        ("Industries", ", ".join(p.industries) or "any"),
        ("Skills", ", ".join(p.skills) or "—" + (f" (min {p.min_skill_matches})" if p.min_skill_matches else "")),
        ("Exclude", ", ".join(p.exclude_keywords) or "—"),
        ("Locations", ", ".join(p.locations) or "anywhere"),
        ("Workplace", ", ".join(jc.WORKPLACES[w] for w in p.workplaces)),
        ("Job types", ", ".join(jc.JOB_TYPES[t] for t in p.job_types) + ("" if p.include_unknown_job_type else " (unknown dropped)")),
        ("Schedule", ", ".join(jc.SCHEDULES[s] for s in p.schedules)),
        ("Salary", p.salary.describe() + ("" if p.salary.include_unlisted or not p.salary.is_set else " (unlisted dropped)")),
        ("Posted within", f"{p.posted_within_days} days" if p.posted_within_days else "any time"),
        ("Sites", ", ".join(s.name for s in config.enabled_sites()) or "none enabled"),
    ]
    return "<br>".join(f"<b>{label}:</b> {value}" for label, value in rows)


# ---------------------------------------------------------------------------
# Site registry
# ---------------------------------------------------------------------------


def page_registry(config: jc.AppConfig) -> None:
    st.header("Site registry", help=sec("cfg_registry"))
    st.markdown(
        '<p class="note">What the app has learned about each job-site host. Rows are updated every time a site is tested, '
        "checked on creation, or searched. Hosts that forbid automated access (HTTP 401/403, robots.txt, known terms) are "
        "<b>inactive</b>: they cannot be added or enabled, and are skipped with the saved warning. "
        "Re-check a host to refresh its row from a live request.</p>",
        unsafe_allow_html=True,
    )
    registry = jc.load_registry()
    rows = registry.list()
    if not rows:
        st.info("The registry is empty.")
    else:
        st.dataframe(
            [
                {
                    "host": r.host,
                    "active": r.active,
                    "status": r.status,
                    "reason": r.reason,
                    "checks": r.checks,
                    "created": r.created_at,
                    "updated": r.updated_at,
                    "source": r.source,
                    "last HTTP": r.last_status_code or "",
                    "last URL": r.last_url,
                    "message": r.message,
                }
                for r in rows
            ],
            hide_index=True,
            width="stretch",
            column_config=column_config(
                ["host", "active", "status", "reason", "checks", "created", "updated", "source", "last HTTP", "last URL", "message"],
                active=st.column_config.CheckboxColumn(disabled=True, help=COLUMNS["active"]),
                source=st.column_config.Column("source", help="Who wrote the row: builtin seed, probe (Test / URL check), search, scan (compliance), or manual."),
            ),
        )
    c1, c2 = st.columns([2, 1])
    with c1:
        host = (
            st.selectbox(
                "Host",
                [r.host for r in rows],
                format_func=lambda name: f"{name} ({'active' if registry.rows[name].active else 'inactive' + (' — terms' if registry.rows[name].policy_block else '')})",
                help=h("reg_host"),
            )
            if rows
            else ""
        )
        url = st.text_input(
            "URL to check",
            value=(registry.rows[host].last_url if host else "") or (f"https://{host}/" if host else ""),
            key="registry-url",
            help=h("reg_url"),
        )
    with c2:
        st.write("")
        st.write("")
        recheck = st.button("Re-check this host", disabled=not host or js is None, help=h("reg_recheck"))
        remove = st.button("Remove row", disabled=not host, help=h("reg_remove"))
    if recheck and host:
        with st.spinner(f"Checking {url}…"):
            result = js.probe(url, config.search, expect="html")
        row = jc.load_registry().lookup(url)
        (st.success if result.registry_status in ("ok", "empty") else st.error)(
            f"{result.message} → registry: status {row.status}, active {'yes' if row.active else 'no'}, checked {row.checks}× (updated {row.updated_at})."
        )
    if remove and host:
        if registry.rows[host].policy_block:
            st.error(f"{host} is blocked by its terms of use; only an administrator can lift that (override below).")
        else:
            registry.remove(host)
            st.session_state["flash"] = f"Removed {host} from the registry."
            st.rerun()
    if host and registry.rows[host].policy_block:
        st.warning(f"**{host}** prohibits automated access by its terms of use — {registry.rows[host].message} Live checks never lift this block.")

    st.subheader("Administrator override", help=sec("reg_override"))
    st.caption("Lift a terms-based block (if the site's terms changed) or impose one. Requires the administrator token (`JOB_SEARCH_ADMIN_TOKEN`).")
    o1, o2, o3 = st.columns([2, 1, 1])
    token = o1.text_input("Administrator token", type="password", key="reg-admin-token", help=h("admin_token"))
    lift = o2.button("Lift the block", disabled=not host or registry.rows.get(host) is None or registry.rows[host].active, help=h("reg_override_lift"))
    impose = o3.button("Block by terms", disabled=not host or registry.rows.get(host) is None or not registry.rows[host].active, help=h("reg_override_block"))
    if (lift or impose) and host:
        if not jc.admin_configured():
            st.error(f"No administrator token is configured: set {jc.ENV_ADMIN_TOKEN} in the environment of this dashboard.")
        elif not jc.verify_token(token):
            st.error("The administrator token is wrong.")
        elif lift:
            registry.set_active(host, True, message="Block lifted by the administrator.")
            st.session_state["flash"] = f"{host}: block lifted by the administrator."
            st.rerun()
        else:
            registry.set_active(host, False, message=f"{host} prohibits automated access by its terms of use (recorded by the administrator).", reason="terms")
            st.session_state["flash"] = f"{host}: blocked by terms (administrator)."
            st.rerun()

    compliance_panel(config, registry)
    with st.expander("Maintenance"):
        m1, m2 = st.columns(2)
        if m1.button("Re-check all hosts", disabled=js is None or not rows, help=h("reg_recheck_all")):
            progress = st.progress(0.0)
            for index, r in enumerate(rows, start=1):
                js.probe(r.last_url or f"https://{r.host}/", config.search, expect="html")
                progress.progress(index / len(rows))
            st.session_state["flash"] = f"Re-checked {len(rows)} host(s)."
            st.rerun()
        if m2.button("Add missing built-in entries", help=h("reg_seed")):
            added = registry.seed()
            registry.save()
            st.session_state["flash"] = f"Added {added} built-in host(s)."
            st.rerun()
        st.caption(f"File: {jc.registry_path()}")
        st.download_button(
            "Download site_registry.json",
            json.dumps({"sites": [r.to_dict() for r in rows]}, indent=2).encode("utf-8"),
            file_name="site_registry.json",
            mime="application/json",
            help=h("reg_download"),
        )


# ---------------------------------------------------------------------------
# Search behaviour
# ---------------------------------------------------------------------------


def page_search(config: jc.AppConfig) -> None:
    st.header("Search behaviour", help=sec("cfg_search"))
    s = config.search
    with st.form("search-settings"):
        c1, c2 = st.columns(2)
        timeout = c1.number_input("Per-site timeout (seconds)", min_value=3, max_value=120, value=int(s.timeout_seconds), help=h("search_timeout"))
        user_agent = c2.text_input("User-Agent header", value=s.user_agent, help=h("search_user_agent"))
        strict = st.checkbox("Strict filtering (hide listings that fail a filter)", value=s.strict_filtering, help=h("search_strict"))
        dedupe = st.checkbox("De-duplicate by listing URL across sites", value=s.dedupe_by_url, help=h("search_dedupe"))
        scan_hours = st.number_input("Compliance scan interval (hours, 0 = off)", min_value=0, max_value=720, value=int(s.compliance_scan_hours), help=h("search_scan_hours"))
        if st.form_submit_button("Save search behaviour", type="primary", help=h("search_save")):
            config.search = jc.SearchSettings(
                timeout_seconds=int(timeout), strict_filtering=strict, dedupe_by_url=dedupe, user_agent=user_agent,
                compliance_scan_hours=int(scan_hours),
                web_page_search=s.web_page_search, web_page_search_signature=s.web_page_search_signature, web_page_search_changed_at=s.web_page_search_changed_at,
            )
            persist(config, "Search behaviour saved.")

    st.subheader("Web-page based search — administrator setting", help=sec("cfg_admin"))
    allowed, why = jc.web_page_search_allowed(config)
    (st.success if allowed else st.error)(why)
    st.markdown(
        '<p class="note">Reading web pages, driving search forms and headless-browser rendering are switched on or off here for the '
        "whole app. The setting is signed with the administrator token; it can only be changed with that token, and a value edited "
        "without it is treated as <b>off</b>. Built-in API providers and feeds are not affected.</p>",
        unsafe_allow_html=True,
    )
    if not jc.admin_configured():
        st.info(f"No administrator token is configured in this process. Set `{jc.ENV_ADMIN_TOKEN}` (e.g. in `.env`) for the person allowed to change this setting, then restart the configuration dashboard.", icon="🔐")
    with st.form("admin-web-search"):
        a1, a2 = st.columns([2, 1])
        token = a1.text_input("Administrator token", type="password", help=h("admin_token"))
        enable = a2.checkbox("Allow web-page based search", value=bool(s.web_page_search), help=h("admin_web_search_toggle"))
        if st.form_submit_button("Apply as administrator", type="primary", help=h("admin_web_search_save"), disabled=not jc.admin_configured()):
            try:
                jc.set_web_page_search(config, enable, token)
            except jc.AdminRequired as exc:
                st.error(f"Refused — {exc}")
            else:
                persist(config, f"Web-page based search switched {'ON' if enable else 'OFF'} by the administrator.")


# ---------------------------------------------------------------------------
# Review / import / export
# ---------------------------------------------------------------------------


def page_review(config: jc.AppConfig) -> None:
    st.header("Review & backup", help=sec("cfg_review"))
    issues = jc.validate(config)
    if not issues:
        st.success("Configuration is valid.")
    for issue in issues:
        (st.error if issue.level == "error" else st.warning)(str(issue))

    c1, c2 = st.columns([1, 1])
    with c1:
        st.subheader("Export", help=sec("review_export"))
        st.download_button(
            "Download job_search_config.json",
            jc.dumps(config).encode("utf-8"),
            file_name="job_search_config.json",
            mime="application/json",
            help=h("review_download"),
        )
        st.caption("Share it, commit it (secrets as ${ENV}), or copy it to another machine.")
    with c2:
        st.subheader("Import", help=sec("review_import"))
        upload = st.file_uploader("Replace the configuration with a JSON file", type=["json"], help=h("review_upload"))
        if upload is not None:
            try:
                incoming = jc.loads(upload.getvalue().decode("utf-8"))
            except (ValueError, json.JSONDecodeError) as exc:
                st.error(f"Could not parse file: {exc}")
            else:
                incoming_issues = jc.validate(incoming)
                for issue in incoming_issues:
                    (st.error if issue.level == "error" else st.warning)(str(issue))
                if st.button("Import now", disabled=jc.has_errors(incoming_issues), help=h("review_import")):
                    persist(incoming, "Configuration imported.")

    st.subheader("Current JSON", help=sec("review_json"))
    st.code(jc.dumps(config), language="json")

    st.subheader("Danger zone", help=sec("review_danger"))
    d1, d2 = st.columns(2)
    if d1.button("Reset to defaults", help=h("review_reset")):
        st.session_state["confirm_reset"] = True
    if st.session_state.get("confirm_reset"):
        st.warning("This overwrites the configuration file (a .bak copy is kept).")
        if d2.button("Yes, reset", type="primary", help=h("review_reset_confirm")):
            st.session_state.pop("confirm_reset", None)
            persist(jc.default_config(), "Reset to defaults.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    config = current()
    st.sidebar.markdown("### ⚙ Configuration")
    st.sidebar.caption("Edits are written to the JSON file below. The main dashboard picks them up on its next search.")
    st.sidebar.caption(f"File: {config_file()}")
    st.sidebar.caption(f"Last saved: {config.updated_at or '—'}")
    if st.sidebar.button("Reload from disk", help=h("cfg_reload")):
        load()
        st.rerun()
    st.sidebar.divider()
    st.sidebar.markdown(f"[Open the main dashboard ↗]({MAIN_APP_URL})")
    st.sidebar.caption("Set JOB_SEARCH_APP_URL to change this link.")

    st.title("Job search configuration")
    flash()
    tabs = st.tabs(["Job sites", "Job preferences", "Site registry", "Search behaviour", "Review & backup"])
    with tabs[0]:
        page_sites(config)
    with tabs[1]:
        page_preferences(config)
    with tabs[2]:
        page_registry(config)
    with tabs[3]:
        page_search(config)
    with tabs[4]:
        page_review(config)


if __name__ == "__main__":
    main()
