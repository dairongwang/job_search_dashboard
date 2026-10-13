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
| **Web page (HTML)** | — | — | any careers/board page: schema.org JobPosting data, job-link following, CSS selectors; JavaScript-rendered pages are loaded in a real headless browser (optional Playwright); **search-form recipes** drive the page's own keyword / category / country / brand controls and its *Find jobs* button; honours robots.txt |

Anything a site cannot filter server-side is filtered locally after fetching, so results behave the same across sites. See [docs/CONFIGURATION.md](docs/CONFIGURATION.md) for details.

### Investigating a careers URL

`python -m jobsearch_sources investigate <url> [--render]` (or *Investigate a careers URL* in the configuration dashboard) reports whether robots.txt allows the page, whether the host answers scripts, which platform powers it, what job data the page carries, and the search-form controls it offers — and suggests a ready-to-add site. See [docs/CRAWLABLE_SITES.md](docs/CRAWLABLE_SITES.md) for the findings and a Yahoo walkthrough.

### Site registry and access policy

Every custom site (feed, JSON, web page) is checked against — and recorded in — a **site registry** (`config/site_registry.json`): one row per host with `status`, `active`, `message`, `created_at`, `updated_at`, check count and last URL. Rows are updated by every *Test this site now*, every URL check on creation, and every search. A host that forbids automated access (HTTP 401/403, robots.txt disallow, known terms) becomes **inactive**: the saved warning is shown, the site cannot be added or enabled, and searches skip it until a re-check succeeds (Configuration dashboard → *Site registry*).

The web-page reader is as capable as a person's browser where the site allows it: real Chromium rendering for JavaScript boards, job-link following, pagination, polite delays. It **does not** spoof browser fingerprints, solve CAPTCHA/bot-protection challenges, or retry under another identity after a 403 — that is the conduct courts have treated as unauthorized access (*Craigslist v. 3Taps*), and a 403 is the site's answer. Indeed, Monster, LinkedIn, Glassdoor and Craigslist are seeded as inactive for that reason; Adzuna carries much of the same inventory and is a supported provider.

Optional browser rendering: `make browser` (or `pip install -r requirements-browser.txt && python -m playwright install chromium`); Docker: `WITH_BROWSER=1 docker compose build`.

## Run it locally

```bash
cd job_search_dashboard
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt  # or requirements.txt / requirements-config.txt separately

# Terminal 1 – operation dashboard (http://localhost:8501)
scripts/run_app.sh                 # = streamlit run app.py --server.port 8501

# Terminal 2 – configuration dashboard (http://localhost:8502), whenever you want to change settings
scripts/run_config.sh              # = streamlit run config_dashboard.py --server.port 8502
```

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
| `ADZUNA_APP_ID`, `ADZUNA_APP_KEY`, `REED_API_KEY`, `USAJOBS_API_KEY`, `USAJOBS_EMAIL`, `THEMUSE_API_KEY` | — | only if those sites are enabled |

## Project layout

```
app.py                      operation dashboard (Streamlit)
config_dashboard.py         configuration dashboard (Streamlit, separate process)
jobsearch_config/           config library: schema, provider catalog, load/save, validation, CLI  (no 3rd-party deps)
jobsearch_sources/          search engine: provider adapters, preference filters, ranking, orchestrator, robots.txt, HTML extraction
config/                     job_search_config.json + site_registry.json (yours, git-ignored) + job_search_config.example.json
tests/                      pytest suite incl. headless Streamlit UI tests
scripts/                    run_app.sh / run_config.sh (+ .bat)
Dockerfile, docker-compose.yml, Makefile, .env.example
docs/CONFIGURATION.md       configuration reference
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
