# Job Search Dashboard

A local Python app for finding roles, tracking applications, and logging outreach. Data stays in a SQLite file (`job_search.db`). Nothing is uploaded.

It ships as **two separable dashboards** that share one JSON configuration file:

| | Operation dashboard (`app.py`) | Configuration dashboard (`config_dashboard.py`) |
|---|---|---|
| Purpose | Search listings, track jobs, contacts, outreach | Choose **which job sites** to search and **what kind of jobs** you want |
| Port (default) | 8501 | 8502 |
| Needs | `requirements.txt` | `requirements-config.txt` (Streamlit only) |
| Writes | `job_search.db` | `config/job_search_config.json` |
| Run it | `scripts/run_app.sh` | `scripts/run_config.sh` |

The operation dashboard only **reads** the configuration (and reloads it automatically when the file changes). You can run the configuration dashboard next to it during day-to-day use, only when needed, on a different host, or not at all — the same file can be edited by the CLI (`python -m jobsearch_config …`), by hand, or provisioned at deployment time.

## What it does

- **Research.** Search every enabled job site with your configured titles, then filter and rank by skills, industry, location, salary range, job type (permanent / contract / temporary / freelance / internship) and schedule. Save matches into the tracker.
- **Jobs.** Pipeline from Saved through Offer, with priority, salary, job type, next action, and notes.
- **Organizations and contacts.** Companies and people tied to roles.
- **Outreach.** Emails, LinkedIn notes, calls, and follow-up dates in one log.
- **Dashboard.** Counts, pipeline, overdue follow-ups, and recent activity.
- **Configuration** (read-only page in the main app; editable in the configuration dashboard).

### Job sites

Built-in adapters, no scraping — public APIs only:

| Site | Key needed | Pushed to the site | Notes |
|---|---|---|---|
| Remotive | no | keyword, category | remote only; asks for attribution and light use |
| Jobicy | no | keyword, region, industry | remote only |
| Arbeitnow | no | — (filtered locally) | Europe-leaning, remote flag |
| Remote OK | no | skill tag | remote only, salary bands |
| The Muse | optional | category, location, level | many on-site/hybrid US roles |
| Himalayas | no | — | structured salary and employment type |
| Adzuna | yes (free) | keyword, location, salary, permanent/contract, full/part-time, age | best fit for on-site roles |
| Reed (UK) | yes (free) | keyword, location, salary, permanent/contract/temp, full/part-time | |
| USAJOBS | yes (free) | keyword, location, minimum salary | US federal |
| **Company careers platforms** — Workday, Greenhouse, Lever, Ashby, SmartRecruiters, Recruitee, Workable | no | keyword / facets where supported | public job APIs of the platforms behind most company careers pages (e.g. Yahoo → Workday); found automatically by *Investigate* |
| **RSS / Atom feed** | — | — | any board or careers page that publishes a feed |
| **Generic JSON API** | — | — | any endpoint, with a dotted-path field mapping |
| **Web page (HTML)** | — | — | any careers/board page: schema.org JobPosting data, job-link following, CSS selectors; JavaScript-rendered pages are loaded in a real headless browser (optional Playwright); honours robots.txt |
| **Web page with a search form** | — | keyword + the form's own dropdowns | sites whose jobs are found through their search form (e.g. Yahoo careers: keywords, job categories, countries, brands, *Find jobs*). A per-site, **versioned search-form strategy** fills in the form on every search; the configuration dashboard shows the same form so you can test it, and the site is only added when the test returns jobs. See [docs/SEARCH_FORMS.md](docs/SEARCH_FORMS.md) |

Anything a site cannot filter server-side is filtered locally after fetching, so results behave the same across sites. See [docs/CONFIGURATION.md](docs/CONFIGURATION.md) for details.

### Searching through a site's own search form

Sites such as Yahoo careers have no feed: you type keywords, pick job categories / countries / brands and press **Find jobs**. The app handles these with **search-form strategies** (`jobsearch_sources/searchforms/`): one strategy class per site, several **versions** per site so each layout of the form is recognised (the version whose fingerprint matches the live page is used — Yahoo ships with the results-page filter form and the landing-page search bar), and declarative JSON *recipes* for sites without a class. When **no version matches** — the site redesigned its form — the app **learns a new version from the live page** (fields, fingerprint, steps, result list), uses it for that search, shows its controls in the dashboard and keeps it under `search_form.learned` once you save it. In the configuration dashboard each such site has a **Search form** panel that mirrors the website's form; *Find jobs* runs it live, and *Add a site → Web page with a search form* only adds the site after a test returned jobs. Every later search fills in the form with the saved criteria (your titles as the keyword). Details, CLI and how to add a site: [docs/SEARCH_FORMS.md](docs/SEARCH_FORMS.md).

```bash
python -m jobsearch_sources forms                                  # strategies, versions, fields
python -m jobsearch_sources test-form yahoo-careers-form --keyword "data analyst" --set "countries=United States" --save
```

### Investigating a careers URL

`python -m jobsearch_sources investigate <url> [--render]` (or *Investigate a careers URL* in the configuration dashboard) reports whether robots.txt allows the page, whether the host answers scripts, which platform powers it, what job data the page carries, and the search-form controls it offers — and suggests a ready-to-add site. See [docs/CRAWLABLE_SITES.md](docs/CRAWLABLE_SITES.md) for the findings and a Yahoo walkthrough.

### Site registry and access policy

Every custom site (feed, JSON, web page) is checked against — and recorded in — a **site registry** (`config/site_registry.json`): one row per host with `status`, `active`, `reason`, `message`, `created_at`, `updated_at`, check count and last URL. Rows are updated by every *Test this site now*, every URL check on creation, every search and the compliance scan. A host that forbids automated access becomes **inactive**: the saved warning is shown, the site cannot be added (not even suggested by *Investigate*), cannot be enabled, and searches skip it. The `reason` matters: `http` (401/403) and `robots` (robots.txt) blocks recover automatically when a re-check succeeds; a **`terms`** block — the site's terms of use prohibit robots/scrapers (Indeed, Monster, LinkedIn, Glassdoor, Craigslist, … are seeded) — is a *policy* decision that no successful fetch can lift; only an administrator override in the *Site registry* tab can.

**Daily compliance scan.** Sites already in the configuration are re-checked every `search.compliance_scan_hours` (default 24) against the same three rules — terms in the registry, robots.txt, HTTP 401/403 — by the main dashboard in the background, on demand (*Site registry → Scan all sites now*) or from cron / Task Scheduler (`python -m jobsearch_sources compliance-scan`). Sites that are no longer compliant are **disabled** with a dated note.

**Administrator switch.** Whether web-page based search (HTML pages, search forms, headless browser) is allowed at all is an administrator setting (*Search behaviour → Web-page based search*, or `python -m jobsearch_config web-search on|off`). It requires the administrator token (`JOB_SEARCH_ADMIN_TOKEN` in the environment of the configuration dashboard) and the stored value is signed with it — a value edited without the token does not verify and counts as **off**. When off, every web-page site is skipped and none can be tested or added; feeds and API providers are unaffected.

The web-page reader is as capable as a person's browser where the site allows it: real Chromium rendering for JavaScript boards, job-link following, pagination, polite delays. It **does not** spoof browser fingerprints, solve CAPTCHA/bot-protection challenges, or retry under another identity after a 403 — that is the conduct courts have treated as unauthorized access (*Craigslist v. 3Taps*), and a 403 is the site's answer. Indeed, Monster, LinkedIn, Glassdoor and Craigslist are seeded as inactive for that reason; Adzuna carries much of the same inventory and is a supported provider.

Browser rendering (Playwright + Chromium) is installed by `scripts/setup.sh` / `make install` and on first use; Docker images include it unless built with `WITH_BROWSER=0`.

## Run it locally

```bash
cd job_search_dashboard
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
scripts/setup.sh                   # Windows: scripts\setup.bat — installs the Python packages AND the headless Chromium

# Terminal 1 – operation dashboard (http://localhost:8501)
scripts/run_app.sh                 # Windows: scripts\run_app.bat

# Terminal 2 – configuration dashboard (http://localhost:8502), whenever you want to change settings
scripts/run_config.sh              # Windows: scripts\run_config.bat
```

Nothing has to be installed by hand for web-form sites: `playwright` is part of `requirements.txt`, the run scripts
(and `make install`) run `python -m jobsearch_sources setup-browser`, which installs the package and downloads
Chromium if either is missing, and the app does the same on first use should a dependency still be absent
(`JOB_SEARCH_AUTO_INSTALL_BROWSER=0` turns that off, e.g. for locked-down hosts).

On first launch a default `config/job_search_config.json` is created (Remotive + Jobicy enabled, "data analyst" titles). Open the configuration dashboard to pick your sites and describe the jobs you want, press **Save**, then search under **Research** in the main app. `config/job_search_config.example.json` shows a fuller example.

### Without the configuration UI (servers, scripts, CI)

```bash
python -m jobsearch_config init                     # write defaults
python -m jobsearch_config sites                    # list sites
python -m jobsearch_config enable remoteok themuse
python -m jobsearch_config disable jobicy
python -m jobsearch_config set-pref titles "data analyst, BI analyst"
python -m jobsearch_config set-pref locations "United States, Philadelphia, PA"
python -m jobsearch_config set-pref job_types "permanent, contract"
python -m jobsearch_config set-pref salary.minimum 85000
python -m jobsearch_config validate                 # exit code 2 on errors
python -m jobsearch_config web-search off --admin-token "$JOB_SEARCH_ADMIN_TOKEN"   # administrator: stop all web-page searching
python -m jobsearch_sources compliance-scan         # daily access-policy check (cron / Task Scheduler); exit 2 if a site was non-compliant
python -m jobsearch_config export > backup.json
python -m jobsearch_config import backup.json
```

### Docker

```bash
cp .env.example .env                         # add API keys if you enable keyed sites
docker compose up app                        # operation only  -> :8501
docker compose --profile config up           # operation + configuration -> :8501 and :8502
docker compose --profile config up config    # configuration dashboard only
```

Both containers mount `./data` (config JSON + SQLite DB). Secrets never need to be in the JSON: write `${ADZUNA_APP_KEY}` and set the variable in `.env` / your secret store.

## Environment variables

| Variable | Default | Used by |
|---|---|---|
| `JOB_SEARCH_CONFIG` | `config/job_search_config.json` | both dashboards, CLI |
| `JOB_SEARCH_REGISTRY` | `site_registry.json` next to the config | both dashboards (site registry) |
| `JOB_SEARCH_DB` | `job_search.db` next to `app.py` | main app |
| `JOB_SEARCH_CONFIG_URL` | `http://localhost:8502` | main app (link to the config UI) |
| `JOB_SEARCH_APP_URL` | `http://localhost:8501` | config UI (link back) |
| `JOB_SEARCH_ADMIN_TOKEN` | — | config UI / CLI: administrator token for the web-page search switch and registry overrides |
| `JOB_SEARCH_AUTO_INSTALL_BROWSER` | `1` | both: set `0` to never install Playwright/Chromium automatically |
| `ADZUNA_APP_ID`, `ADZUNA_APP_KEY`, `REED_API_KEY`, `USAJOBS_API_KEY`, `USAJOBS_EMAIL`, `THEMUSE_API_KEY` | — | only if those sites are enabled |

## Project layout

```
app.py                      operation dashboard (Streamlit)
config_dashboard.py         configuration dashboard (Streamlit, separate process)
jobsearch_config/           config library: schema, provider catalog, load/save, validation, CLI  (no 3rd-party deps)
jobsearch_sources/          search engine: provider adapters, preference filters, ranking, orchestrator, robots.txt, HTML extraction
jobsearch_sources/searchforms/  site-by-site, versioned search-form strategies (Yahoo careers built in; JSON recipes for others)
config/                     job_search_config.json + site_registry.json (yours, git-ignored) + job_search_config.example.json
tests/                      pytest suite incl. headless Streamlit UI tests
scripts/                    run_app.sh / run_config.sh (+ .bat)
Dockerfile, docker-compose.yml, Makefile, .env.example
docs/CONFIGURATION.md       configuration reference
docs/SEARCH_FORMS.md        search-form strategies: design, test panel, run-time behaviour, adding a site
```

## Tooltips

Every control, metric, section header and table column in both dashboards has a `?` tooltip explaining what it does, how it relates to the rest of the app, and a concrete example. The texts live in `ui_help.py` (`HELP` for widgets, `SECTIONS` for headers, `COLUMNS` for tables); provider-specific option help lives with the option definitions in `jobsearch_config/catalog.py`. `tests/test_tooltips.py` fails if any widget is added without one.

## Development

```bash
make dev        # install everything
make test       # pytest (offline – HTTP is stubbed)
make lint       # pyflakes
make validate   # validate the active configuration
```

Job search uses public feeds only. Remotive asks for attribution and light use (at most a few fetches a day); Remote OK asks for a link back to the original listing. Listings from remote boards are remote-leaning; on-site roles come from Adzuna/Reed/The Muse/USAJOBS or your own feeds, or are added by hand.
