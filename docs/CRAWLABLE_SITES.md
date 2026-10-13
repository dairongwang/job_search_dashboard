# Which job sites allow robots, and how to get their job data

This is the investigation behind the *Investigate a careers URL* function and
the site providers. It was written without live access (the development
sandbox is offline), so the per-site facts come from how these platforms
document themselves; **run the investigator on your machine to get a live
verdict for any URL** — it records robots.txt, reachability, platform and
form controls, and writes the result to the Site registry.

```bash
python -m jobsearch_sources investigate https://www.yahooinc.com/careers/ --render
# or: Configuration dashboard → Job sites → Investigate a careers URL
```

## 1. Three kinds of job sites

| Kind | Examples | Robots / terms | How the app reads them |
|---|---|---|---|
| **Aggregators with public APIs** | Remotive, Jobicy, Arbeitnow, Remote OK, The Muse, Himalayas, Adzuna, Reed, USAJOBS | APIs published for third parties; some need a free key | built-in providers |
| **Company career sites on an ATS platform** | Yahoo (Workday), Airbnb (Greenhouse), Netflix (Lever), Notion (Ashby), Bosch (SmartRecruiters), many SMEs (Recruitee, Workable) | The platform publishes a **job-board API meant for exactly this** (widgets, aggregators); robots.txt of the career host allows job pages | *Company careers platform* providers — structured JSON, no JavaScript, no scraping |
| **Big job boards** | Indeed, Monster, LinkedIn, Glassdoor, ZipRecruiter, Dice, Craigslist | No public feed/API; **terms prohibit automated access**; servers answer scripts with HTTP 403 even though robots.txt may allow search engines | not supported — seeded as inactive in the Site registry; Adzuna carries much of the same inventory |

Anything else (a company's own careers page, a university board, a niche
board) is handled by the **Web page** provider: JobPosting structured data,
job links, CSS selectors, browser rendering and — new — **search-form
recipes** that drive the page's own search like a person.

## 2. Career-site platforms and their public job endpoints

| Platform | Fingerprint in the page | Endpoint the provider uses | Auth | Data |
|---|---|---|---|---|
| Workday | `<tenant>.wd<N>.myworkdayjobs.com/<site>` | `POST /wday/cxs/<tenant>/<site>/jobs` with `searchText` + `appliedFacets`; `GET …/job/<path>` for details | none | title, location, posted, facets (country, job family, time type…), description |
| Greenhouse | `boards.greenhouse.io/<board>` | `boards-api.greenhouse.io/v1/boards/<board>/jobs?content=true` | none | title, location, department, office, description |
| Lever | `jobs.lever.co/<site>` | `api.lever.co/v0/postings/<site>?mode=json` | none | title, team, location, workplace type, commitment, salary range |
| Ashby | `jobs.ashbyhq.com/<board>` | `api.ashbyhq.com/posting-api/job-board/<board>` | none | title, employment type, remote flag, compensation summary |
| SmartRecruiters | `careers.smartrecruiters.com/<Company>` | `api.smartrecruiters.com/v1/companies/<Company>/postings?q=` | none | title, city/country, employment type, department, industry |
| Recruitee | `<company>.recruitee.com` | `<company>.recruitee.com/api/offers/` | none | title, location, remote, employment type, salary |
| Workable | `apply.workable.com/<subdomain>` | `workable.com/api/accounts/<subdomain>?details=true` | none | title, location, remote, employment type |
| iCIMS, SuccessFactors, Taleo, Oracle HCM, Phenom, Eightfold, Jobvite, BambooHR, Teamtailor, Personio | various | no public API (or feed only) | — | Web page provider (+ browser rendering); Teamtailor/Personio via their feeds |

These endpoints are what the career sites' own pages call, or are documented
for partners; they return structured JSON and need no JavaScript. The
investigator detects the platform from links/scripts on the careers page and
fills in the identifiers.

## 3. Yahoo — worked example

`https://www.yahooinc.com/careers/` shows a search bar — *Key words*,
*Select job categories*, *Select countries*, *Select brands*, **Find jobs** —
and its job listings are hosted on Workday (`ouryahoo.wd5.myworkdayjobs.com/careers`).
Two ways to search it, both shipped in `config/job_search_config.example.json` (disabled):

**A. Workday API (recommended)** — site `yahoo-workday`: your titles become
`searchText`; filters are given by their visible names and resolved to
Workday's facet ids automatically:

```json
"facets": {"locationCountry": "United States of America", "jobFamilyGroup": ["Engineering"], "timeType": "Full time"}
```

If a name does not exist, the run reports the available choices. Job pages
are fetched for the description, time type and country.

**B. Search-form recipe** — site `yahoo-careers-form`: a Web page site with
`render: always` and these steps, executed in headless Chromium exactly as
a person would:

```json
[
  {"fill":  {"placeholder": "Key words"}, "value": "{keyword}"},
  {"click": {"text": "Select job categories"}}, {"click": {"option": "{category}"}}, {"press": "Escape"},
  {"click": {"text": "Select countries"}},      {"click": {"option": "{country}"}},  {"press": "Escape"},
  {"click": {"text": "Select brands"}},         {"click": {"option": "{brands}"}},   {"press": "Escape"},
  {"click": {"button": "Find jobs"}},
  {"wait": "networkidle"},
  {"click": {"button": "Load more"}, "repeat": 3, "optional": true, "snapshot": true}
]
```

with `form_values = {"category": "Engineering", "country": "United States", "brands": ["Yahoo", "Yahoo Finance"]}`
(`{keyword}` comes from your titles; a list value repeats its step per item).
Results are read from each snapshot; job links are followed to their pages
for JobPosting data. Run *Investigate* with *Render in browser* first: it
lists the real control labels and dropdown options so the recipe matches the
live page.

### Step vocabulary

| Step | Meaning |
|---|---|
| `{"fill": T, "value": "…"}` | click the field and type |
| `{"select": T, "value": "…"}` | choose an option of a native `<select>` by label (or value) |
| `{"click": T}` | click (custom dropdown toggles, options, buttons) |
| `{"check": T}` | tick a checkbox / radio |
| `{"press": "Enter"}` (+ optional `"target"`) | key press |
| `{"wait": T}` / `"networkidle"` / `{"seconds": 2}` | wait for an element, network idle, or a pause |
| `{"scroll": "bottom"}` | scroll down (infinite lists) |
| modifiers | `"repeat": N`, `"snapshot": true` (capture results after the step), `"optional": true` (ignore a missing element), `"timeout_ms"`, `"settle_ms"` |

Targets `T`: a CSS string or `{"css"}`, `{"text"}` (partial visible text),
`{"exact_text"}`, `{"placeholder"}`, `{"label"}`, `{"button"}` (button or link
name), `{"option"}` (listbox option or its text), `{"role", "name"}`, `{"testid"}`.

## 4. Rules the app applies to every site

1. `robots.txt` is fetched and evaluated (RFC 9309) before any request; disallowed URLs are never requested.
2. Requests carry an identifying User-Agent and respect a delay / `Crawl-delay`.
3. A 401/403/429 — including a bot-protection challenge page shown to the real browser — ends the run and marks the host **forbidden** in the Site registry; the app does not disguise itself or solve challenges (see *Craigslist v. 3Taps*).
4. Every check (investigate, test, search) updates the registry row with timestamps, status and active flag; forbidden hosts cannot be added or enabled.
