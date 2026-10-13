# Configuration reference

The Job Search Dashboard is driven by one JSON file, by default
`config/job_search_config.json` (override with `JOB_SEARCH_CONFIG`). Three
things can write it — they are interchangeable and can be used at different
stages of the lifecycle:

| Stage | Tool |
|---|---|
| Development / day-to-day | **Configuration dashboard** – `streamlit run config_dashboard.py --server.port 8502` |
| Deployment / automation | **CLI** – `python -m jobsearch_config …` (exit code 2 on validation errors, good for CI) |
| Provisioning | **Hand-written / mounted file** – copy `config/job_search_config.example.json`, mount it into the container |

The main app (`app.py`) only reads the file. It checks the file's modification
time on every interaction, so a save in the configuration dashboard is picked
up by the next search without restarting anything. Every write is atomic and
keeps a `.bak` copy of the previous version.

## 1. Job sites (`sites`)

Each entry selects a **provider adapter** plus options:

```json
{
  "id": "adzuna",            // unique slug: lowercase letters, digits, - or _
  "provider": "adzuna",      // adapter key (see table below)
  "name": "Adzuna",          // display name shown in results as "source"
  "enabled": true,           // only enabled sites are searched
  "max_results": 25,         // cap per site (1–200)
  "options": { "country": "us", "app_id": "${ADZUNA_APP_ID}", "app_key": "${ADZUNA_APP_KEY}" },
  "notes": "free text"
}
```

### Secrets

Any string option may contain `${ENV_NAME}`; it is replaced from the process
environment **at search time**, never written back to the file. The
configuration dashboard shows whether the variable is set. Put the values in
`.env` (loaded by `scripts/run_*.sh` and `docker compose`) or your secret
store.

### Providers

| `provider` | Options | What is pushed to the site |
|---|---|---|
| `remotive` | `category` (Remotive slug; blank = derived from your first industry) | keyword, category |
| `jobicy` | `geo`, `industry` | keyword (tag), region, industry |
| `arbeitnow` | `pages` | nothing — keyword filtered locally |
| `remoteok` | — | first skill as tag |
| `themuse` | `category`, `level`, `api_key`, `pages` | category, location, level |
| `himalayas` | — | nothing |
| `adzuna` | `country`, `app_id`*, `app_key`* | keyword, location, salary min/max, permanent/contract, full/part-time, max age |
| `reed` | `api_key`*, `distance_miles` | keyword, location, salary, permanent/contract/temp, full/part-time |
| `usajobs` | `api_key`*, `email`* | keyword, location, min salary, date posted |
| `greenhouse` / `lever` / `ashby` / `smartrecruiters` / `recruitee` / `workable` | company identifier (`board` / `site` / `company_id` / `company` / `subdomain`), display name, platform filters | platform API filters (department, team, keyword/city for SmartRecruiters) |
| `workday` | `url` or `tenant` + `site` (+ `host`), `facets` (by visible name), `details` | keyword (`searchText`), facets |
| `html` | `url`*, `pages`, `render`, `actions`, `form_values`, `follow_links`, `max_detail_pages`, `delay_seconds`, `link_pattern`, `item_selector` + field selectors, `workplace` | `{keyword}` / `{location}` / `{page}` placeholders if present; otherwise filtered locally |
| `rss` | `url`*, `title_format`, `workplace` | `{keyword}` / `{location}` placeholders in the URL if present; otherwise filtered locally |
| `json` | `url`*, `items_path`, `mapping`, `headers`, `workplace` | `{keyword}` / `{location}` / `{limit}` placeholders if present |

\* required when the site is enabled.

The "Test this site now" button in the configuration dashboard fetches live
data with the saved options so you can confirm a key or a feed URL works.

#### Which sites can be added?

Three custom types cover almost any source:

| Type | Use when | How it reads listings |
|---|---|---|
| **RSS / Atom feed** | the board or careers page publishes a feed | parses items; lightest on the site |
| **Generic JSON API** | the site has a documented JSON endpoint | dotted-path field mapping |
| **Web page (HTML)** | there is only a normal web page | schema.org `JobPosting` data embedded in the page → job links followed to detail pages → CSS selectors you configure |

When you create a custom site the dashboard fetches the URL once and tells
you what it found (feed items, JobPosting objects, job-looking links, or
nothing). It refuses URLs that answer **HTTP 403** (automated access blocked),
that robots.txt disallows, or that are the wrong kind (e.g. a feed added as a
page), and it switches an RSS site to the feed a page advertises.

#### Site registry

`config/site_registry.json` (or `JOB_SEARCH_REGISTRY`) keeps one row per host:

| Field | Meaning |
|---|---|
| `host` | lowercased host without `www.`; seed rows use the registrable domain and match sub-hosts |
| `status` | `ok` · `forbidden` · `empty` (reachable, no listings) · `error` (network) |
| `active` | `false` when the host forbids automated access — HTTP 401/403, robots.txt disallow, known terms |
| `message` | the warning shown to the user |
| `source` | `builtin` · `probe` (Test / URL check) · `search` · `manual` |
| `created_at`, `updated_at`, `checks`, `last_url`, `last_status_code` | audit trail |

The row is updated on **every** check: *Test this site now*, the URL check
when a custom site is created, every search run, and *Re-check* in the
Site registry tab. Consequences of `active = false`:

* the site cannot be created (even with "skip the URL check"),
* an enabled site on that host fails validation, so it cannot be saved enabled,
* searches skip it and show the saved warning,
* *Test this site now* / *Re-check* still make one live request, so the row recovers as soon as the site allows access again.

The built-in seed (Indeed, Monster, Craigslist, LinkedIn, Glassdoor, ZipRecruiter,
Dice, SimplyHired, CareerBuilder) is only a starting point; re-checking
overwrites it with live results, and rows can be removed.

#### Access policy

The web-page reader does what a person's browser does where the site allows
it — including executing JavaScript in real Chromium — and it identifies
itself. It does **not** spoof fingerprints, solve CAPTCHA/bot-protection
challenges, rotate identities, or retry after a 401/403/429. `robots.txt`
is a crawler courtesy, not permission to scrape; the 403 a site returns is
its answer, and circumventing a block is what made scraping unlawful in
*Craigslist v. 3Taps* (CFAA) — *hiQ v. LinkedIn* protected only public data
gathered without circumvention. Much of Indeed's inventory is available
through the **Adzuna** provider (free API key); The Muse and USAJOBS cover
on-site US roles; Reed covers the UK.

#### Web page (HTML)

```json
{ "id": "acme-careers", "provider": "html", "name": "Acme careers", "enabled": true,
  "options": { "url": "https://careers.example.com/jobs?q={keyword}&page={page}", "pages": 2,
               "follow_links": "auto", "max_detail_pages": 15, "delay_seconds": 1 } }
```

What happens on every page:

1. `robots.txt` of the host is fetched (cached an hour) and the URL is checked
   with RFC 9309 rules (wildcards, longest match, `Crawl-delay`). Disallowed
   URLs are never requested.
2. The page is fetched with the identifying `User-Agent`
   (`Mozilla/5.0 (compatible; JobSearchDashboard/2.0; …)`, robots token
   `JobSearchDashboard`) and at least `delay_seconds` between requests to
   the same host.
3. `<script type="application/ld+json">` blocks are parsed for
   `JobPosting` objects (also inside `@graph` and `ItemList`) → title,
   company, location (incl. `TELECOMMUTE`), salary with unit, employment
   type, dates, URL. Expired postings (`validThrough` in the past) are
   dropped.
4. If `item_selector` is set, each matching element is read with the field
   selectors (`title_selector`, `link_selector`, `company_selector`,
   `location_selector`, `salary_selector`, `date_selector`,
   `job_type_selector`).
5. If the page yielded nothing (or `follow_links` = `always`), job-looking
   links on the same host are followed — up to `max_detail_pages` — and each
   detail page is parsed for `JobPosting` data, falling back to Open Graph /
   `<h1>` / meta description. `link_pattern` (regex) narrows which links
   count as jobs.
6. Without a `{keyword}` placeholder, results are filtered locally by your
   titles.

**JavaScript-rendered pages.** With Playwright installed
(`pip install -r requirements-browser.txt && python -m playwright install chromium`)
the `render` option controls a real headless Chromium: `auto` (default)
loads a page in the browser only when the plain fetch looks
JavaScript-rendered, `always` renders every page (listing and detail),
`never` sticks to plain HTTP. Rendering runs in a child process, sends the
same identifying User-Agent, skips images/fonts/media, and treats a
401/403/429 (including bot-protection challenge pages) as access denied —
the run stops and the host is recorded as forbidden. Without Playwright,
such pages are reported as "appears to render results with JavaScript".
Needs the `beautifulsoup4` package.

#### Custom RSS / Atom feed

```json
{ "id": "acme-careers", "provider": "rss", "name": "Acme careers", "enabled": true,
  "options": { "url": "https://careers.example.com/jobs.rss?q={keyword}",
               "title_format": "company: title", "workplace": "hybrid" } }
```

`title_format` tells the adapter how to split the company out of titles like
`Acme: Data Analyst` (`company: title`) or `Data Analyst at Acme`
(`title at company`). Categories are mapped to job types when they say
things like "Full-time", "Contract", "Temporary".

#### Custom JSON API

```json
{ "id": "example-json-api", "provider": "json", "name": "Example API", "enabled": true,
  "options": {
    "url": "https://jobs.example.com/api/search?q={keyword}&limit={limit}",
    "items_path": "data.jobs",
    "headers": { "Authorization": "Bearer ${EXAMPLE_API_TOKEN}" },
    "mapping": {
      "title": "name", "organization": "employer.name", "location": "where",
      "url": "link", "description": "body", "salary_min": "pay.min", "salary_max": "pay.max",
      "salary_currency": "pay.currency", "job_type": "kind", "workplace": "mode",
      "industry": "category", "tags": "skills", "published": "posted", "id": "id"
    } } }
```

Mapping values are dotted paths into each item (`company.name`,
`locations.0.name`, `tags.*.name`). `items_path` points to the list of
items (blank if the response is already a list).

## 2. Job preferences (`preferences`)

| Key | Type | Meaning |
|---|---|---|
| `titles` | list | Role phrases. The first three are sent as search queries to keyword-capable sites; all are used for ranking. |
| `industries` | list | From the built-in list or free text. Mapped to Remotive/Jobicy categories where possible; +10 score when matched. |
| `skills` | list | Each skill found in a listing adds +10 (max +50). Whole-word match, so `R` or `C` are safe. |
| `min_skill_matches` | int | Drop listings matching fewer skills (0 = ranking only). |
| `exclude_keywords` | list | Drop listings containing any of these words. |
| `locations` | list | Cities, states, countries, regions. Synonyms are understood (`United States` ≈ `USA`, `UK` ≈ `United Kingdom`…). Add `Remote` to accept remote roles from any region; otherwise a remote role must be open worldwide or to one of your locations. Empty = anywhere. |
| `workplaces` | list of `remote`, `hybrid`, `onsite` | Allowed workplace modes. |
| `job_types` | list of `permanent`, `contract`, `temporary`, `freelance`, `internship` | Allowed employment types. |
| `schedules` | list of `full_time`, `part_time` | Allowed schedules. |
| `include_unknown_job_type` | bool | Keep listings that do not state a type (most feeds don't). |
| `salary.minimum` / `salary.maximum` | int or null | Range in `salary.currency` per `salary.period` (`year`, `month`, `day`, `hour`). A listing passes if its range overlaps yours; hourly/daily/monthly pay is converted to yearly for comparison. |
| `salary.include_unlisted` | bool | Keep listings with no pay information (or a different currency). |
| `posted_within_days` | int or null | Drop listings older than this. Unknown dates pass. |

City preferences imply their country for remote roles: with only
`Philadelphia, PA` listed, a remote job "open to USA" still passes (an
on-site job in New York does not).

### How filtering and ranking work

1. **Hard filters** — exclude keywords, job type, schedule, workplace,
   location, salary, age, minimum skills. Unknown values pass (configurable
   for job type and salary) so a site that omits a field does not disappear.
2. **Score** — title match (+40 phrase / +30 all words / +12 any word),
   skills (+10 each), industry (+10), salary in range (+10), explicit location
   match (+10), preferred workplace (+5), freshness (+10 ≤ 7 days, +5 ≤ 14).
3. **Strict filtering** (`search.strict_filtering`, also a toggle on the
   Research page) hides listings that fail a hard filter. Turn it off to see
   everything ranked, with the failing reason in the `filter_notes` column.
   When every fetched listing is removed, the Research page says which
   filters removed them (e.g. `location (9), job type (2)`).

## 3. Search behaviour (`search`)

| Key | Default | Meaning |
|---|---|---|
| `timeout_seconds` | 15 | Per-request timeout. Sites are queried in parallel. |
| `strict_filtering` | true | See above. |
| `dedupe_by_url` | true | Drop the same listing found on several sites. |
| `user_agent` | `Mozilla/5.0 (compatible; JobSearchDashboard/2.0; personal job tracker)` | Sent with every request; the product token is used for robots.txt groups. |

## 4. Validation

`python -m jobsearch_config validate` (and the **Review & backup** tab) reports
errors (bad site ids, unknown providers, missing required options, salary
min > max, …) and warnings (no sites enabled, `${ENV}` not set, …). The
dashboard refuses to save a configuration with errors; the CLI exits with
code 2.

## 5. Programmatic use

```python
import jobsearch_config as jc
import jobsearch_sources as js

config = jc.load_config()                     # honours JOB_SEARCH_CONFIG
report = js.run_search(config)                # all enabled sites, configured titles
for job, match in report.results:
    print(match.score, job.title, job.organization, job.salary_text, match.matched_skills)
print(report.errors, report.attributions)
```

`jobsearch_config` has no third-party dependencies and `jobsearch_sources`
uses only the standard library, so both can be reused from a cron job,
notebook or another UI.
