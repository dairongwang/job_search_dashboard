"""Tooltip texts for every interactive element of both dashboards.

Kept in one place so wording is consistent, searchable and testable
(``tests/test_tooltips.py`` checks that every widget carries a tooltip).
Each entry explains what the element does, how it relates to the rest of
the app, and gives a concrete example. Markdown is allowed.
"""

from __future__ import annotations

HELP: dict[str, str] = {
    # ------------------------------------------------------------------ shared / navigation
    "nav": (
        "Pages of the tracker.\n\n"
        "- **Dashboard** – counts, pipeline chart, what is due.\n"
        "- **Research** – search the configured job sites and save listings.\n"
        "- **Jobs** – every saved role and its status.\n"
        "- **Contacts** / **Outreach** – people and the messages you owe them.\n"
        "- **Configuration** – read-only view of sites and preferences (edit them in the configuration dashboard).\n\n*Example:* after a search on **Research**, saved listings show up on **Jobs**; logging a recruiter reply on **Outreach** clears it from the Dashboard's due list."
    ),
    "reload_config": (
        "Re-reads `job_search_config.json` right now. Normally unnecessary: the app notices the file's timestamp change "
        "after every save in the configuration dashboard.\n\n*Example:* you edited the JSON by hand and want the new "
        "sites to appear immediately."
    ),
    # ------------------------------------------------------------------ dashboard metrics
    "metric_open": "Roles whose status is still in play (Saved … Offer, On Hold). Rejected, Withdrawn and Accepted are excluded.\n\n*Example:* 12 open roles = 12 things that may still need an action.",
    "metric_in_process": "Roles you have actually applied to: Applied, Recruiter Screen, Interview, Final Round, Offer, Accepted.\n\n*Example:* 4 in process out of 12 open means 8 are still only saved or being researched.",
    "metric_interviews": "Roles at Interview, Final Round or Offer stage — the ones that deserve preparation time this week.\n\n*Example:* 2 here = two roles where you should be rehearsing answers, not sending new applications.",
    "metric_contacts": "People in the Contacts page (recruiters, hiring managers, referrers).\n\n*Example:* 15 contacts across 12 open roles means roughly one warm person per company.",
    "metric_outreach": "Outreach entries logged in the last 7 days. A steady number here usually predicts interviews two to four weeks later.\n\n*Example:* 6 touches this week; if it drops to 0 the pipeline usually dries up a month later.",
    # ------------------------------------------------------------------ research
    "research_keyword": (
        "Optional one-off search phrase. Leave it **blank** to use the titles from your configuration (up to three are sent to "
        "each site; sites searched through their own form submit the keyword saved with their criteria instead, unless "
        "configured to use the titles). Type something to search for that instead, just for this run — your configuration "
        "is not changed.\n\n"
        "*Example:* configured titles are `data analyst, BI analyst`; typing `analytics engineer` searches only that phrase."
    ),
    "research_sites": (
        "Which of the **enabled** sites to query this time. Remove a site to skip it for one run (it stays enabled in the "
        "configuration).\n\n*Example:* keep only `Remotive` while you tune keywords, then add the others back."
    ),
    "research_strict": (
        "**On:** listings that fail any preference (location, salary, job type, schedule, workplace, excluded word, age, "
        "minimum skills) are hidden.\n\n**Off:** everything is shown, ranked; failing rows are marked and the `filter_notes` "
        "column says why (e.g. `location 'Europe'; salary out of range`).\n\n*Tip:* switch it off when a search returns nothing."
    ),
    "research_run": (
        "Queries the selected sites in parallel, merges and de-duplicates the listings, applies your preferences and ranks "
        "them by match score. Sites that refuse access or return nothing are listed above the results with the reason.\n\n*Example:* with Remotive + Jobicy enabled and titles `data analyst`, one click fetches both, drops roles outside your salary/location, and ranks the rest."
    ),
    "research_pick": (
        "Choose listings to copy into the Jobs tracker with status **Saved**. Already-tracked listings (same URL) are skipped.\n\n"
        "*Example:* pick `3. Data Analyst — Acme` and `7. BI Analyst — Zeta`, then press *Save selected*."
    ),
    "research_save": "Copies the selected listings into the Jobs page (status Saved, priority Medium). Title, company, location, salary, job type, link and description are kept.\n\n*Example:* saving `Data Analyst — Acme` creates a Jobs row with status Saved and an Acme entry under Target companies.",
    "research_export": "Downloads the current result table (all columns, including score, matched skills and filter notes) as CSV for a spreadsheet.\n\n*Example:* open `search_results.csv` in Excel to sort by `score` or share the list.",
    "org_name": "Company you want to target, even without a live opening. Creates an entry under *Target companies*.\n\n*Example:* `Northline Health`",
    "org_industry": "Free text used only for your own filtering and notes.\n\n*Example:* `Healthcare / Life Sciences`",
    "org_location": "Where the company is based or where its team you care about sits.\n\n*Example:* `Philadelphia, PA`",
    "org_website": "Careers page or homepage, so it is one click away when you research.\n\n*Example:* `https://northline.example.com/careers`",
    "org_why": "Why this company matters to you — mission, people you know there, products you use. Shown in the table.\n\n*Example:* `Uses dbt + Snowflake; Maria from my cohort is on the analytics team.`",
    "org_add": "Saves the company. If it already exists (same name) nothing changes.\n\n*Example:* adding `Northline Health` twice keeps the first entry's notes.",
    "note_topic": "Short title for a research note.\n\n*Example:* `Salary bands for analyst roles in Philly`",
    "note_body": "The note itself: links, numbers, names, what you learned. Stored locally in the SQLite file.\n\n*Example:* `Glassdoor: analyst II $82–96k. Recruiter said band tops at $100k. Ask about bonus.`",
    "note_save": "Stores the note with a timestamp. Notes are listed newest first.\n\n*Example:* save `Interview questions — Acme` today and it appears at the top of the list with today's timestamp.",
    # ------------------------------------------------------------------ jobs
    "job_title": "Role title as written in the listing. Used in the Jobs table, in outreach labels and for duplicate checks together with the URL.\n\n*Example:* `Senior Data Analyst` (keep the seniority word — it helps you compare roles later).",
    "job_org": "Company or organisation. Also creates it under *Target companies* if new.\n\n*Example:* `Acme Health`",
    "job_location": "City/region or `Remote`. Used for your own filtering in the Jobs table.\n\n*Example:* `Philadelphia, PA` or `Remote — US`",
    "job_workplace": "Remote / Hybrid / On-site, or Unknown if the listing does not say.\n\n*Example:* `Hybrid` for '3 days in the Philadelphia office'.",
    "job_status": (
        "Where the role is in your pipeline. Moves the bar on the Dashboard.\n\n"
        "Saved → Researching → Applied → Recruiter Screen → Interview → Final Round → Offer → Accepted; "
        "Rejected / Withdrawn / On Hold close or pause it.\n\n*Example:* set **Applied** the day you submit; the application date is recorded."
    ),
    "job_priority": "High / Medium / Low — your own ranking for where to spend time. Filterable in the table.\n\n*Example:* `High` for a referral at a target company, `Low` for a long-shot application.",
    "job_salary": "Pay as published or as you learned it, free text.\n\n*Example:* `$85k–$105k` or `£45,000 + bonus`",
    "job_url": "Link to the listing. Used to detect duplicates, so paste the canonical job page URL.\n\n*Example:* `https://boards.example.com/jobs/123`",
    "job_next_action": "The single next thing you owe this role. Appears under *Due and overdue* on the Dashboard when it has a date.\n\n*Example:* `Follow up with recruiter`",
    "job_next_date": "When that next action is due. Roles due within 7 days show on the Dashboard; past dates count as overdue.\n\n*Example:* applied on Monday → set next action `Follow up` for the following Monday.",
    "job_notes": "Anything else: interviewer names, questions asked, your impressions.\n\n*Example:* `Phone screen with Dana (recruiter) 10/14: team of 5, Looker, hybrid 2 days.`",
    "job_add": "Adds the role to the tracker. A listing URL already in the tracker is rejected to avoid duplicates.\n\n*Example:* title `Data Analyst`, organization `Acme`, status `Applied` → the role appears in the table with today's application date.",
    "job_load_sample": "Inserts two example roles and one example contact so you can see how the pages look. Delete them afterwards.\n\n*Example:* click once to get `Data Analyst @ Northline Health` (Applied) and `Product Operations Associate @ Harbor & Co` (Researching).",
    "job_filter_status": "Show only roles in these statuses. Defaults to the open ones (everything except Rejected, Withdrawn, Accepted).\n\n*Example:* choose only `Interview` and `Final Round` to see what needs preparation.",
    "job_filter_priority": "Show only roles with these priorities.\n\n*Example:* keep only `High` when you have an hour and want the best use of it.",
    "job_filter_text": "Case-insensitive search in title and company.\n\n*Example:* `analyst` or `acme`",
    "job_export": "Downloads the rows currently shown (after the filters above) as CSV.\n\n*Example:* filter to `Applied` and export `jobs.csv` to keep a dated record of applications.",
    "job_pick": "Choose the role to update below. The list shows `id: title @ company`.\n\n*Example:* `7: Data Analyst @ Acme` — the form below fills with that role's current values.",
    "job_date_applied": "Date you submitted the application. Only stored when *Record an application date* is ticked.\n\n*Example:* tick *Record an application date* and set `2026-10-13` on the day you submit.",
    "job_mark_applied": "Tick to store the application date shown on the left; untick to clear it.\n\n*Example:* untick if you saved the role as Applied by mistake and have not actually applied.",
    "job_save": "Writes the changes to the role and refreshes the table.\n\n*Example:* change status to `Interview`, set next action `Prepare SQL case study` due Friday, press Save — the Dashboard's due list updates.",
    "job_delete": "Removes the selected role permanently (no undo).\n\n*Example:* remove the two sample roles once you have added real ones.",
    # ------------------------------------------------------------------ contacts
    "contact_name": "Person's full name. Becomes selectable on the Outreach page once saved.\n\n*Example:* `Alex Rivera`",
    "contact_org": "Where they work. Also creates the organisation under *Target companies* if new.\n\n*Example:* `Northline Health`",
    "contact_title": "Their job title.\n\n*Example:* `Technical Recruiter`",
    "contact_relationship": "How you know them or what they can do for you.\n\n*Example:* `Recruiter`, `classmate`, `hiring manager`",
    "contact_email": "Email address, if you have it.\n\n*Example:* `alex.rivera@northline.example.com`",
    "contact_linkedin": "Profile URL; shown as a link in the table.\n\n*Example:* `https://www.linkedin.com/in/alexrivera`",
    "contact_notes": "Context: how you met, what they care about, what you promised.\n\n*Example:* `Met at PyData Philly; offered to refer me to the analytics team.`",
    "contact_add": "Saves the contact. They become selectable when logging outreach.\n\n*Example:* add `Alex Rivera / Northline Health / Recruiter` and they appear in the *Contact* dropdown on Outreach.",
    "contact_export": "Downloads all contacts as CSV.\n\n*Example:* `contacts.csv` imports cleanly into Google Sheets or a CRM.",
    "contact_remove_pick": "Choose a contact to delete with the button below.\n\n*Example:* `3: Alex Rivera`.",
    "contact_delete": "Deletes the selected contact permanently. Outreach entries that mention them are kept.\n\n*Example:* deleting a recruiter who left the company; past outreach to them stays in the log.",
    # ------------------------------------------------------------------ outreach
    "outreach_contact": "Who you contacted. Pick from Contacts; their organisation is filled in automatically.\n\n*Example:* `Alex Rivera (Northline Health)` fills the organisation automatically.",
    "outreach_role": "The tracked role this message is about, if any. Lets the log show which roles are getting attention.\n\n*Example:* `Data Analyst @ Northline Health` links this note to that role.",
    "outreach_channel": "How you reached out: Email, LinkedIn, Phone, Referral, InMail, Event, Other.\n\n*Example:* `LinkedIn` for a connection note, `Email` for a thank-you after an interview.",
    "outreach_outcome": "What happened so far: Sent, Replied, Meeting set, No response, Not interested, Referred. *Sent* and *No response* drive the follow-up reminders.\n\n*Example:* start with `Sent`; change to `Replied` or `Meeting set` when it happens, which removes the reminder.",
    "outreach_subject": "One line on what the message was about.\n\n*Example:* `Intro note about the analyst role`",
    "outreach_date": "When you sent it or spoke.\n\n*Example:* `2026-10-13` for a message sent today.",
    "outreach_follow_up": "When to chase if you hear nothing. Shows under *Follow-ups coming due* three days ahead of this date.\n\n*Example:* sent Monday → follow up the next Monday; the entry appears under *Follow-ups coming due* from Friday.",
    "outreach_use_follow_up": "Untick if no follow-up is needed (e.g. they already replied).",
    "outreach_notes": "What you sent and what they said — paste the key lines so the next message has context.\n\n*Example:* `Asked for 15 min about the analytics team. They replied: happy to chat Thursday 3pm.`",
    "outreach_log": "Saves the entry. If a contact was chosen, the organisation comes from their record; otherwise from the role.\n\n*Example:* logging `LinkedIn · Alex Rivera · Intro note · Sent · follow up 10/20` adds a row and a reminder.",
    "outreach_export": "Downloads the whole outreach log as CSV.\n\n*Example:* `outreach.csv` to review how many touches led to replies.",
    # ------------------------------------------------------------------ config: sidebar & general
    "cfg_reload": "Discards the on-screen state and re-reads the JSON file. Use it after editing the file by hand or with the CLI (`python -m jobsearch_config …`).\n\n*Example:* you ran `python -m jobsearch_config enable adzuna` in a terminal; press this to see Adzuna enabled here.",
    "cfg_quick_toggle": (
        "Fast way to choose which sites are searched: the selected ones become **enabled**, all others disabled. "
        "Press *Apply quick toggle* to save. A site on a host that forbids automated access cannot be enabled — the save is refused.\n\n"
        "*Example:* select `Remotive`, `Jobicy`, `Adzuna` and press Apply."
    ),
    "cfg_quick_apply": "Saves the enabled/disabled state chosen above. The main dashboard picks it up on its next search.\n\n*Example:* after selecting `Remotive` and `Adzuna`, press Apply — Jobicy becomes disabled and stays configured.",
    "site_enabled": "Only enabled sites are queried. Disable instead of removing when you want to keep the options (e.g. an API key).",
    "site_name": "Label shown in the result table's `source` column and in the sites list.\n\n*Example:* `Adzuna (US)`",
    "site_max": "Upper limit of listings taken from this site per search, after de-duplication. Lower it to be gentle on small boards.\n\n*Example:* `20`",
    "site_notes": "Your own reminder about this site — why it is here, its rate limits, where the key came from.\n\n*Example:* `Key created 2026-10 under my personal Adzuna account; 250 calls/day.`",
    "site_save": "Writes the site settings to the configuration file after validation (e.g. required options, forbidden hosts).",
    "site_remove": "Deletes this site from the configuration. Listings already saved in the tracker are unaffected.\n\n*Example:* remove a company careers feed after you have applied there.",
    "site_remove_unknown": "Deletes this entry; its provider is not known to this version of the app.\n\n*Example:* a site with provider `foo` left by a newer version of the app.",
    # ------------------------------------------------------------------ search-form panel (web-page sites)
    "sf_find": (
        "Opens the site in a headless browser, fills in **this form exactly as you filled it here** (keyword box, dropdown "
        "choices), presses the site's *Find jobs* button and lists the jobs that came back — unfiltered, so you see what the "
        "site returns. If the page matches no known version of the form, a new version is learned from the page and this "
        "panel switches to its controls. Nothing is saved until you press *Save criteria*. A site that searches through its "
        "web form is only added / enabled when this test returns at least one job.\n\n*Example:* keyword `data analyst`, "
        "categories `Engineering`, countries `United States` → 12 jobs → *Save criteria & enable site*."
    ),
    "sf_keyword_mode": (
        "**Off (default):** every search submits the form exactly as saved here — the keyword you typed, or an empty box if "
        "you left it blank, so the site's dropdown filters alone decide. **On:** the keyword box is filled with your preferred "
        "titles from *Job preferences* instead, one search per title (up to three). A keyword typed on the Research page "
        "always replaces either for that one run.\n\n*Example:* off + empty keyword + categories `Engineering` → all "
        "Engineering jobs; on + titles `data analyst, BI analyst` → two searches, one per title."
    ),
    "sf_refresh": (
        "Loads the page once (in a real browser when Playwright is installed) to read the dropdown choices the site offers "
        "right now and to check which version of the site's form is live. Use it when a choice you expect is missing.\n\n"
        "*Example:* Yahoo adds a new brand — after refreshing it appears in *Select brands*."
    ),
    "sf_save": (
        "Writes the criteria you entered, the form version that matched the live page (including a version learned from the "
        "page, kept under `search_form.learned`) and the passing test (time, number of jobs) into the site's `search_form` "
        "option, and enables the site. From now on every search fills in the site's form "
        "with these criteria (your titles replace the keyword).\n\n*Example:* saved with `categories: Engineering`; the next "
        "search on the Research page submits Yahoo's form with *Engineering* ticked."
    ),
    "inv_add_form": (
        "Adds the page as a web-page site driven by the matched search-form strategy — **disabled**. Open its card, fill in "
        "the mirrored form and press Find jobs; the site is enabled only when that test returns jobs.\n\n*Example:* "
        "yahooinc.com/careers/search.html → site `yahooinc-com-form` using `yahoo-careers@2`."
    ),
    "add_form_strategy": (
        "Which site's search-form implementation to use. *Detect from the URL* picks it by host name; choose one explicitly "
        "for a mirror or test copy of the site. Each strategy may have several versions — the newest whose fingerprint matches "
        "the live page is used.\n\n*Example:* `Yahoo careers` for `yahooinc.com/careers/search.html`."
    ),
    "add_form_url": (
        "Address of the page that shows the search form. Searches load this page, fill in the form and read the result list.\n\n"
        "*Example:* `https://www.yahooinc.com/careers/search.html`"
    ),
    "add_form_id": "Unique slug for the site: lowercase letters, digits, '-' or '_'.\n\n*Example:* `yahoo-careers`",
    "add_form_name": "Label shown in the result table's `source` column and in the sites list.\n\n*Example:* `Yahoo careers (search form)`",
    "add_form_create": (
        "Creates the site **with the criteria and the passing test you just ran** and enables it. The button only appears "
        "after *Find jobs* returned at least one job; a failed test never adds a site.\n\n*Example:* after a test that "
        "returned 12 jobs, press it once — the site shows up under Job sites as validated."
    ),
    "admin_token": (
        "The administrator token of this installation — the value of the `JOB_SEARCH_ADMIN_TOKEN` environment variable on the "
        "machine running this dashboard. Only someone who knows it can change administrator settings or lift a terms-based "
        "block.\n\n*Example:* the value your administrator put in `.env`."
    ),
    "admin_web_search_toggle": (
        "Whether the app may read web pages, drive search forms and render pages in a headless browser at all. Off = every "
        "web-page site is skipped in searches and cannot be tested or added; feeds and API providers keep working.\n\n"
        "*Example:* untick before an audit; tick again once the policy review is done."
    ),
    "admin_web_search_save": (
        "Verifies the token, signs the new state with it and saves. A state written without the token (e.g. by editing the "
        "JSON) does not verify and counts as off.\n\n*Example:* token + tick → web-page search ON, signed and dated."
    ),
    "search_scan_hours": (
        "How often the main dashboard re-checks every custom / careers-platform site for access policy (robots.txt, HTTP "
        "401/403, terms recorded in the registry) and disables the ones that are no longer compliant. 0 switches the "
        "automatic scan off (cron can still run `python -m jobsearch_sources compliance-scan`).\n\n*Example:* `24` = daily."
    ),
    "compliance_scan_now": (
        "Re-checks every custom and careers-platform site right now against robots.txt, HTTP access and the registry policy, "
        "updates the registry, and disables sites that are no longer compliant (a dated note is added to the site).\n\n"
        "*Example:* a board that started answering 403 last week is disabled and listed with the reason."
    ),
    "reg_override_lift": (
        "Administrator only: marks the selected host active again, e.g. after its terms of use changed to allow automated "
        "access. Requires the administrator token.\n\n*Example:* lift `example-board.com` after they published an API policy."
    ),
    "reg_override_block": (
        "Administrator only: records that the selected host prohibits robots/scrapers by its terms. The block is sticky — no "
        "successful fetch lifts it — and its sites are disabled by the next compliance scan.\n\n*Example:* block "
        "`someboard.com` after reading its terms of service."
    ),
    "site_test": (
        "Makes **one live request** with the saved settings and shows up to 8 listings — no filtering, so you see what the site "
        "actually returns. The result is written to the *Site registry* (status, active flag, timestamps). Needs internet.\n\n"
        "*Example:* after entering an Adzuna key, test it; `0 listings` with no error usually means the keyword/location is too narrow."
    ),
    "add_builtin_provider": "Ready-made adapters. *needs key* means you must obtain free credentials from the provider's site and enter them (or reference them as `${ENV_VAR}`).\n\n*Example:* `Adzuna — needs key` (free at developer.adzuna.com) vs. `Remotive — no key`.",
    "add_builtin": "Adds the provider with default options, enabled. Open its card below to set options such as country or category.\n\n*Example:* add `The Muse`, then set its Category to `Data and Analytics` on its card.",
    "add_custom_type": (
        "- **RSS / Atom feed** – the board publishes a feed (lightest).\n"
        "- **Generic JSON API** – a documented JSON endpoint; you map fields.\n\n"
        "Web pages are added elsewhere: *Web page with a search form* for sites searched through their form, *Investigate a "
        "careers URL* for plain pages and careers platforms.\n\n*Example:* `https://weworkremotely.com/categories/remote-data-jobs.rss` → RSS; "
        "`https://boards.example.com/api/jobs` → JSON."
    ),
    "add_custom_id": "Short unique identifier used in the config file and CLI. Lowercase letters, digits, `-` or `_`.\n\n*Example:* `acme-careers`",
    "add_custom_name": "Display name shown in results.\n\n*Example:* `Acme careers feed`",
    "add_custom_url": (
        "Feed or API address to fetch. Placeholders are replaced at search time: `{keyword}` (your titles), `{location}` (first "
        "non-remote location), `{limit}`.\n\n*Examples:* `https://example.com/jobs.rss?q={keyword}` · "
        "`https://boards.example.com/api/jobs?search={keyword}&per_page={limit}`"
    ),
    "add_custom_skip": (
        "Normally the URL is fetched once before saving to confirm it is really a feed / JSON / page and that the host allows "
        "access. Tick only if the site is temporarily down. Hosts marked forbidden in the Site registry are still refused.\n\n*Example:* a university board that is offline for maintenance tonight."
    ),
    "add_custom_create": "Checks the URL (unless skipped), records the host in the Site registry and saves the site enabled. An RSS site given a web page switches to the feed that page advertises.\n\n*Example:* creating `acme-careers` with `https://careers.example.com/` stores `https://careers.example.com/jobs.rss` if that page advertises the feed.",
    "inv_url": (
        "Careers page or job-board address to investigate. The app checks robots.txt, fetches the page, detects the platform "
        "behind it (Workday, Greenhouse, Lever, …), counts JobPosting data and job links, and lists the search-form controls.\n\n"
        "*Example:* `https://www.yahooinc.com/careers/`"
    ),
    "inv_render": (
        "Also load the page in headless Chromium so JavaScript-built search bars and results are inspected (needs Playwright). "
        "Slower, but required for most modern careers sites.\n\n*Example:* tick for yahooinc.com, whose search bar is built by JavaScript."
    ),
    "inv_run": (
        "Runs the investigation (1–2 live requests) and writes the outcome to the Site registry. Shows a verdict — crawlable, "
        "forbidden (robots.txt or HTTP 403), unreachable — and a ready-to-add site suggestion.\n\n*Example:* for a Workday site it "
        "suggests a 'Workday careers site' entry with tenant and site filled in."
    ),
    "inv_add": (
        "Saves the suggested site exactly as shown (enabled). Open its card afterwards to add filters or a search recipe.\n\n"
        "*Example:* adds `yahooinc-com-workday` with tenant `ouryahoo`, site `careers`."
    ),
    # ------------------------------------------------------------------ config: preferences
    "pref_titles": (
        "Role phrases you want. The first three are sent as search queries to sites that support keywords; all of them raise a "
        "listing's score when found in its title (+40 for the whole phrase).\n\nType a phrase and press Enter.\n\n"
        "*Example:* `data analyst`, `business intelligence analyst`, `analytics engineer`"
    ),
    "pref_industries": (
        "Optional. Mapped to a site category where one exists (e.g. *Data / Analytics* → Remotive `data`, Jobicy `data-science`) "
        "and worth +10 in ranking when the listing mentions it.\n\n*Example:* `Healthcare / Life Sciences`"
    ),
    "pref_skills": (
        "Tools and skills. Each one found in a listing (whole-word, so `R` does not match `Tableau`) adds +10 to its score, up to +50; "
        "the `matched_skills` column shows which.\n\n*Example:* `SQL`, `Python`, `Tableau`, `dbt`"
    ),
    "pref_min_skills": "Drop listings matching fewer than this many of your skills. `0` = skills only affect ranking.\n\n*Example:* with skills `SQL, Python, Tableau` and `2` here, a listing mentioning only SQL is hidden.",
    "pref_exclude": "Listings containing any of these words (whole-word, in title or description) are dropped.\n\n*Example:* `clearance`, `unpaid`, `senior`",
    "pref_locations": (
        "Cities, states, countries or regions you accept. Synonyms are understood (`United States` ≈ `USA`/`US`; `UK` ≈ `United Kingdom`). "
        "A city implies its country for remote roles, so with only `Philadelphia, PA` a remote job open to `USA` still passes. "
        "Add `Remote` to accept remote roles from **any** region. Empty = anywhere.\n\n*Example:* `United States`, `Philadelphia, PA`"
    ),
    "pref_workplaces": "Allowed work modes. Remove *On-site* to see only remote and hybrid roles. The first one listed gets a small ranking bonus.\n\n*Example:* `Remote` + `Hybrid` hides fully on-site roles.",
    "pref_job_types": (
        "Employment types you accept: Permanent (direct hire, incl. 'full-time employee'), Contract, Temporary, Freelance, Internship. "
        "Sites that support it (Adzuna, Reed) receive this as a server-side filter.\n\n*Example:* `Permanent` + `Contract`"
    ),
    "pref_schedules": "Full-time and/or part-time. Listings stating the other schedule are dropped.\n\n*Example:* keep only `Full-time` to drop part-time listings.",
    "pref_include_unknown": "Many feeds omit the employment type. Ticked: such listings are kept. Unticked: only listings that state an accepted type survive.\n\n*Example:* unticked, an RSS item with no 'Full-time' or 'Contract' wording is hidden.",
    "pref_salary_min": "Lowest acceptable pay in the currency/period on the right. `0` = no minimum. A listing passes if its published range overlaps yours.\n\n*Example:* `85000`",
    "pref_salary_max": "Highest pay you want to see (useful to skip director-level roles). `0` = no maximum.\n\n*Example:* `140000`",
    "pref_salary_currency": "Currency of the figures on the left. Listings in another currency count as *unlisted*.\n\n*Example:* `USD` — a listing quoting `£45,000` is then treated as unlisted.",
    "pref_salary_period": "Per year / month / day / hour. Listings quoting hourly or daily pay are converted (×2080 h, ×260 d, ×12 m) before comparing.\n\n*Example:* minimum `40` with *per hour* equals about `83,200` per year.",
    "pref_include_unlisted": "Most boards do not publish pay. Ticked: such listings are kept (marked `salary unlisted`). Unticked: only listings with pay inside your range survive.\n\n*Example:* unticked with minimum `85,000`: only listings publishing a range reaching $85k remain.",
    "pref_posted_within": "Ignore listings older than this many days (by published date). `0` = any age. Unknown dates are kept.\n\n*Example:* `14`",
    "pref_save": "Validates and writes the preferences to the configuration file. The main dashboard uses them on its next search.\n\n*Example:* add `dbt` to skills, save, and the next search shows `dbt` under `matched_skills` where it appears.",
    # ------------------------------------------------------------------ config: registry
    "reg_host": "A host the app has checked. *inactive* = forbids automated access; such hosts cannot be added or enabled and are skipped.\n\n*Example:* `indeed.com (inactive)` or `careers.example.com (active)`.",
    "reg_url": "URL used for a re-check — defaults to the last URL checked for this host.\n\n*Example:* `https://careers.example.com/jobs`",
    "reg_recheck": "Makes one live request to the URL, updates the row (status, active, checks, updated time). A host that now allows access becomes active again.\n\n*Example:* re-check `board.example.com` after they lifted a block; if it answers 200 the row turns active.",
    "reg_remove": "Deletes the row. The host will be re-evaluated from scratch the next time a site on it is tested or searched.\n\n*Example:* remove `old-board.example.com` after the site shut down.",
    "reg_recheck_all": "Re-checks every host in the table, one request each, with a progress bar. Useful after a long break.\n\n*Example:* 12 hosts ≈ 12 requests, about 20 seconds.",
    "reg_seed": "Re-adds the built-in starting entries (Indeed, Monster, Craigslist, …) if you removed some.\n\n*Example:* you removed `glassdoor.com` by mistake — this puts it back as inactive.",
    "reg_download": "Downloads the registry as JSON for backup or for another machine.\n\n*Example:* copy `site_registry.json` next to the config on your laptop.",
    # ------------------------------------------------------------------ config: search behaviour
    "search_timeout": "Seconds to wait for one request before giving up on that site for this run.\n\n*Example:* `15`; raise to `40` for slow boards.",
    "search_user_agent": (
        "Sent with every request so sites can identify the app; its product token (`JobSearchDashboard`) is what robots.txt rules "
        "are matched against. Keep it honest — it is not used to impersonate a browser.\n\n*Example:* `Mozilla/5.0 (compatible; JobSearchDashboard/2.0; personal job tracker)`."
    ),
    "search_strict": "Default for the *Strict filters* switch on the Research page: hide listings that fail a preference (on) or show them ranked lower with the reason (off).\n\n*Example:* off by default = every search shows hidden-by-filter rows greyed with their reason.",
    "search_dedupe": "When the same listing URL comes back from several sites, keep only the first copy.\n\n*Example:* a Remotive listing that Jobicy also syndicates appears once.",
    "search_save": "Writes these settings to the configuration file.\n\n*Example:* raise the timeout to `40` for a slow board, save, search again.",
    # ------------------------------------------------------------------ config: review
    "review_download": "Downloads the full configuration JSON. Secrets written as `${ENV_VAR}` stay as placeholders, so the file is safe to share.\n\n*Example:* `job_search_config.json` committed to your dotfiles repo with `${ADZUNA_APP_KEY}` instead of the key.",
    "review_upload": "Choose a JSON file exported from this dashboard (or written by hand) to replace the current configuration. It is validated before the *Import now* button is enabled.\n\n*Example:* the file you downloaded on another machine.",
    "review_import": "Replaces the configuration with the uploaded file (a `.bak` of the previous one is kept).\n\n*Example:* importing a file with 5 sites replaces your current 3.",
    "review_reset": "Starts the reset: the next button asks for confirmation.\n\n*Example:* click, read the warning, then confirm — or navigate away to cancel.",
    "review_reset_confirm": "Overwrites the configuration with the defaults (Remotive + Jobicy enabled, 'data analyst'). A `.bak` copy of the current file is kept.\n\n*Example:* after confirming, Adzuna keys and custom sites are gone from the config (still in the `.bak`).",
}

# Section headers (st.header / st.subheader help).
SECTIONS: dict[str, str] = {
    "dash_pipeline": "How many roles sit in each status. Move a role with *Status* on the Jobs page; the bar updates immediately.",
    "dash_due": "Open roles whose *Next action date* is within 7 days or already past, oldest first. Clear them by updating the role on the Jobs page.",
    "dash_recent": "The eight most recent outreach entries. Log new ones on the Outreach page.",
    "research_targets": "Companies you want to work for, whether or not they have an opening today. Independent of the site search.",
    "research_notes": "Free-form research notes (salary bands, interview questions, market observations) stored locally.",
    "jobs_update": "Pick a role and change its status, salary, dates, next action or notes. Everything else (title, link) stays as saved.",
    "outreach_due": "Outreach marked *Sent* or *No response* whose follow-up date is within 3 days or past. Update the outcome once they reply.",
    "outreach_log": "Every outreach entry, newest first.",
    "cfg_sites": "Which job sites are searched and how. Built-in providers have ready-made adapters; custom sites read a feed, a JSON API or a web page.",
    "cfg_investigate": "One-stop check of a careers URL: robots.txt verdict, reachability, platform (public API?), page data and search-form controls, plus a ready-to-add site suggestion. Results are recorded in the Site registry.",
    "cfg_add_site": "Add a built-in provider from the catalog, a web page searched through its own form (tested first), or a custom feed / JSON API by URL (checked once before saving). Plain pages and careers platforms come from *Investigate a careers URL*.",
    "cfg_prefs": "What kind of jobs you want. Titles and skills steer search and ranking; location, salary, job type, schedule and workplace are filters.",
    "pref_role": "Role titles, industries, skills and words to avoid — what the job *is*.",
    "pref_location": "Where the job may be and which work modes you accept.",
    "pref_employment": "Permanent / contract / temporary, full- or part-time, and what to do when a listing does not say.",
    "pref_salary": "Pay range in one currency and period; listings are converted to yearly for comparison.",
    "pref_freshness": "How old a listing may be.",
    "pref_summary": "The filters exactly as they will be applied on the next search, in plain words.",
    "site_search_form": (
        "Mirror of the website's own search form. Fill it in as on the site and press Find jobs to test; the site joins the "
        "job search only after a test returns jobs. Shows the strategy (site-specific implementation) and form version in use."
    ),
    "reg_override": "Administrator-only changes to the registry: lift or impose terms-based blocks. Live checks never lift a terms block.",
    "cfg_compliance": "Daily re-check of every configured custom/platform site against the access policy (terms, robots.txt, HTTP 401/403); non-compliant sites are disabled.",
    "cfg_admin": "Administrator switch for all web-page based searching; signed with the administrator token so nobody else can change it.",
    "cfg_registry": "Per-host memory of every live check: who allows automated access and who does not. Updated by tests, URL checks and searches.",
    "cfg_search": "Cross-site behaviour of the search engine: timeouts, strictness, de-duplication, how the app identifies itself.",
    "cfg_review": "Validation results, the raw JSON, import/export and reset.",
    "review_export": "Download the configuration to back it up, share it, or move it to another machine.",
    "review_import": "Replace the configuration with a JSON file. It is validated first; import is only enabled when there are no errors.",
    "review_json": "The configuration exactly as stored on disk.",
    "review_danger": "Irreversible-ish actions (a .bak copy is always kept).",
    "app_cfg_sites": "The sites the main app will query and their options (secrets masked). Edit them in the configuration dashboard.",
    "app_cfg_prefs": "The preferences the main app applies on the next search.",
    "app_cfg_policy": "Whether web-page based search is allowed (administrator switch) and when the configured sites were last scanned for access-policy compliance.",
    "app_cfg_registry": "Hosts the app has checked; inactive hosts are skipped. Managed in the configuration dashboard's Site registry tab.",
}


def sec(key: str) -> str:
    return SECTIONS[key]


# Column tooltips for result / data tables (dataframe column_config help).
COLUMNS: dict[str, str] = {
    "score": "Relevance 0–100+: title match (+40/+30/+12), matched skills (+10 each, max +50), industry (+10), salary in range (+10), explicit location (+10), freshness (+10/+5).",
    "passes": "Ticked when the listing satisfies every preference. Only shown with strict filters off.",
    "title": "Role title as the site publishes it (e.g. `Senior Data Analyst`).",
    "organization": "Hiring company or organisation as the site reports it (e.g. `Acme Health`).",
    "location": "Location text from the listing (e.g. `USA`, `Worldwide`, `Philadelphia, PA`).",
    "workplace": "remote / hybrid / onsite, or blank when the listing does not say.",
    "job_type": "permanent / contract / temporary / freelance / internship, normalised from the site's wording; blank = not stated.",
    "salary_text": "Pay as published (or composed from min–max and currency).",
    "matched_skills": "Which of your configured skills appear in the title, description or tags.",
    "published": "Date the listing was posted (YYYY-MM-DD).",
    "source": "Display name of the site the listing came from (e.g. `Remotive`, `Acme careers`).",
    "url": "Link to the original listing on the site; click to open it in a new tab.",
    "filter_notes": "Why the listing failed (strict off) or soft remarks such as `salary unlisted`.",
    "site": "Display name of the site this row describes (e.g. `Remotive`).",
    "fetched": "Listings the site returned before your preferences were applied.",
    "kept": "Listings from this site that passed the preferences.",
    "seconds": "Time the site took to answer this search, in seconds (slow sites may need a higher timeout).",
    "status": "`ok`, an adapter note (e.g. `rendered 2 page(s) in a browser`), or the error that stopped the site.",
    "host": "Host name without `www.` (e.g. `indeed.com`); seed rows also match their sub-hosts.",
    "active": "Unticked = the host forbids automated access; it cannot be added or enabled and is skipped in searches.",
    "checks": "How many live checks have been recorded for this host (tests, URL checks, searches).",
    "created": "When the row was first created (first check or built-in seed), local time.",
    "updated": "When the row was last updated by a live check, local time.",
    "message": "Explanation or warning saved on the last check of this host.",
    "enabled": "Whether the site is queried by searches (edit in the configuration dashboard).",
    "provider": "Adapter used for the site, e.g. `Adzuna`, `RSS / Atom feed`, `Web page (HTML)`.",
    "max results": "Cap on listings taken from this site per search, after de-duplication.",
    "options": "Provider options as configured (API keys and secrets are masked with ••••) — or, for form controls, the dropdown's choices.",
    "id": "Internal row number in the local database; use it to tell roles with the same title apart.",
    "priority": "Your own High / Medium / Low ranking of how much the role matters.",
    "date_applied": "Date you recorded the application (blank = not applied yet).",
    "next_action": "The single next thing you owe this role, e.g. `Follow up with recruiter`.",
    "next_action_date": "When that next action is due; dates in the past count as overdue.",
    "next_action_date_due": "Due date of the next action; past dates are overdue.",
    "name": "Contact's full name as entered on the Contacts page.",
    "email": "Email address of the contact, if known.",
    "linkedin": "LinkedIn profile link of the contact; click to open it.",
    "relationship": "How you know the contact or what they can do (recruiter, classmate, hiring manager…).",
    "notes": "Free-text notes entered with the record.",
    "activity_date": "Date the outreach happened (message sent or call made).",
    "channel": "How you reached out: Email, LinkedIn, Phone, Referral, InMail, Event, Other.",
    "contact_name": "Who was contacted (a person from the Contacts page).",
    "subject": "One-line purpose of the message, e.g. `Intro note about the analyst role`.",
    "outcome": "Current result: Sent / Replied / Meeting set / No response / Not interested / Referred.",
    "follow_up_date": "When to chase if there is no reply; drives the *Follow-ups coming due* list.",
    "job_title": "The tracked role this outreach relates to, if any (title @ company).",
    "industry": "Industry of the company, free text (e.g. `Healthcare / Life Sciences`).",
    "website": "Company website or careers page; click to open it.",
    "created_at": "When the note was written (timestamp).",
    "topic": "Short title of the research note.",
    "body": "Full text of the research note.",
    "kind": "Type of control on the page: input, select (native dropdown), combobox (custom dropdown), checkbox, button.",
    "label": "Visible text / placeholder / aria-label of the control — use it as the target in a search recipe, e.g. `{\"placeholder\": \"Key words\"}`.",
    "css hint": "Best-effort CSS selector for the control, for recipes that prefer `{\"css\": ...}` targets.",
    "last HTTP": "HTTP status code of the last check: 200 = OK, 403 = access refused, 0 = no response.",
    "reason": "Why the host is inactive: `terms` (its terms prohibit robots — sticky, administrator only), `robots` (robots.txt), `http` (401/403/429); blank when active.",
    "compliant": "Ticked when the site may still be accessed automatically (terms, robots.txt and HTTP access all allow it).",
    "disabled": "Ticked when this scan disabled the site because it is no longer compliant.",
    "last URL": "Exact URL used for the last check of this host.",
}


def h(key: str) -> str:
    """Tooltip text for ``key``; raises if missing so gaps are caught early."""
    return HELP[key]


def column_config(columns, **overrides):
    """Build a Streamlit ``column_config`` dict giving every column a tooltip.

    ``overrides`` map column name -> a ``st.column_config.*`` object (already
    carrying its own ``help``) or a plain label string.
    """
    import streamlit as st

    config = {}
    for name in columns:
        if name in overrides:
            value = overrides[name]
            config[name] = st.column_config.Column(value, help=COLUMNS.get(name, "")) if isinstance(value, str) else value
        else:
            config[name] = st.column_config.Column(help=COLUMNS.get(name, name))
    return config
