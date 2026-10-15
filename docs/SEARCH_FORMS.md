# Search-form strategies — searching a site through its own search form

Many career sites have no feed or API: jobs are found by filling in the
site's **search form** (a keyword box, *Select job categories* / *Select
countries* / *Select brands* dropdowns, a **Find jobs** button) and reading
the list that appears. Every site implements that form differently, and the
same site changes it over time. This document describes how the app handles
it: the design (Strategy pattern + versioned registry), the user flow in the
configuration dashboard (the mirrored test form and the "no jobs → not added"
rule), what a search does at run time, and how to add a strategy for a new
site or a new version of an existing one.

```
jobsearch_sources/searchforms/
    base.py       SearchFormStrategy (the interface), FormField, FormChanged
    yahoo.py      YahooCareersFormV2 / YahooCareersFormV1   ← one site, two versions of its form
    recipe.py     RecipeStrategy — declarative strategy from JSON (no code needed)
    registry.py   lookup by host / family / version, resolution against the live page
    runner.py     executes a strategy in the headless browser and parses the results
    service.py    detect(), test_form(), mark_validated() … used by the dashboards and CLI
```

## 1. Design

### Strategy pattern, one object per site *and* per form version

`SearchFormStrategy` is the interface; each concrete strategy encapsulates
everything that is specific to one site's form:

| Method / attribute | What it encapsulates | Yahoo careers, version 2 |
|---|---|---|
| `family`, `version`, `since`, `hosts`, `form_hint` | identity: which site, which layout, when it was observed | `yahoo-careers`, `2`, `2026-02`, `yahooinc.com`, `form#collapseFilterJobs` |
| `fields()` | the controls of the form *as the user sees them* — label, kind (`text` / `select` / `multiselect` / `checkbox`), known choices | *Search by keywords*; *Select job categories* (18 choices); *Select countries* (20); *Select brands* (8); *Select experience* (6) |
| `fingerprint()` / `absent()` | CSS selectors that must (not) exist for this version to apply | `form#collapseFilterJobs`, `input[name=keyword]`, `#JCDropdown`, `#JLDropdown`, `#JBDropdown`, `button#search-page-find-jobs-mobile` |
| `live_options(soup)` | how to read the choices the live page offers right now | the `value` of every checkbox in `#JCDropdown`, `#JLDropdown`, … |
| `steps(criteria, pages)` | how to fill in and submit the form, as browser steps | expand the collapsed form, type the keyword, open each dropdown, tick the chosen boxes, press **Find jobs**, wait for `#tableJobListing` to change, press **Load more** |
| `parse_results(soup, url)` | how to read the result list — a strategy that implements it **owns** the results: an empty list means the site found nothing, and the provider never falls back to reading the page generically (that would turn the page's own navigation links into "jobs") | `#tableJobListing tr.jobTitle` → title + link, brand, location |
| `no_results_message(soup)` | the site's own "nothing matches" text, surfaced in the outcome | `#tableJobListing .errorMsg` → *"We currently do not have any jobs matching your criteria…"* |
| `viewport` | browser size the form needs | tablet width (the filter form lives in a `.mobileTabletOnly` container) |

The rest of the app never looks inside a strategy: the configuration
dashboard renders `fields()`, the provider calls `steps()` and
`parse_results()`, the registry uses `fingerprint()`. Adding a site is adding
one class (or one JSON recipe); nothing else changes.

### Versioning — the same site changes its form over time

Strategies sharing a `family` are versions of one site's form. The registry
keeps them **newest first** and, at run time, the headless browser checks the
fingerprints *on the live page* before touching anything:

1. the configured version is tried first (`search_form.version`),
2. then the other versions of the family, newest first,
3. the first whose fingerprint matches is used. If it is not the configured
   one, the search still works and the outcome notes *"the search form
   changed: configured version 2 … version 1 did [match] and was used
   instead"*, so the user knows to re-validate.
4. If **none** matches, the app **learns a new version from the live page**
   (next section) and uses it. Only when that is impossible too (the page has
   no search-like form, or learning is switched off with
   `"learn": false`) does the run raise `FormChanged` instead of silently
   returning nothing: *"the site's search form no longer matches any known
   version — tried: yahoo-careers@2 (2026-02), yahoo-careers@1 (2026-02) …"*.
   The Research page shows it as *search form changed* and the site registry
   records it.

Yahoo ships with two layouts: **v2** — the *Filter jobs* form
(`form#collapseFilterJobs`, submit `button#search-page-find-jobs-mobile`)
on `careers/search.html`; **v1** — the landing-page search bar on
`careers/` (`form[action="/careers/search.html"]`, `#search-keyword`,
`name="categories[] / locations[] / brands[]"`, submit
`button#index-page-find-jobs`; submitting navigates to the results page).
Both read the same `#tableJobListing` result table.

### Learning a version from the page (`learn.py`)

`learn_form(soup, url)` inspects the page's `<form>`s (or form-like
containers): the keyword box (name / id / placeholder hints), checkbox and
radio groups (grouped by `name`, labelled by their Bootstrap dropdown toggle,
`<legend>` or heading, options from the labels), native `<select>`s and the
submit button (`type=submit` or a *Find / Search* button). The most
search-like form becomes a recipe spec: `fields` (so the dashboard can
mirror it), a `fingerprint` (its form, keyword box, group containers and
submit button — so the version is recognised next time and told apart from
the next redesign), `steps` (fill, tick, select, submit, *Load more*) and
`"results": {"auto": true}`.

`learned_results(soup, url)` reads the page that comes back: the dominant
group of structurally identical links — a job list is a repeated row with a
link each — scored by job-looking URLs (`/job/`, `JR…`) and results-like
containers, and **never** links inside `nav`/`header`/`footer`/menu
containers. No such group → zero jobs.

The learned version is `auto-N` of the site's family (`yahoo-careers@auto-1`).
The run that learned it uses it immediately (criteria entered for the old
fields are carried over by key, label or identical option sets; the Research
page asks you to re-validate). In the configuration dashboard, *Refresh form
from the site* / *Find jobs* switch the panel to the learned controls;
*Save criteria* stores the spec under `search_form.learned`, selects it as
`version`, and from then on it is resolved like any other version (newest
registered first, then learned ones, the configured one always first).

### Declarative strategies (recipes)

For a site without a Python class, the same interface can be described in
JSON in the site's `search_form` option (`"strategy": "recipe"`): `fields`,
`fingerprint`, `steps` (with `{placeholders}` named after the fields) and
optional `results` selectors (`item_selector` + field selectors, plus an
`empty_selector` for the site's "no results" message; with `item_selector`
set the recipe owns its results, see above). A recipe is a `RecipeStrategy` and gets the
same mirrored test panel, validation rule and change detection (when it has
a fingerprint). The older `actions` + `form_values` options are upgraded to
a recipe automatically.

## 2. Configuration dashboard — test the form before the site is added

Every **Web page (HTML)** site whose host has a strategy (or whose options
carry a `search_form` block) gets a **Search form** panel on its card, and
*Add a site* has a **Web page with a search form** tab. Both show the
**same controls as the website** — for Yahoo: the keyword box and the job
categories / countries / brands / experience dropdowns with the site's
choices — and a **Find jobs** button.

1. Fill in the criteria as you would on the site.
2. **Find jobs** opens the page in headless Chromium, fills in the form with
   exactly those values, presses the site's *Find jobs* button and lists the
   jobs that came back (unfiltered). The panel reports which strategy
   version matched, the total the site reported, and any chosen value the
   live form does not offer.
3. **The site is added / enabled only when the test returned at least one
   job**: the *Add site (validated)* / *Save criteria & enable site* button
   appears only after a passing test. A failing test leaves the
   configuration untouched. The rule is also enforced by validation — an
   enabled form-driven site without a recorded passing test is a
   configuration error (`python -m jobsearch_config validate` exits 2; the
   quick toggle refuses to enable it).
4. **Refresh form from the site** re-reads the live page: which version is
   live and the current dropdown choices (they are also refreshed by every
   test).

What gets saved (`options.search_form`):

```json
{
  "strategy": "yahoo-careers",
  "version": "2",
  "criteria": {"keyword": "data analyst", "categories": ["Engineering"], "countries": ["United States"], "brands": ["Yahoo", "Yahoo Finance"], "experience": []},
  "live_options": {"categories": ["Administration", "…"], "countries": ["…"], "brands": ["…"], "experience": ["…"]},
  "validated": {"at": "2026-03-01T09:12:44", "jobs": 12, "strategy": "yahoo-careers@2", "criteria": {"…": "…"}, "total": 12, "error": ""},
  "learned": [ {"version": "auto-1", "since": "2026-04", "label": "…", "fingerprint": ["…"], "fields": [], "steps": [], "results": {"auto": true}} ],
  "learn": true,
  "keyword_mode": "criteria"
}
```

`keyword_mode`: `criteria` (default) — searches submit the saved keyword as
is; `titles` — your preferred titles go into the keyword box instead.

`learned` holds versions derived from the live page (see above); `version`
may point at one of them. `learn: false` disables learning for the site.

## 3. What a search does (main app, every run)

For each enabled form-driven site, on every search:

1. the page is loaded in headless Chromium (robots.txt checked first, the
   identifying User-Agent sent, 401/403 ends the run — the same access
   policy as every other request);
2. the strategy version is resolved on the live page (section 1);
3. the form is filled in with the **saved criteria — exactly as tested**,
   keyword included (a blank keyword stays blank: the site's own dropdown
   filters do the work). Two exceptions: a keyword typed on the Research
   page replaces it for that run, and a site saved with *"put my preferred
   titles in the keyword box"* (`keyword_mode: titles`) submits your
   configured titles instead, one submission each (up to three);
4. *Find jobs* is pressed, the result list is read (plus *Load more* pages
   up to `pages`), rows become listings (title, link, company, location);
5. with `follow_links = always`, job pages are opened (up to
   `max_detail_pages`) to add description, salary, employment type and
   posting date — Yahoo's Workday job pages carry schema.org JobPosting data;
6. your preferences filter and rank the listings like any other site.

The search outcome (*N site(s) could not be searched*, the per-site status
table) shows strategy notes: rendered pages, a version fallback, or a
*search form changed* error.

## 4. CLI

```bash
python -m jobsearch_sources forms                         # registered strategies, versions, fields
python -m jobsearch_sources forms --site yahoo-careers-form   # a site's strategy, criteria, validation status
python -m jobsearch_sources test-form yahoo-careers-form --keyword "data analyst" \
        --set "countries=United States" --set "brands=Yahoo,Yahoo Finance" --save   # test, and save + enable on success
python -m jobsearch_sources investigate https://www.yahooinc.com/careers/search.html   # reports the matching version
```

## 5. Adding a site, or a new version of a site's form

1. Run *Investigate* (or `python -m jobsearch_sources investigate <url> --render`)
   to see the controls of the form; save the page HTML as a fixture for tests.
2. Write a class in `jobsearch_sources/searchforms/<site>.py`:

```python
class AcmeFormV1(SearchFormStrategy):
    family, version, since = "acme-careers", "1", "2026-04"
    label, hosts = "Acme careers — search form", ("acme.example.com",)
    start_url = "https://acme.example.com/jobs"

    def fields(self):
        return [FormField("keyword", "What", "text", binds="keyword"),
                FormField("team", "Team", "select", ["Engineering", "Sales"])]

    def fingerprint(self):
        return ["form#job-search input[name=q]", "select[name=team]"]

    def live_options(self, soup):
        return {"team": [o.get_text(strip=True) for o in soup.select("select[name=team] option") if o.get("value")]}

    def steps(self, criteria, pages=1):
        crit = self.normalise_criteria(criteria)
        return [{"fill": {"css": "form#job-search input[name=q]"}, "value": crit["keyword"]},
                {"select": {"css": "select[name=team]"}, "value": crit["team"]},
                {"click": {"css": "form#job-search button[type=submit]"}},
                {"wait": "networkidle", "optional": True}]

    def parse_results(self, soup, base_url):
        return [{"title": a.get_text(strip=True), "link": urljoin(base_url, a["href"])} for a in soup.select("ul.results a[href]")]
```

3. Register it in `registry.py` (`register(AcmeFormV1())`). A **new version**
   of an existing site is a second class with the same `family`, a higher
   `version` and its own fingerprint/steps — keep the old one so pages that
   still show the old layout keep working, and so a redesign is reported
   rather than guessed.
4. Or, without code, describe it as a recipe in the site's `search_form`
   option (section 1).

### Step vocabulary (browser)

| Step | Meaning |
|---|---|
| `{"fill": T, "value": "…"}` | click the field and type |
| `{"select": T, "value": "…"}` | choose an option of a native `<select>` by label (or value) |
| `{"click": T}` / `{"check": T}` | click / tick |
| `{"press": "Enter"}` (+ `"target"`) | key press |
| `{"wait": T}` / `"networkidle"` / `{"seconds": 2}` | wait for an element, network idle, or a pause |
| `{"remember": T}` … `{"wait_change": T}` | store an element's content, later wait until it changed (pages that pre-render a result list) |
| `{"scroll": "bottom"}` | scroll down (infinite lists) |
| modifiers | `"repeat": N`, `"snapshot": true` (capture results after the step), `"optional": true`, `"timeout_ms"`, `"settle_ms"`, `"force": true` (operate a control hidden by the responsive layout through the DOM) |

Targets `T`: a CSS string or `{"css"}`, `{"text"}`, `{"exact_text"}`,
`{"placeholder"}`, `{"label"}`, `{"button"}`, `{"option"}`, `{"role", "name"}`,
`{"testid"}`.

## 6. Installation of the headless browser

`playwright` is in `requirements.txt` / `requirements-config.txt`.
`scripts/setup.sh|bat`, the run scripts, `make install` and the Docker image
run `python -m jobsearch_sources setup-browser`, which installs the package
and downloads Chromium when missing (idempotent). The app also installs them
on first use (`browser.available()` → `ensure_installed()`), so a search or a
*Find jobs* test never fails for lack of setup; set
`JOB_SEARCH_AUTO_INSTALL_BROWSER=0` to disable that.

## 7. Tests

`tests/fixtures/yahoo/` holds the real capture of Yahoo's search page
(`live_search_page.html`, used to test fingerprints, option discovery and
result parsing offline) and a JavaScript replica of the form
(`search.html`: collapsed filter form, checkbox dropdowns, results rendered
by script, *Load more*, job pages with JobPosting data) plus an older-layout
page and a redesigned page. `tests/test_searchforms.py` runs offline;
`tests/test_browser.py` and `tests/test_searchform_ui.py` drive the replica
in real Chromium, including the dashboard flows (passing test → enabled,
failing test → not added, version fallback, redesign detection).
