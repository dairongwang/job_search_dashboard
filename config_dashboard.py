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

import streamlit as st

import jobsearch_config as jc
from jobsearch_config.validate import ENV_REF_RE

try:  # optional: live "Test site" button needs the adapters
    import jobsearch_sources as js
except Exception:  # pragma: no cover - sources are optional for the config UI
    js = None  # type: ignore[assignment]

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
        default_text = json.dumps(value if isinstance(value, dict) else (opt.default or {}), indent=2)
        text = st.text_area(label, value=default_text, key=key, help=opt.help, height=180)
        try:
            parsed = json.loads(text) if text.strip() else {}
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
        if st.button("Remove", key=f"rm-{site.id}"):
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
        enabled = c1.checkbox("Enabled", value=site.enabled)
        name = c2.text_input("Display name", value=site.name)
        max_results = c3.number_input("Max results", min_value=1, max_value=200, value=int(site.max_results), step=5)
        values: dict[str, Any] = {}
        if spec.options:
            cols = st.columns(2) if len(spec.options) > 1 else [st.container()]
            for index, opt in enumerate(spec.options):
                with cols[index % len(cols)] if len(spec.options) > 1 else cols[0]:
                    values[opt.key] = render_option(site, opt, f"opt:{site.id}")
        notes = st.text_input("Notes", value=site.notes, placeholder="Why this site, rate-limit reminders, …")
        b1, b2 = st.columns([1, 1])
        save = b1.form_submit_button("Save site", type="primary")
        remove = b2.form_submit_button("Remove site")
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

    if js is not None:
        if st.button("Test this site now", key=f"test-{site.id}", help="Fetches live listings with the saved settings (needs internet)."):
            with st.spinner(f"Contacting {site.name}…"):
                jobs, outcome = js.test_site(site, config)
            if outcome.error:
                st.error(f"{site.name}: {outcome.error}")
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
                    )


def add_site_panel(config: jc.AppConfig) -> None:
    st.subheader("Add a site")
    existing = {s.provider for s in config.sites}
    tab_builtin, tab_custom = st.tabs(["From the catalog", "Custom feed or API"])

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
            )
            st.caption(spec.description)
            if st.button("Add to my sites", key="add-builtin-btn"):
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
        spec = st.selectbox("Type", jc.custom_providers(), format_func=lambda s: s.label, key="add-custom-kind")
        st.caption(spec.description)
        c1, c2 = st.columns(2)
        site_id = c1.text_input("Site id", placeholder="acme-careers", key="add-custom-id", help="Lowercase letters, digits, - or _.")
        name = c2.text_input("Display name", placeholder="Acme careers page", key="add-custom-name")
        url = st.text_input("URL", placeholder="https://example.com/jobs.rss?q={keyword}", key="add-custom-url")
        if st.button("Create site", key="add-custom-btn"):
            sid = site_id.strip().lower()
            if not re.match(r"^[a-z0-9][a-z0-9_-]{0,39}$", sid):
                st.error("Site id must be lowercase letters, digits, '-' or '_'.")
            elif config.get_site(sid):
                st.error("That site id already exists.")
            elif not url.strip().lower().startswith(("http://", "https://")):
                st.error("URL must start with http:// or https://.")
            else:
                options = jc.default_options(spec.key)
                options["url"] = url.strip()
                config.upsert_site(jc.SiteConfig(id=sid, provider=spec.key, name=name.strip() or sid, enabled=True, options=options))
                persist(config, f"Created {name or sid}. Adjust its mapping/options below.")


def page_sites(config: jc.AppConfig) -> None:
    st.header("Job sites")
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
        help="Select which sites are searched; press Apply.",
    )
    if st.button("Apply quick toggle"):
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
    add_site_panel(config)


# ---------------------------------------------------------------------------
# Preferences editor
# ---------------------------------------------------------------------------


def page_preferences(config: jc.AppConfig) -> None:
    st.header("Job preferences")
    st.markdown(
        '<p class="note">Describe the jobs you want. Titles and skills are sent to sites that support keyword search and '
        "used to rank every result; location, salary, job type and workplace are applied as filters.</p>",
        unsafe_allow_html=True,
    )
    prefs = config.preferences
    with st.form("prefs"):
        st.subheader("Role")
        c1, c2 = st.columns(2)
        titles = c1.multiselect(
            "Target titles / keywords",
            options=sorted(set(prefs.titles)),
            default=prefs.titles,
            accept_new_options=True,
            help="Type a phrase and press Enter. The first three are used as search queries.",
        )
        industries = c2.multiselect(
            "Industries",
            options=sorted(set(jc.INDUSTRIES) | set(prefs.industries)),
            default=prefs.industries,
            accept_new_options=True,
            help="Optional. Mapped to site categories where possible and used for ranking.",
        )
        c3, c4 = st.columns([2, 1])
        skills = c3.multiselect(
            "Skills",
            options=sorted(set(prefs.skills)),
            default=prefs.skills,
            accept_new_options=True,
            help="Each matching skill raises a listing's score.",
        )
        min_skills = c4.number_input(
            "Require at least N skills",
            min_value=0,
            max_value=20,
            value=int(prefs.min_skill_matches),
            help="0 = skills only influence ranking.",
        )
        exclude = st.multiselect(
            "Exclude keywords",
            options=sorted(set(prefs.exclude_keywords)),
            default=prefs.exclude_keywords,
            accept_new_options=True,
            help="Listings containing any of these words are dropped (e.g. 'senior', 'clearance').",
        )

        st.subheader("Location")
        c5, c6 = st.columns([2, 1])
        locations = c5.multiselect(
            "Preferred locations",
            options=sorted(set(prefs.locations)),
            default=prefs.locations,
            accept_new_options=True,
            help="Cities, states, countries or regions. Add 'Remote' to accept remote roles from any region; "
            "otherwise remote roles must be open to one of your locations (e.g. 'United States').",
        )
        workplaces = c6.multiselect(
            "Workplace",
            options=list(jc.WORKPLACES),
            default=prefs.workplaces,
            format_func=lambda k: jc.WORKPLACES[k],
        )

        st.subheader("Employment")
        c7, c8 = st.columns([2, 1])
        job_types = c7.multiselect(
            "Job types",
            options=list(jc.JOB_TYPES),
            default=prefs.job_types,
            format_func=lambda k: jc.JOB_TYPES[k],
            help="Permanent vs. temporary/contract work.",
        )
        schedules = c8.multiselect(
            "Schedule",
            options=list(jc.SCHEDULES),
            default=prefs.schedules,
            format_func=lambda k: jc.SCHEDULES[k],
        )
        include_unknown = st.checkbox(
            "Keep listings that don't state a job type",
            value=prefs.include_unknown_job_type,
            help="Many feeds omit the employment type.",
        )

        st.subheader("Salary")
        s1, s2, s3, s4, s5 = st.columns([1, 1, 1, 1, 1.4])
        minimum = s1.number_input("Minimum", min_value=0, value=int(prefs.salary.minimum or 0), step=5000, help="0 = no minimum")
        maximum = s2.number_input("Maximum", min_value=0, value=int(prefs.salary.maximum or 0), step=5000, help="0 = no maximum")
        currency = s3.selectbox(
            "Currency",
            options=sorted(set(jc.CURRENCIES) | {prefs.salary.currency}),
            index=sorted(set(jc.CURRENCIES) | {prefs.salary.currency}).index(prefs.salary.currency),
        )
        period = s4.selectbox(
            "Period",
            options=list(jc.SALARY_PERIODS),
            index=list(jc.SALARY_PERIODS).index(prefs.salary.period),
            format_func=lambda k: jc.SALARY_PERIODS[k],
        )
        include_unlisted = s5.checkbox(
            "Keep listings without pay info",
            value=prefs.salary.include_unlisted,
            help="Most boards do not publish salary. Untick to see only listings with pay in range.",
        )

        st.subheader("Freshness")
        posted = st.number_input(
            "Only listings posted within the last N days",
            min_value=0,
            max_value=365,
            value=int(prefs.posted_within_days or 0),
            help="0 = no limit.",
        )

        if st.form_submit_button("Save preferences", type="primary"):
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

    st.markdown("##### Effective filter summary")
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
# Search behaviour
# ---------------------------------------------------------------------------


def page_search(config: jc.AppConfig) -> None:
    st.header("Search behaviour")
    s = config.search
    with st.form("search-settings"):
        c1, c2 = st.columns(2)
        timeout = c1.number_input("Per-site timeout (seconds)", min_value=3, max_value=120, value=int(s.timeout_seconds))
        user_agent = c2.text_input("User-Agent header", value=s.user_agent, help="Some feeds require an identifying user agent.")
        strict = st.checkbox(
            "Strict filtering (hide listings that fail a filter)",
            value=s.strict_filtering,
            help="When off, everything is shown and failing listings are ranked lower with the reason.",
        )
        dedupe = st.checkbox("De-duplicate by listing URL across sites", value=s.dedupe_by_url)
        if st.form_submit_button("Save search behaviour", type="primary"):
            config.search = jc.SearchSettings(timeout_seconds=int(timeout), strict_filtering=strict, dedupe_by_url=dedupe, user_agent=user_agent)
            persist(config, "Search behaviour saved.")


# ---------------------------------------------------------------------------
# Review / import / export
# ---------------------------------------------------------------------------


def page_review(config: jc.AppConfig) -> None:
    st.header("Review & backup")
    issues = jc.validate(config)
    if not issues:
        st.success("Configuration is valid.")
    for issue in issues:
        (st.error if issue.level == "error" else st.warning)(str(issue))

    c1, c2 = st.columns([1, 1])
    with c1:
        st.subheader("Export")
        st.download_button(
            "Download job_search_config.json",
            jc.dumps(config).encode("utf-8"),
            file_name="job_search_config.json",
            mime="application/json",
        )
        st.caption("Share it, commit it (secrets as ${ENV}), or copy it to another machine.")
    with c2:
        st.subheader("Import")
        upload = st.file_uploader("Replace the configuration with a JSON file", type=["json"])
        if upload is not None:
            try:
                incoming = jc.loads(upload.getvalue().decode("utf-8"))
            except (ValueError, json.JSONDecodeError) as exc:
                st.error(f"Could not parse file: {exc}")
            else:
                incoming_issues = jc.validate(incoming)
                for issue in incoming_issues:
                    (st.error if issue.level == "error" else st.warning)(str(issue))
                if st.button("Import now", disabled=jc.has_errors(incoming_issues)):
                    persist(incoming, "Configuration imported.")

    st.subheader("Current JSON")
    st.code(jc.dumps(config), language="json")

    st.subheader("Danger zone")
    d1, d2 = st.columns(2)
    if d1.button("Reset to defaults"):
        st.session_state["confirm_reset"] = True
    if st.session_state.get("confirm_reset"):
        st.warning("This overwrites the configuration file (a .bak copy is kept).")
        if d2.button("Yes, reset", type="primary"):
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
    if st.sidebar.button("Reload from disk"):
        load()
        st.rerun()
    st.sidebar.divider()
    st.sidebar.markdown(f"[Open the main dashboard ↗]({MAIN_APP_URL})")
    st.sidebar.caption("Set JOB_SEARCH_APP_URL to change this link.")

    st.title("Job search configuration")
    flash()
    tabs = st.tabs(["Job sites", "Job preferences", "Search behaviour", "Review & backup"])
    with tabs[0]:
        page_sites(config)
    with tabs[1]:
        page_preferences(config)
    with tabs[2]:
        page_search(config)
    with tabs[3]:
        page_review(config)


if __name__ == "__main__":
    main()
