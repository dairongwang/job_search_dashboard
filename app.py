"""Local job-search dashboard: research, tracking, contacts, and outreach.

Which sites are searched and what kind of jobs are wanted come from the
configuration file managed by ``config_dashboard.py`` (see README).
"""

from __future__ import annotations

import os
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

import jobsearch_config as jc
import jobsearch_sources as js
from ui_help import COLUMNS, column_config, h, sec

# Data location is configurable for deployment (e.g. a mounted volume in Docker).
DB_PATH = Path(os.environ.get("JOB_SEARCH_DB") or Path(__file__).with_name("job_search.db"))
CONFIG_APP_URL = os.environ.get("JOB_SEARCH_CONFIG_URL", "http://localhost:8502")

STATUSES = [
    "Saved",
    "Researching",
    "Applied",
    "Recruiter Screen",
    "Interview",
    "Final Round",
    "Offer",
    "Accepted",
    "Rejected",
    "Withdrawn",
    "On Hold",
]
OPEN_STATUSES = {
    "Saved",
    "Researching",
    "Applied",
    "Recruiter Screen",
    "Interview",
    "Final Round",
    "Offer",
    "On Hold",
}
PRIORITIES = ["High", "Medium", "Low"]
CHANNELS = ["Email", "LinkedIn", "Phone", "Referral", "InMail", "Event", "Other"]
OUTCOMES = ["Sent", "Replied", "Meeting set", "No response", "Not interested", "Referred"]

st.set_page_config(
    page_title="Job Search Dashboard",
    page_icon="◈",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
      :root {
        --ink: #1c1917;
        --muted: #57534e;
        --line: #e7e5e4;
        --paper: #faf7f2;
        --card: #ffffff;
        --accent: #0f6e6b;
        --accent-soft: #e7f3f2;
        --warn: #9a3412;
      }
      .stApp { background: var(--paper); color: var(--ink); }
      [data-testid="stSidebar"] { background: #1c1917; }
      [data-testid="stSidebar"] * { color: #faf7f2; }
      [data-testid="stSidebar"] a { color: #99f6e4 !important; }
      h1, h2, h3 { letter-spacing: -0.03em; }
      .pill {
        display: inline-block;
        background: var(--accent-soft);
        color: var(--accent);
        border-radius: 999px;
        padding: 2px 8px;
        font-size: 0.75rem;
        font-weight: 600;
      }
      .note {
        color: var(--muted);
        font-size: 0.92rem;
      }
    </style>
    """,
    unsafe_allow_html=True,
)


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS organizations (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                website TEXT,
                industry TEXT,
                location TEXT,
                notes TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY,
                title TEXT NOT NULL,
                organization TEXT,
                location TEXT,
                workplace TEXT,
                url TEXT,
                source TEXT,
                status TEXT NOT NULL DEFAULT 'Saved',
                priority TEXT NOT NULL DEFAULT 'Medium',
                salary TEXT,
                date_found TEXT,
                date_applied TEXT,
                next_action TEXT,
                next_action_date TEXT,
                notes TEXT,
                description TEXT,
                external_id TEXT,
                job_type TEXT,
                schedule TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS contacts (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                organization TEXT,
                title TEXT,
                email TEXT,
                linkedin TEXT,
                phone TEXT,
                relationship TEXT,
                notes TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS outreach (
                id INTEGER PRIMARY KEY,
                contact_name TEXT,
                organization TEXT,
                job_title TEXT,
                channel TEXT NOT NULL,
                subject TEXT,
                activity_date TEXT NOT NULL,
                follow_up_date TEXT,
                outcome TEXT,
                notes TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS research_notes (
                id INTEGER PRIMARY KEY,
                topic TEXT NOT NULL,
                body TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            );
            """
        )
        # Migrations for databases created by older versions.
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(jobs)")}
        for column in ("job_type", "schedule"):
            if column not in columns:
                conn.execute(f"ALTER TABLE jobs ADD COLUMN {column} TEXT")


# ---------------------------------------------------------------------------
# Configuration (edited by config_dashboard.py / the CLI; read-only here)
# ---------------------------------------------------------------------------


def get_config() -> jc.AppConfig:
    """Return the active configuration, reloading automatically when the file changes."""
    stamp = jc.mtime()
    if st.session_state.get("config") is None or st.session_state.get("config_mtime") != stamp:
        st.session_state["config"] = jc.load_config(create=True)
        st.session_state["config_mtime"] = jc.mtime()
    return st.session_state["config"]


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def today_iso() -> str:
    return date.today().isoformat()


def df_query(sql: str, params: tuple = ()) -> pd.DataFrame:
    with connect() as conn:
        return pd.read_sql_query(sql, conn, params=params)


def execute(sql: str, params: tuple = ()) -> None:
    with connect() as conn:
        conn.execute(sql, params)


def get_setting(key: str, default: str = "") -> str:
    with connect() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    execute(
        "INSERT INTO settings(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def metric(label: str, value: str, help_key: str = "") -> None:
    with st.container(border=True):
        st.metric(label, value, help=h(help_key) if help_key else None)


def save_job(row: dict, status: str = "Saved") -> str:
    external_id = row.get("external_id") or ""
    url = row.get("url") or ""
    with connect() as conn:
        if external_id:
            existing = conn.execute("SELECT id FROM jobs WHERE external_id = ?", (external_id,)).fetchone()
            if existing:
                return "already tracked"
        if url:
            existing = conn.execute("SELECT id FROM jobs WHERE url = ? AND url != ''", (url,)).fetchone()
            if existing:
                return "already tracked"
        stamp = now_iso()
        conn.execute(
            """
            INSERT INTO jobs (
                title, organization, location, workplace, url, source, status, priority,
                salary, date_found, next_action, notes, description, external_id, job_type, schedule,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'Medium', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row.get("title") or "Untitled role",
                row.get("organization") or "",
                row.get("location") or "",
                row.get("workplace") or "",
                url,
                row.get("source") or "Manual",
                status,
                row.get("salary") or row.get("salary_text") or "",
                row.get("published") or today_iso(),
                row.get("next_action") or "",
                row.get("notes") or "",
                row.get("description") or "",
                external_id,
                row.get("job_type") or "",
                row.get("schedule") or "",
                stamp,
                stamp,
            ),
        )
        org = (row.get("organization") or "").strip()
        if org:
            conn.execute(
                "INSERT OR IGNORE INTO organizations(name, website, created_at) VALUES(?, ?, ?)",
                (org, "", stamp),
            )
    return "saved"


def load_sample() -> None:
    stamp = now_iso()
    samples = [
        {
            "title": "Data Analyst",
            "organization": "Northline Health",
            "location": "Philadelphia, PA",
            "workplace": "Hybrid",
            "url": "https://example.com/jobs/northline-analyst",
            "source": "Sample",
            "status": "Applied",
            "salary": "$85k–$105k",
            "date_found": today_iso(),
            "date_applied": today_iso(),
            "next_action": "Follow up with recruiter",
            "next_action_date": (date.today() + timedelta(days=3)).isoformat(),
            "notes": "Sample record. Delete when you add real roles.",
            "external_id": "sample:1",
        },
        {
            "title": "Product Operations Associate",
            "organization": "Harbor & Co",
            "location": "Remote — US",
            "workplace": "Remote",
            "url": "https://example.com/jobs/harbor-ops",
            "source": "Sample",
            "status": "Researching",
            "salary": "",
            "date_found": today_iso(),
            "next_action": "Find a hiring manager on LinkedIn",
            "next_action_date": (date.today() + timedelta(days=1)).isoformat(),
            "notes": "Sample record.",
            "external_id": "sample:2",
        },
    ]
    with connect() as conn:
        for row in samples:
            existing = conn.execute(
                "SELECT id FROM jobs WHERE external_id = ?", (row["external_id"],)
            ).fetchone()
            if existing:
                continue
            conn.execute(
                """
                INSERT INTO jobs (
                    title, organization, location, workplace, url, source, status, priority,
                    salary, date_found, date_applied, next_action, next_action_date, notes,
                    external_id, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'Medium', ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["title"],
                    row["organization"],
                    row["location"],
                    row["workplace"],
                    row["url"],
                    row["source"],
                    row["status"],
                    row["salary"],
                    row["date_found"],
                    row.get("date_applied"),
                    row["next_action"],
                    row["next_action_date"],
                    row["notes"],
                    row["external_id"],
                    stamp,
                    stamp,
                ),
            )
            conn.execute(
                "INSERT OR IGNORE INTO organizations(name, location, created_at) VALUES(?, ?, ?)",
                (row["organization"], row["location"], stamp),
            )
        conn.execute(
            """
            INSERT INTO contacts(name, organization, title, email, linkedin, relationship, notes, created_at)
            SELECT ?, ?, ?, ?, ?, ?, ?, ?
            WHERE NOT EXISTS (SELECT 1 FROM contacts WHERE email = ?)
            """,
            (
                "Alex Rivera",
                "Northline Health",
                "Recruiter",
                "alex.rivera@example.com",
                "https://www.linkedin.com/in/example",
                "Recruiter",
                "Sample contact.",
                stamp,
                "alex.rivera@example.com",
            ),
        )


def page_dashboard() -> None:
    st.title("Job search")
    st.caption("One place for roles, companies, people, and the next message you owe.")

    jobs = df_query("SELECT * FROM jobs")
    outreach = df_query("SELECT * FROM outreach")
    contacts = df_query("SELECT * FROM contacts")

    open_jobs = jobs[jobs["status"].isin(OPEN_STATUSES)] if not jobs.empty else jobs
    applied = jobs[jobs["status"].isin(["Applied", "Recruiter Screen", "Interview", "Final Round", "Offer", "Accepted"])] if not jobs.empty else jobs
    interviews = jobs[jobs["status"].isin(["Interview", "Final Round", "Offer"])] if not jobs.empty else jobs
    week_ago = (date.today() - timedelta(days=7)).isoformat()
    recent_outreach = outreach[outreach["activity_date"] >= week_ago] if not outreach.empty else outreach

    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        metric("Open roles", str(len(open_jobs)), "metric_open")
    with c2:
        metric("In process", str(len(applied)), "metric_in_process")
    with c3:
        metric("Interviews / offers", str(len(interviews)), "metric_interviews")
    with c4:
        metric("Contacts", str(len(contacts)), "metric_contacts")
    with c5:
        metric("Outreach, 7 days", str(len(recent_outreach)), "metric_outreach")

    left, right = st.columns([1.2, 1])
    with left:
        st.subheader("Pipeline", help=sec("dash_pipeline"))
        if jobs.empty:
            st.info("No roles yet. Search public listings under Research, or add one under Jobs.")
        else:
            counts = jobs["status"].value_counts().reindex(STATUSES).fillna(0).astype(int)
            chart = counts[counts > 0].rename_axis("status").reset_index(name="roles")
            st.bar_chart(chart, x="status", y="roles", color="#0f6e6b", height=280)
    with right:
        st.subheader("Due and overdue", help=sec("dash_due"))
        if jobs.empty:
            st.caption("Next actions show up here once a role has a follow-up date.")
        else:
            due = jobs.dropna(subset=["next_action_date"])
            due = due[due["next_action_date"] <= (date.today() + timedelta(days=7)).isoformat()]
            due = due[due["status"].isin(OPEN_STATUSES)]
            if due.empty:
                st.caption("Nothing due in the next week.")
            else:
                show = due.sort_values("next_action_date")[
                    ["next_action_date", "title", "organization", "next_action", "status"]
                ]
                st.dataframe(show, hide_index=True, width="stretch", column_config=column_config(show.columns))

    st.subheader("Recent outreach", help=sec("dash_recent"))
    if outreach.empty:
        st.caption("Log a note, email, or LinkedIn touch under Outreach.")
    else:
        st.dataframe(
            outreach.sort_values("activity_date", ascending=False).head(8)[
                ["activity_date", "channel", "contact_name", "organization", "subject", "outcome", "follow_up_date"]
            ],
            hide_index=True,
            width="stretch",
            column_config=column_config(["activity_date", "channel", "contact_name", "organization", "subject", "outcome", "follow_up_date"]),
        )


def config_summary_md(config: jc.AppConfig) -> str:
    p = config.preferences
    sites = ", ".join(s.name for s in config.enabled_sites()) or "none enabled"
    parts = [
        f"**Sites:** {sites}",
        f"**Titles:** {', '.join(p.titles) or '—'}",
        f"**Skills:** {', '.join(p.skills) or '—'}",
        f"**Industries:** {', '.join(p.industries) or 'any'}",
        f"**Locations:** {', '.join(p.locations) or 'anywhere'} · {', '.join(jc.WORKPLACES[w] for w in p.workplaces)}",
        f"**Job types:** {', '.join(jc.JOB_TYPES[t] for t in p.job_types)} · {', '.join(jc.SCHEDULES[s] for s in p.schedules)}",
        f"**Salary:** {p.salary.describe()}",
        f"**Posted within:** {str(p.posted_within_days) + ' days' if p.posted_within_days else 'any time'}",
    ]
    return "  \n".join(parts)


def page_research() -> None:
    config = get_config()
    st.title("Research")
    st.markdown(
        '<p class="note">Searches the job sites you enabled in the configuration dashboard and applies your job '
        "preferences (titles, skills, location, salary, job type). Save the ones worth a closer look, then track them "
        "like any other role.</p>",
        unsafe_allow_html=True,
    )

    with st.expander("Active configuration", expanded=False):
        st.markdown(config_summary_md(config))
        issues = jc.validate(config)
        for issue in issues:
            (st.error if issue.level == "error" else st.warning)(str(issue))
        st.caption(f"Config file: {jc.config_path()} · change it in the [configuration dashboard]({CONFIG_APP_URL}).")

    enabled = config.enabled_sites()
    if not enabled:
        st.warning(f"No job sites are enabled. Open the [configuration dashboard]({CONFIG_APP_URL}) to pick some.")

    col_a, col_b = st.columns([2, 2])
    with col_a:
        keyword = st.text_input(
            "Keyword override",
            value="",
            placeholder=f"blank = use configured titles: {', '.join(config.preferences.titles[:3]) or '—'}",
            help=h("research_keyword"),
        )
    with col_b:
        site_ids = st.multiselect(
            "Sites for this run",
            [s.id for s in enabled],
            default=[s.id for s in enabled],
            format_func=lambda sid: next((s.name for s in enabled if s.id == sid), sid),
            help=h("research_sites"),
        )
    col_c, col_d = st.columns([1, 3])
    with col_c:
        strict = st.toggle("Strict filters", value=config.search.strict_filtering, help=h("research_strict"))
    with col_d:
        run = st.button("Search listings", type="primary", disabled=not site_ids, help=h("research_run"))

    if run:
        with st.spinner(f"Checking {len(site_ids)} site(s)…"):
            report = js.run_search(config, keyword=keyword if keyword.strip() else None, site_ids=site_ids, strict=strict)
        st.session_state["search_report"] = report

    report = st.session_state.get("search_report")
    if isinstance(report, js.SearchReport):
        if report.errors:
            with st.expander(f"{len(report.errors)} site(s) could not be searched", expanded=True):
                for outcome in report.outcomes:
                    if outcome.error:
                        (st.error if outcome.denied else st.warning)(f"{outcome.name}: {outcome.error}")
                st.caption(
                    "Sites that answer HTTP 403 or return a web page do not offer a feed/API for scripts. "
                    f"Fix or disable them in the [configuration dashboard]({CONFIG_APP_URL})."
                )
        rows = report.rows()
        kept = sum(1 for r in rows if r["passes"])
        if report.fetched and kept == 0 and report.dropped:
            top = ", ".join(f"{kind} ({count})" for kind, count in report.dropped.most_common(6))
            st.info(
                f"All {report.fetched} fetched listing(s) were removed by your preferences — {top}. "
                "Turn off **Strict filters** to see them with the reason, or loosen the preference in the configuration dashboard."
            )
        with st.expander(
            f"{kept} listing(s) after filters · fetched {report.fetched} unique across {len(report.outcomes)} site(s)",
            expanded=False,
        ):
            if report.dropped:
                st.caption("Removed by filters: " + ", ".join(f"{kind} {count}" for kind, count in report.dropped.most_common()))
            st.dataframe(
                pd.DataFrame(
                    [
                        {"site": o.name, "fetched": o.fetched, "kept": o.kept, "seconds": o.seconds, "status": o.error or (o.note or "ok")}
                        for o in report.outcomes
                    ]
                ),
                hide_index=True,
                width="stretch",
                column_config=column_config(["site", "fetched", "kept", "seconds", "status"]),
            )
            if report.keywords:
                st.caption("Search phrases: " + ", ".join(report.keywords))
            for line in report.attributions:
                st.caption(line)
        frame = pd.DataFrame(rows)
        if not frame.empty:
            st.session_state["search_results"] = frame
            preview_cols = [
                "score", "title", "organization", "location", "workplace", "job_type", "salary_text",
                "matched_skills", "published", "source", "url",
            ]
            if not strict:
                preview_cols.insert(1, "passes")
                preview_cols.append("filter_notes")
            st.dataframe(
                frame[preview_cols],
                hide_index=True,
                width="stretch",
                column_config=column_config(
                    preview_cols,
                    url=st.column_config.LinkColumn("listing", help=COLUMNS["url"]),
                    score=st.column_config.ProgressColumn(
                        "match", min_value=0, max_value=max(100, int(frame["score"].max())), help=COLUMNS["score"]
                    ),
                    salary_text="salary",
                    passes=st.column_config.CheckboxColumn("ok", help=COLUMNS["passes"]),
                ),
            )
            labels = [f"{i}. {row.title} — {row.organization}" for i, row in frame.iterrows()]
            picked = st.multiselect("Save into the tracker", labels, help=h("research_pick"))
            if st.button("Save selected", help=h("research_save")) and picked:
                saved = skipped = 0
                for label in picked:
                    idx = int(label.split(".", 1)[0])
                    result = save_job(frame.loc[idx].to_dict())
                    saved += result == "saved"
                    skipped += result != "saved"
                st.success(f"Saved {saved}. Already tracked: {skipped}.")
            st.download_button("Export results CSV", frame.to_csv(index=False).encode(), "search_results.csv", "text/csv", help=h("research_export"))
        else:
            st.info("No matches. Loosen a preference in the configuration dashboard, turn off strict filters, or try another keyword.")

    st.subheader("Target companies", help=sec("research_targets"))
    with st.form("add_org", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        name = c1.text_input("Company", help=h("org_name"))
        industry = c2.text_input("Industry", help=h("org_industry"))
        location = c3.text_input("Location", help=h("org_location"))
        website = st.text_input("Website", help=h("org_website"))
        notes = st.text_area("Why this company", height=80, help=h("org_why"))
        if st.form_submit_button("Add company", help=h("org_add")) and name.strip():
            execute(
                "INSERT OR IGNORE INTO organizations(name, website, industry, location, notes, created_at) VALUES(?, ?, ?, ?, ?, ?)",
                (name.strip(), website.strip(), industry.strip(), location.strip(), notes.strip(), now_iso()),
            )
            st.success(f"Added {name.strip()}.")
            st.rerun()
    orgs = df_query("SELECT name, industry, location, website, notes FROM organizations ORDER BY name")
    if not orgs.empty:
        st.dataframe(
            orgs,
            hide_index=True,
            width="stretch",
            column_config=column_config(orgs.columns, name=st.column_config.Column("name", help="Company name."), website=st.column_config.LinkColumn(help=COLUMNS["website"])),
        )

    st.subheader("Research notes", help=sec("research_notes"))
    with st.form("note", clear_on_submit=True):
        topic = st.text_input("Topic", placeholder="Salary bands for analyst roles in Philly", help=h("note_topic"))
        body = st.text_area("Note", help=h("note_body"))
        if st.form_submit_button("Save note", help=h("note_save")) and topic.strip():
            execute(
                "INSERT INTO research_notes(topic, body, created_at) VALUES(?, ?, ?)",
                (topic.strip(), body.strip(), now_iso()),
            )
            st.rerun()
    notes = df_query("SELECT created_at, topic, body FROM research_notes ORDER BY id DESC")
    if not notes.empty:
        st.dataframe(notes, hide_index=True, width="stretch", column_config=column_config(notes.columns))


def page_jobs() -> None:
    st.title("Jobs")
    jobs = df_query("SELECT * FROM jobs ORDER BY updated_at DESC")

    with st.expander("Add a role", expanded=jobs.empty):
        with st.form("add_job", clear_on_submit=True):
            c1, c2 = st.columns(2)
            title = c1.text_input("Title", help=h("job_title"))
            organization = c2.text_input("Organization", help=h("job_org"))
            c3, c4, c5 = st.columns(3)
            location = c3.text_input("Location", help=h("job_location"))
            workplace = c4.selectbox("Workplace", ["Remote", "Hybrid", "On-site", "Unknown"], help=h("job_workplace"))
            status = c5.selectbox("Status", STATUSES, index=0, help=h("job_status"))
            c6, c7 = st.columns(2)
            priority = c6.selectbox("Priority", PRIORITIES, index=1, help=h("job_priority"))
            salary = c7.text_input("Salary", help=h("job_salary"))
            url = st.text_input("Listing URL", help=h("job_url"))
            next_action = st.text_input("Next action", help=h("job_next_action"))
            next_action_date = st.date_input("Next action date", value=date.today(), help=h("job_next_date"))
            notes = st.text_area("Notes", help=h("job_notes"))
            if st.form_submit_button("Add role", help=h("job_add")) and title.strip():
                result = save_job(
                    {
                        "title": title.strip(),
                        "organization": organization.strip(),
                        "location": location.strip(),
                        "workplace": workplace,
                        "url": url.strip(),
                        "source": "Manual",
                        "salary": salary.strip(),
                        "notes": notes.strip(),
                        "next_action": next_action.strip(),
                        "published": today_iso(),
                        "external_id": "",
                    },
                    status=status,
                )
                if result == "saved":
                    execute(
                        """
                        UPDATE jobs
                        SET priority = ?, next_action = ?, next_action_date = ?, date_applied = ?
                        WHERE id = (SELECT MAX(id) FROM jobs)
                        """,
                        (
                            priority,
                            next_action.strip(),
                            next_action_date.isoformat() if next_action.strip() else None,
                            today_iso() if status not in {"Saved", "Researching"} else None,
                        ),
                    )
                    st.success("Role added.")
                else:
                    st.info("That listing URL is already in the tracker.")
                st.rerun()

    if jobs.empty:
        st.info("The tracker is empty. Add a role above, or save listings from Research.")
        if st.button("Load two sample roles", help=h("job_load_sample")):
            load_sample()
            st.rerun()
        return

    f1, f2, f3 = st.columns(3)
    status_filter = f1.multiselect("Status", STATUSES, default=[s for s in STATUSES if s in OPEN_STATUSES], help=h("job_filter_status"))
    priority_filter = f2.multiselect("Priority", PRIORITIES, default=PRIORITIES, help=h("job_filter_priority"))
    query = f3.text_input("Filter title or company", help=h("job_filter_text"))
    view = jobs[jobs["status"].isin(status_filter) & jobs["priority"].isin(priority_filter)]
    if query.strip():
        needle = query.lower()
        view = view[
            view["title"].str.lower().str.contains(needle, na=False)
            | view["organization"].fillna("").str.lower().str.contains(needle, na=False)
        ]
    columns = [
        "id",
        "title",
        "organization",
        "status",
        "priority",
        "location",
        "job_type",
        "salary",
        "date_applied",
        "next_action",
        "next_action_date",
        "url",
    ]
    st.dataframe(
        view[columns],
        hide_index=True,
        width="stretch",
        column_config=column_config(columns, url=st.column_config.LinkColumn(help=COLUMNS["url"])),
    )
    st.download_button(
        "Export filtered jobs CSV",
        view.to_csv(index=False).encode(),
        "jobs.csv",
        "text/csv",
        help=h("job_export"),
    )

    st.subheader("Update a role", help=sec("jobs_update"))
    labels = {f"{row.id}: {row.title} @ {row.organization or '—'}": int(row.id) for row in jobs.itertuples()}
    choice = st.selectbox("Role", list(labels), help=h("job_pick"))
    job_id = labels[choice]
    row = jobs[jobs["id"] == job_id].iloc[0]
    with st.form("edit_job"):
        e1, e2, e3 = st.columns(3)
        status = e1.selectbox("Status", STATUSES, index=STATUSES.index(row.status) if row.status in STATUSES else 0, help=h("job_status"))
        priority = e2.selectbox("Priority", PRIORITIES, index=PRIORITIES.index(row.priority) if row.priority in PRIORITIES else 1, help=h("job_priority"))
        salary = e3.text_input("Salary", value=row.salary or "", help=h("job_salary"))
        applied_default = date.fromisoformat(row.date_applied) if row.date_applied else date.today()
        date_applied = st.date_input("Date applied", value=applied_default, help=h("job_date_applied"))
        mark_applied = st.checkbox("Record an application date", value=bool(row.date_applied), help=h("job_mark_applied"))
        next_action = st.text_input("Next action", value=row.next_action or "", help=h("job_next_action"))
        follow_default = date.fromisoformat(row.next_action_date) if row.next_action_date else date.today()
        next_action_date = st.date_input("Next action date", value=follow_default, help=h("job_next_date"))
        notes = st.text_area("Notes", value=row.notes or "", help=h("job_notes"))
        if st.form_submit_button("Save changes", help=h("job_save")):
            execute(
                """
                UPDATE jobs
                SET status = ?, priority = ?, salary = ?, date_applied = ?, next_action = ?,
                    next_action_date = ?, notes = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    status,
                    priority,
                    salary.strip(),
                    date_applied.isoformat() if mark_applied else None,
                    next_action.strip(),
                    next_action_date.isoformat() if next_action.strip() else None,
                    notes.strip(),
                    now_iso(),
                    job_id,
                ),
            )
            st.success("Updated.")
            st.rerun()
    if st.button("Delete this role", help=h("job_delete")):
        execute("DELETE FROM jobs WHERE id = ?", (job_id,))
        st.rerun()


def page_people() -> None:
    st.title("Contacts")
    st.caption("Recruiters, hiring managers, and people who can make an introduction.")
    with st.form("add_contact", clear_on_submit=True):
        c1, c2 = st.columns(2)
        name = c1.text_input("Name", help=h("contact_name"))
        organization = c2.text_input("Organization", help=h("contact_org"))
        c3, c4 = st.columns(2)
        title = c3.text_input("Title", help=h("contact_title"))
        relationship = c4.text_input("Relationship", placeholder="Recruiter, classmate, hiring manager", help=h("contact_relationship"))
        email = st.text_input("Email", help=h("contact_email"))
        linkedin = st.text_input("LinkedIn URL", help=h("contact_linkedin"))
        notes = st.text_area("Notes", height=80, help=h("contact_notes"))
        if st.form_submit_button("Add contact", help=h("contact_add")) and name.strip():
            execute(
                """
                INSERT INTO contacts(name, organization, title, email, linkedin, relationship, notes, created_at)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    name.strip(),
                    organization.strip(),
                    title.strip(),
                    email.strip(),
                    linkedin.strip(),
                    relationship.strip(),
                    notes.strip(),
                    now_iso(),
                ),
            )
            if organization.strip():
                execute(
                    "INSERT OR IGNORE INTO organizations(name, created_at) VALUES(?, ?)",
                    (organization.strip(), now_iso()),
                )
            st.rerun()
    contacts = df_query(
        "SELECT id, name, organization, title, email, linkedin, relationship, notes FROM contacts ORDER BY name"
    )
    if contacts.empty:
        st.info("No contacts yet.")
        return
    shown = contacts.drop(columns=["id"])
    st.dataframe(
        shown,
        hide_index=True,
        width="stretch",
        column_config=column_config(shown.columns, linkedin=st.column_config.LinkColumn(help=COLUMNS["linkedin"]), title=st.column_config.Column("title", help="Their job title.")),
    )
    st.download_button("Export contacts CSV", contacts.to_csv(index=False).encode(), "contacts.csv", "text/csv", help=h("contact_export"))
    labels = {f"{row.id}: {row.name}": int(row.id) for row in contacts.itertuples()}
    choice = st.selectbox("Remove contact", ["—"] + list(labels), help=h("contact_remove_pick"))
    if choice != "—" and st.button("Delete contact", help=h("contact_delete")):
        execute("DELETE FROM contacts WHERE id = ?", (labels[choice],))
        st.rerun()


def page_outreach() -> None:
    st.title("Outreach")
    contacts = df_query("SELECT name, organization FROM contacts ORDER BY name")
    jobs = df_query("SELECT title, organization FROM jobs ORDER BY updated_at DESC")
    contact_labels = ["—"] + [f"{row.name} ({row.organization or 'no company'})" for row in contacts.itertuples()]
    job_labels = ["—"] + [f"{row.title} @ {row.organization or '—'}" for row in jobs.itertuples()]

    with st.form("log_outreach", clear_on_submit=True):
        c1, c2 = st.columns(2)
        contact = c1.selectbox("Contact", contact_labels, help=h("outreach_contact"))
        role = c2.selectbox("Related role", job_labels, help=h("outreach_role"))
        c3, c4 = st.columns(2)
        channel = c3.selectbox("Channel", CHANNELS, help=h("outreach_channel"))
        outcome = c4.selectbox("Outcome", OUTCOMES, help=h("outreach_outcome"))
        subject = st.text_input("Subject or purpose", placeholder="Intro note about the analyst role", help=h("outreach_subject"))
        activity_date = st.date_input("Date", value=date.today(), help=h("outreach_date"))
        follow_up = st.date_input("Follow up on", value=date.today() + timedelta(days=5), help=h("outreach_follow_up"))
        use_follow_up = st.checkbox("Set a follow-up", value=True, help=h("outreach_use_follow_up"))
        notes = st.text_area("What you sent / what they said", help=h("outreach_notes"))
        if st.form_submit_button("Log outreach", type="primary", help=h("outreach_log")):
            contact_name = ""
            organization = ""
            if contact != "—":
                contact_name = contact.split(" (", 1)[0]
                match = contacts[contacts["name"] == contact_name]
                if not match.empty:
                    organization = match.iloc[0]["organization"] or ""
            job_title = "" if role == "—" else role
            if role != "—" and " @ " in role:
                organization = organization or role.split(" @ ", 1)[1]
            execute(
                """
                INSERT INTO outreach(
                    contact_name, organization, job_title, channel, subject,
                    activity_date, follow_up_date, outcome, notes, created_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    contact_name,
                    organization,
                    job_title,
                    channel,
                    subject.strip(),
                    activity_date.isoformat(),
                    follow_up.isoformat() if use_follow_up else None,
                    outcome,
                    notes.strip(),
                    now_iso(),
                ),
            )
            st.success("Logged.")
            st.rerun()

    log = df_query("SELECT * FROM outreach ORDER BY activity_date DESC, id DESC")
    if log.empty:
        st.info("No outreach yet. A short log is enough: who, channel, date, and when to follow up.")
        return
    due = log.dropna(subset=["follow_up_date"])
    due = due[due["follow_up_date"] <= (date.today() + timedelta(days=3)).isoformat()]
    due = due[due["outcome"].isin(["Sent", "No response"])]
    if not due.empty:
        st.subheader("Follow-ups coming due", help=sec("outreach_due"))
        st.dataframe(
            due[["follow_up_date", "contact_name", "organization", "channel", "subject"]],
            hide_index=True,
            width="stretch",
            column_config=column_config(["follow_up_date", "contact_name", "organization", "channel", "subject"]),
        )
    st.subheader("Log", help=sec("outreach_log"))
    log_cols = ["activity_date", "channel", "contact_name", "organization", "job_title", "subject", "outcome", "follow_up_date", "notes"]
    st.dataframe(log[log_cols], hide_index=True, width="stretch", column_config=column_config(log_cols))
    st.download_button("Export outreach CSV", log.to_csv(index=False).encode(), "outreach.csv", "text/csv", help=h("outreach_export"))


def page_configuration() -> None:
    """Read-only view of the configuration the app is running with.

    Editing happens in the separate configuration dashboard (config_dashboard.py)
    or through ``python -m jobsearch_config`` so that operation and configuration
    can be deployed and secured independently.
    """
    config = get_config()
    st.title("Configuration")
    st.markdown(
        f'<p class="note">This page is read-only. Change sites and preferences in the '
        f'<a href="{CONFIG_APP_URL}" target="_blank">configuration dashboard</a> '
        f"(<code>streamlit run config_dashboard.py --server.port 8502</code>) or with "
        f"<code>python -m jobsearch_config</code>. Changes are picked up automatically.</p>",
        unsafe_allow_html=True,
    )
    c1, c2 = st.columns([3, 1])
    c1.code(str(jc.config_path()), language="text")
    if c2.button("Reload now", help=h("reload_config")):
        st.session_state.pop("config", None)
        st.rerun()
    st.caption(f"Last saved: {config.updated_at or '—'}")

    issues = jc.validate(config)
    if not issues:
        st.success("Configuration is valid.")
    for issue in issues:
        (st.error if issue.level == "error" else st.warning)(str(issue))

    st.subheader("Job sites", help=sec("app_cfg_sites"))
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "enabled": s.enabled,
                    "site": s.name,
                    "provider": (jc.provider(s.provider).label if jc.provider(s.provider) else s.provider),
                    "max results": s.max_results,
                    "options": ", ".join(f"{k}={'••••' if 'key' in k or 'secret' in k or k == 'app_id' else v}" for k, v in s.options.items() if v not in ("", None, {}))
                    or "—",
                }
                for s in config.sites
            ]
        ),
        hide_index=True,
        width="stretch",
        column_config=column_config(
            ["enabled", "site", "provider", "max results", "options"],
            enabled=st.column_config.CheckboxColumn(disabled=True, help=COLUMNS["enabled"]),
        ),
    )
    st.subheader("Job preferences", help=sec("app_cfg_prefs"))
    st.markdown(config_summary_md(config))
    st.subheader("Site registry", help=sec("app_cfg_registry"))
    st.caption("Hosts the app has checked. Inactive hosts forbid automated access and are skipped. Managed in the configuration dashboard.")
    rows = jc.load_registry().list()
    if rows:
        st.dataframe(
            pd.DataFrame(
                [
                    {"host": r.host, "active": r.active, "status": r.status, "checks": r.checks, "updated": r.updated_at, "message": r.message}
                    for r in rows
                ]
            ),
            hide_index=True,
            width="stretch",
            column_config=column_config(
                ["host", "active", "status", "checks", "updated", "message"],
                active=st.column_config.CheckboxColumn(disabled=True, help=COLUMNS["active"]),
            ),
        )
    with st.expander("Raw JSON"):
        st.code(jc.dumps(config), language="json")


def main() -> None:
    init_db()
    config = get_config()
    st.sidebar.markdown("### Job search")
    st.sidebar.caption("Local tracker. Your SQLite file never leaves this machine.")
    page = st.sidebar.radio(
        "Go to",
        ["Dashboard", "Research", "Jobs", "Contacts", "Outreach", "Configuration"],
        help=h("nav"),
        captions=[
            "Counts, pipeline, what is due",
            "Search sites, save listings",
            "Your roles and their status",
            "Recruiters and referrers",
            "Messages and follow-ups",
            "Active sites & preferences (read-only)",
        ],
    )
    st.sidebar.divider()
    st.sidebar.caption(f"Database: {DB_PATH.name}")
    enabled = config.enabled_sites()
    st.sidebar.caption(
        f"Searching {len(enabled)} site(s): {', '.join(s.name for s in enabled) or 'none'}"
    )
    st.sidebar.markdown(f"[Configure sites & preferences ↗]({CONFIG_APP_URL})")
    if page == "Dashboard":
        page_dashboard()
    elif page == "Research":
        page_research()
    elif page == "Jobs":
        page_jobs()
    elif page == "Contacts":
        page_people()
    elif page == "Outreach":
        page_outreach()
    else:
        page_configuration()


if __name__ == "__main__":
    main()
