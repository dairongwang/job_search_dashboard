"""Catalog of job-site providers the app knows how to talk to.

The catalog is pure data. It drives the configuration dashboard (which
options to show for a site) and documents what each adapter pushes to the
remote API versus what is filtered locally. The adapters themselves live in
``jobsearch_sources.providers``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class OptionSpec:
    key: str
    label: str
    kind: str = "text"  # text | secret | select | int | bool | textarea | json
    default: Any = ""
    help: str = ""
    choices: tuple[str, ...] = ()
    required: bool = False


@dataclass(frozen=True)
class ProviderSpec:
    key: str
    label: str
    description: str
    homepage: str
    requires_key: bool = False
    custom: bool = False  # user supplies the URL (generic adapters)
    platform: bool = False  # company careers platform (ATS): one instance per company, identified by a token
    attribution: str = ""
    server_side: tuple[str, ...] = ()  # preferences the adapter pushes to the API
    options: tuple[OptionSpec, ...] = field(default_factory=tuple)
    default_site: dict[str, Any] | None = None  # suggested site entry for "add from catalog"


REMOTIVE_CATEGORIES = (
    "",
    "software-dev",
    "data",
    "devops",
    "product",
    "design",
    "marketing",
    "sales",
    "customer-support",
    "business",
    "finance-legal",
    "hr",
    "writing",
    "all-others",
)

JOBICY_GEOS = (
    "",
    "usa",
    "canada",
    "uk",
    "europe",
    "emea",
    "apac",
    "latam",
    "australia",
    "germany",
    "france",
    "netherlands",
    "spain",
    "portugal",
    "ireland",
    "india",
    "singapore",
)

JOBICY_INDUSTRIES = (
    "",
    "engineering",
    "data-science",
    "dev",
    "devops",
    "product",
    "design",
    "marketing",
    "sales",
    "customer-support",
    "hr",
    "finance",
    "legal",
    "management",
    "supporting",
    "technical-support",
    "seo",
    "copywriting",
    "business",
    "admin",
)

ADZUNA_COUNTRIES = ("us", "gb", "ca", "au", "de", "fr", "nl", "in", "nz", "sg", "za", "at", "be", "br", "ch", "es", "it", "mx", "pl")

PROVIDERS: dict[str, ProviderSpec] = {
    "remotive": ProviderSpec(
        key="remotive",
        label="Remotive",
        description="Public remote-job feed. No key needed; Remotive asks for attribution and light use.",
        homepage="https://remotive.com/remote-jobs",
        attribution="Listings courtesy of Remotive (https://remotive.com).",
        server_side=("titles/keyword", "category"),
        options=(
            OptionSpec(
                "category",
                "Category",
                "select",
                "",
                "Restricts results to one Remotive category. Blank = all categories, or the category derived from your first "
                "preferred industry (e.g. *Data / Analytics* → `data`). Example: `software-dev` for engineering roles.",
                REMOTIVE_CATEGORIES,
            ),
        ),
        default_site={"id": "remotive", "name": "Remotive", "enabled": True, "max_results": 20},
    ),
    "jobicy": ProviderSpec(
        key="jobicy",
        label="Jobicy",
        description="Public remote-job API with geo and industry filters. No key needed.",
        homepage="https://jobicy.com/jobs-rss-feed",
        attribution="Listings courtesy of Jobicy (https://jobicy.com).",
        server_side=("titles/keyword (tag)", "geo", "industry"),
        options=(
            OptionSpec(
                "geo",
                "Region",
                "select",
                "",
                "Only remote jobs open to candidates in this Jobicy region. Blank = worldwide. Example: `usa` for US-only roles, "
                "`europe` for EU time zones.",
                JOBICY_GEOS,
            ),
            OptionSpec(
                "industry",
                "Industry",
                "select",
                "",
                "Jobicy's own job category. Blank = all, or derived from your first preferred industry (e.g. *Data / Analytics* → "
                "`data-science`). Example: `dev` for software roles, `marketing` for marketing roles.",
                JOBICY_INDUSTRIES,
            ),
        ),
        default_site={"id": "jobicy", "name": "Jobicy", "enabled": True, "max_results": 20},
    ),
    "arbeitnow": ProviderSpec(
        key="arbeitnow",
        label="Arbeitnow",
        description="Europe-leaning job board API (many Germany/EU listings, remote flags, visa sponsorship tags). No key.",
        homepage="https://www.arbeitnow.com/api/job-board-api",
        attribution="Listings courtesy of Arbeitnow (https://www.arbeitnow.com).",
        server_side=("titles/keyword",),
        options=(
            OptionSpec(
                "pages",
                "Pages to fetch",
                "int",
                1,
                "How many result pages to read (about 100 listings each, newest first). Your titles are matched locally, so "
                "`2` gives more chances of a hit at the cost of one extra request. Keep it at 1–3.",
                (),
            ),
        ),
        default_site={"id": "arbeitnow", "name": "Arbeitnow", "enabled": False, "max_results": 30},
    ),
    "remoteok": ProviderSpec(
        key="remoteok",
        label="Remote OK",
        description="Public JSON feed of remote jobs with tags and salary bands. No key; please keep request volume low.",
        homepage="https://remoteok.com/api",
        attribution="Listings courtesy of Remote OK (https://remoteok.com). Please link back to the original listing.",
        server_side=("skills (tags)",),
        options=(),
        default_site={"id": "remoteok", "name": "Remote OK", "enabled": False, "max_results": 30},
    ),
    "themuse": ProviderSpec(
        key="themuse",
        label="The Muse",
        description="Public jobs API covering many on-site and hybrid roles in the US. API key optional for higher limits.",
        homepage="https://www.themuse.com/developers/api/v2",
        attribution="Listings courtesy of The Muse (https://www.themuse.com).",
        server_side=("category", "location", "level"),
        options=(
            OptionSpec(
                "category",
                "Category",
                "text",
                "",
                "One of The Muse's job categories, spelled exactly as on themuse.com. Blank = all. Examples: `Data and Analytics`, "
                "`Software Engineering`, `Project Management`.",
            ),
            OptionSpec(
                "level",
                "Level",
                "select",
                "",
                "Experience level filter applied by The Muse. Blank = all. Example: `Mid Level` to skip internships and senior roles.",
                ("", "Internship", "Entry Level", "Mid Level", "Senior Level", "Management"),
            ),
            OptionSpec(
                "api_key",
                "API key (optional)",
                "secret",
                "",
                "Not required; a free key from themuse.com/developers raises the request limit. You can paste the key or write "
                "`${THEMUSE_API_KEY}` and set that variable in `.env`.",
            ),
            OptionSpec(
                "pages",
                "Pages to fetch",
                "int",
                1,
                "Result pages to read, 20 listings each. Your first preferred location is sent as the location filter. Example: `2` = up to 40 listings.",
                (),
            ),
        ),
        default_site={"id": "themuse", "name": "The Muse", "enabled": False, "max_results": 20},
    ),
    "himalayas": ProviderSpec(
        key="himalayas",
        label="Himalayas",
        description="Remote jobs API with structured salary and employment-type fields. No key.",
        homepage="https://himalayas.app/jobs/api",
        attribution="Listings courtesy of Himalayas (https://himalayas.app).",
        server_side=(),
        options=(),
        default_site={"id": "himalayas", "name": "Himalayas", "enabled": False, "max_results": 30},
    ),
    "adzuna": ProviderSpec(
        key="adzuna",
        label="Adzuna",
        description="Aggregator with strong location, salary and permanent/contract filters. Needs a free app id + key.",
        homepage="https://developer.adzuna.com/",
        requires_key=True,
        attribution="Listings courtesy of Adzuna (https://www.adzuna.com).",
        server_side=("titles/keyword", "location", "salary range", "permanent/contract", "full/part-time", "posted within"),
        options=(
            OptionSpec(
                "country",
                "Country",
                "select",
                "us",
                "Adzuna runs one index per country; pick where you want to work. Salary figures come back in that country's "
                "currency. Example: `us` for the United States, `gb` for the UK, `de` for Germany.",
                ADZUNA_COUNTRIES,
                required=True,
            ),
            OptionSpec(
                "app_id",
                "App ID",
                "secret",
                "${ADZUNA_APP_ID}",
                "Free credential from developer.adzuna.com (register, create an app). Paste it here or keep `${ADZUNA_APP_ID}` "
                "and put the value in `.env` so the config file stays shareable.",
                required=True,
            ),
            OptionSpec(
                "app_key",
                "App key",
                "secret",
                "${ADZUNA_APP_KEY}",
                "The key that goes with the App ID, from the same developer.adzuna.com page. `${ADZUNA_APP_KEY}` reads it from the environment.",
                required=True,
            ),
        ),
        default_site={"id": "adzuna", "name": "Adzuna", "enabled": False, "max_results": 25},
    ),
    "reed": ProviderSpec(
        key="reed",
        label="Reed (UK)",
        description="UK job board with permanent / contract / temp and salary filters. Needs a free API key.",
        homepage="https://www.reed.co.uk/developers/jobseeker",
        requires_key=True,
        attribution="Listings courtesy of Reed.co.uk.",
        server_side=("titles/keyword", "location", "salary range", "permanent/contract/temp", "full/part-time"),
        options=(
            OptionSpec(
                "api_key",
                "API key",
                "secret",
                "${REED_API_KEY}",
                "Free key from reed.co.uk/developers/jobseeker (sent as HTTP basic-auth user name). Paste it or keep "
                "`${REED_API_KEY}` and set it in `.env`.",
                required=True,
            ),
            OptionSpec(
                "distance_miles",
                "Distance (miles)",
                "int",
                15,
                "Search radius around your first non-remote preferred location (e.g. `Manchester`). Example: `10` for city only, `30` for commuting range.",
                (),
            ),
        ),
        default_site={"id": "reed", "name": "Reed", "enabled": False, "max_results": 25},
    ),
    "usajobs": ProviderSpec(
        key="usajobs",
        label="USAJOBS",
        description="US federal government vacancies. Needs a free API key and the email it was registered with.",
        homepage="https://developer.usajobs.gov/",
        requires_key=True,
        attribution="Data from USAJOBS (https://www.usajobs.gov).",
        server_side=("titles/keyword", "location", "salary minimum"),
        options=(
            OptionSpec(
                "api_key",
                "API key",
                "secret",
                "${USAJOBS_API_KEY}",
                "Free key requested at developer.usajobs.gov (arrives by email). Sent as the `Authorization-Key` header. "
                "Paste it or keep `${USAJOBS_API_KEY}` and set it in `.env`.",
                required=True,
            ),
            OptionSpec(
                "email",
                "Registered email",
                "text",
                "${USAJOBS_EMAIL}",
                "The email address the key was issued to; USAJOBS requires it as the User-Agent of every request. Example: `you@example.com`.",
                required=True,
            ),
        ),
        default_site={"id": "usajobs", "name": "USAJOBS", "enabled": False, "max_results": 25},
    ),
    # ------------------------------------------------------------------ company careers platforms (ATS)
    "greenhouse": ProviderSpec(
        key="greenhouse",
        label="Greenhouse board",
        description="Company careers pages hosted on Greenhouse (boards.greenhouse.io/<board>). Uses Greenhouse's public Job Board API — no key, structured data.",
        homepage="https://developers.greenhouse.io/job-board.html",
        platform=True,
        attribution="",
        server_side=("department (filter)",),
        options=(
            OptionSpec("board", "Board token", "text", "", "The company's token in its Greenhouse URL. Example: for `https://boards.greenhouse.io/airbnb` the token is `airbnb`.", required=True),
            OptionSpec("company", "Company name", "text", "", "Display name shown in the employer column of results (the API only returns the board token). Example: `Airbnb`."),
            OptionSpec("department", "Department contains", "text", "", "Optional filter on the Greenhouse department name. Example: `Data` keeps `Data Science` and `Data Engineering`."),
            OptionSpec("workplace", "Default workplace", "select", "", "Assumed work mode when the location text does not say. Example: `onsite` for an office-first company.", ("", "remote", "hybrid", "onsite")),
        ),
    ),
    "lever": ProviderSpec(
        key="lever",
        label="Lever postings",
        description="Company careers pages hosted on Lever (jobs.lever.co/<site>). Uses Lever's public Postings API — no key; includes workplace type and sometimes salary.",
        homepage="https://github.com/lever/postings-api",
        platform=True,
        server_side=("department", "team", "location", "commitment"),
        options=(
            OptionSpec("site", "Site name", "text", "", "The company's name in its Lever URL. Example: for `https://jobs.lever.co/netflix` the site is `netflix`.", required=True),
            OptionSpec("company", "Company name", "text", "", "Display name shown in the employer column of results (the API only returns the site name). Example: `Netflix`."),
            OptionSpec("department", "Department", "text", "", "Optional exact Lever department filter applied by the API. Example: `Engineering`."),
            OptionSpec("team", "Team", "text", "", "Optional exact Lever team filter applied by the API. Example: `Data Platform`."),
            OptionSpec("location", "Location", "text", "", "Optional exact Lever location filter. Example: `Remote - US`."),
            OptionSpec("commitment", "Commitment", "text", "", "Optional exact Lever commitment filter. Example: `Full-time` or `Contract`."),
            OptionSpec("workplace", "Default workplace", "select", "", "Assumed work mode when Lever's workplaceType is missing. Example: `hybrid`.", ("", "remote", "hybrid", "onsite")),
        ),
    ),
    "ashby": ProviderSpec(
        key="ashby",
        label="Ashby job board",
        description="Company careers pages hosted on Ashby (jobs.ashbyhq.com/<board>). Uses Ashby's public Job Posting API — no key; includes employment type and compensation summary.",
        homepage="https://developers.ashbyhq.com/docs/public-job-posting-api",
        platform=True,
        server_side=(),
        options=(
            OptionSpec("board", "Job board name", "text", "", "The name in the company's Ashby URL. Example: for `https://jobs.ashbyhq.com/notion` the board is `notion`.", required=True),
            OptionSpec("company", "Company name", "text", "", "Display name shown in the employer column of results (the API only returns the board name). Example: `Notion`."),
            OptionSpec("workplace", "Default workplace", "select", "", "Assumed work mode when the posting is not flagged remote and the location does not say. Example: `onsite`.", ("", "remote", "hybrid", "onsite")),
        ),
    ),
    "smartrecruiters": ProviderSpec(
        key="smartrecruiters",
        label="SmartRecruiters",
        description="Company careers pages hosted on SmartRecruiters (careers.smartrecruiters.com/<Company>). Uses the public Posting API — no key; keyword and city are filtered server-side.",
        homepage="https://developers.smartrecruiters.com/docs/posting-api",
        platform=True,
        server_side=("keyword", "city"),
        options=(
            OptionSpec("company_id", "Company identifier", "text", "", "The identifier in the company's SmartRecruiters URL (case matters). Example: for `https://careers.smartrecruiters.com/Bosch` use `Bosch`.", required=True),
            OptionSpec("company", "Company name", "text", "", "Display name for the employer column if the API does not return one. Example: `Bosch`."),
            OptionSpec("workplace", "Default workplace", "select", "", "Assumed work mode when the posting is not flagged remote. Example: `onsite`.", ("", "remote", "hybrid", "onsite")),
        ),
    ),
    "recruitee": ProviderSpec(
        key="recruitee",
        label="Recruitee",
        description="Company careers pages hosted on Recruitee (<company>.recruitee.com). Uses the public careers API — no key; includes employment type and salary when published.",
        homepage="https://docs.recruitee.com/reference/offers",
        platform=True,
        server_side=(),
        options=(
            OptionSpec("company", "Company subdomain", "text", "", "The part before `.recruitee.com` in the careers URL. Example: for `https://acme.recruitee.com` use `acme`.", required=True),
            OptionSpec("company_name", "Company name", "text", "", "Display name shown in the employer column of results (the API only returns the subdomain). Example: `Acme GmbH`."),
            OptionSpec("workplace", "Default workplace", "select", "", "Assumed work mode when the offer is not flagged remote. Example: `onsite`.", ("", "remote", "hybrid", "onsite")),
        ),
    ),
    "workable": ProviderSpec(
        key="workable",
        label="Workable",
        description="Company careers pages hosted on Workable (apply.workable.com/<subdomain>). Uses Workable's public jobs widget API — no key; includes employment type and remote flag.",
        homepage="https://workable.readme.io/reference/jobs-widget",
        platform=True,
        server_side=(),
        options=(
            OptionSpec("subdomain", "Account subdomain", "text", "", "The company's Workable subdomain. Example: for `https://apply.workable.com/acme-inc/` use `acme-inc`.", required=True),
            OptionSpec("workplace", "Default workplace", "select", "", "Assumed work mode when the job is not flagged telecommuting. Example: `onsite`.", ("", "remote", "hybrid", "onsite")),
        ),
    ),
    "workday": ProviderSpec(
        key="workday",
        label="Workday careers site",
        description=(
            "Company careers sites hosted on Workday (<tenant>.wd<N>.myworkdayjobs.com/<site>) — e.g. Yahoo's. Calls the career "
            "site's own JSON search endpoint with your keywords and human-readable facet filters (country, job family…); the "
            "host's robots.txt is honoured."
        ),
        homepage="https://www.myworkdayjobs.com/",
        platform=True,
        server_side=("keyword", "facets: country, job family, time type…"),
        options=(
            OptionSpec(
                "url",
                "Careers URL (optional)",
                "text",
                "",
                "Paste the Workday careers address and tenant/host/site are derived automatically. Example: "
                "`https://ouryahoo.wd5.myworkdayjobs.com/careers` → tenant `ouryahoo`, site `careers`.",
            ),
            OptionSpec("tenant", "Tenant", "text", "", "First label of the Workday host. Example: `ouryahoo` for `ouryahoo.wd5.myworkdayjobs.com`.", required=True),
            OptionSpec("site", "Site", "text", "", "The career-site name after the host. Example: `careers` in `…myworkdayjobs.com/careers`; some companies use `External` or `Careers_Site`.", required=True),
            OptionSpec("host", "Host", "text", "", "Full host when it is not `<tenant>.wd5.myworkdayjobs.com`. Example: `ouryahoo.wd5.myworkdayjobs.com` or `company.wd1.myworkdayjobs.com`."),
            OptionSpec(
                "facets",
                "Filters (JSON)",
                "json",
                {},
                "Workday facet filters by their visible names; ids are looked up automatically and unknown names are reported with the "
                "available choices. Example: `{\"locationCountry\": \"United States\", \"jobFamilyGroup\": [\"Engineering\", \"Data\"], \"timeType\": \"Full time\"}`.",
            ),
            OptionSpec(
                "details",
                "Fetch job details",
                "select",
                "auto",
                "Each job page is one extra request and adds the description, time type and country. `auto` = first 10 jobs, `always` = all kept jobs, `never` = listing data only.",
                ("auto", "always", "never"),
            ),
            OptionSpec("company", "Company name", "text", "", "Display name shown in the employer column of results (Workday only returns the tenant). Example: `Yahoo`."),
            OptionSpec("workplace", "Default workplace", "select", "", "Assumed work mode when the listing does not say. Example: `hybrid`.", ("", "remote", "hybrid", "onsite")),
        ),
    ),
    "rss": ProviderSpec(
        key="rss",
        label="RSS / Atom feed",
        description="Any job board that publishes an RSS or Atom feed (company career pages, niche boards, Google Alerts).",
        homepage="",
        custom=True,
        server_side=(),
        options=(
            OptionSpec(
                "url",
                "Feed URL",
                "text",
                "",
                "Address of the RSS/Atom feed. `{keyword}` and `{location}` are replaced at search time (one request per title); "
                "without `{keyword}` the items are filtered locally by your titles. Example: `https://example.com/jobs.rss?q={keyword}` "
                "or a careers page whose feed link is discovered automatically.",
                required=True,
            ),
            OptionSpec(
                "title_format",
                "Title format",
                "select",
                "",
                "How the feed writes item titles, so the company can be split from the role. Example: WeWorkRemotely-style "
                "`Acme: Data Analyst` → *company: title*; `Data Analyst at Acme` → *title at company*. Blank = keep the title as is.",
                ("", "title at company", "company: title"),
            ),
            OptionSpec(
                "workplace",
                "Default workplace",
                "select",
                "",
                "Work mode to assume when an item does not mention remote/hybrid/on-site, so your *Workplace* preference can be applied. "
                "Example: `onsite` for a local hospital's careers feed.",
                ("", "remote", "hybrid", "onsite"),
            ),
        ),
    ),
    "html": ProviderSpec(
        key="html",
        label="Web page (HTML)",
        description=(
            "Any careers page or job-board page. Reads schema.org JobPosting data embedded in the page, follows job links "
            "to detail pages, or uses CSS selectors you provide; JavaScript-rendered pages are loaded in a real headless "
            "browser when Playwright is installed. Honours robots.txt, identifies itself, waits between requests, and stops "
            "on HTTP 403."
        ),
        homepage="",
        custom=True,
        server_side=(),
        options=(
            OptionSpec(
                "url",
                "Page URL",
                "text",
                "",
                "Address of the listing page. `{keyword}`, `{location}` and `{page}` are replaced at search time; without `{keyword}` "
                "the extracted listings are filtered locally by your titles. Example: `https://example.com/careers?q={keyword}&page={page}`.",
                required=True,
            ),
            OptionSpec(
                "pages",
                "Pages to fetch",
                "int",
                1,
                "Result pages to read when the URL contains `{page}` (replaced by 1, 2, 3 …). Paging stops early at the first empty "
                "page. Example: URL `…/jobs?page={page}` with `3` reads pages 1–3.",
                (),
            ),
            OptionSpec(
                "render",
                "Render with browser",
                "select",
                "auto",
                "auto = load the page in headless Chromium only when it looks JavaScript-rendered; always = every page; never = plain HTTP only. "
                "Needs Playwright (pip install playwright && python -m playwright install chromium).",
                ("auto", "always", "never"),
            ),
            OptionSpec(
                "actions",
                "Search form steps (JSON)",
                "json",
                [],
                "Steps the browser performs on the page before reading results — exactly what you would do by hand. Targets can be "
                "CSS or visible text: `{\"placeholder\": \"Key words\"}`, `{\"text\": \"Select countries\"}`, `{\"button\": \"Find jobs\"}`, "
                "`{\"label\": \"Country\"}`, `{\"option\": \"United States\"}`, `{\"css\": \"#q\"}`. Values may use `{keyword}`, `{location}` "
                "and any key from *Search form values*. Example: `[{\"fill\": {\"placeholder\": \"Key words\"}, \"value\": \"{keyword}\"}, "
                "{\"click\": {\"text\": \"Select countries\"}}, {\"click\": {\"option\": \"{country}\"}}, {\"press\": \"Escape\"}, "
                "{\"click\": {\"button\": \"Find jobs\"}}, {\"wait\": \"networkidle\"}]`. Add `\"repeat\": 3, \"snapshot\": true` to a "
                "'Load more'/'Next' click to collect several pages; `\"optional\": true` ignores a missing element.",
            ),
            OptionSpec(
                "form_values",
                "Search form values (JSON)",
                "json",
                {},
                "Named values for the `{placeholders}` used in the steps — the choices you would pick in the site's dropdowns. "
                "A list repeats the step for each item. Example: `{\"category\": \"Engineering\", \"country\": \"United States\", "
                "\"brands\": [\"Yahoo\", \"Yahoo Finance\"]}`.",
            ),
            OptionSpec(
                "follow_links",
                "Follow job links",
                "select",
                "auto",
                "`auto` opens individual job pages only when the listing page itself yields nothing; `always` also opens each job "
                "page to get full descriptions, salary and employment type; `never` uses only what the listing page shows.",
                ("auto", "always", "never"),
            ),
            OptionSpec(
                "max_detail_pages",
                "Max job pages to open",
                "int",
                15,
                "Upper bound on individual job pages opened per search when links are followed — each is one request to the site. "
                "Example: `15` ≈ 15 s of polite crawling at a 1 s delay.",
                (),
            ),
            OptionSpec(
                "delay_seconds",
                "Delay between requests (s)",
                "int",
                1,
                "Minimum pause between two requests to the same host (a larger robots.txt `Crawl-delay` wins). Example: `2` for small "
                "company sites, `1` for large boards.",
                (),
            ),
            OptionSpec(
                "link_pattern",
                "Job link pattern (regex)",
                "text",
                "",
                "Optional regular expression; only links whose URL matches are treated as job pages. Blank = built-in heuristic "
                "(`/jobs/`, `/careers/`, `/positions/`, `?job=` …). Example: `/positions/\\d+` or `jobdetails\\.aspx\\?id=`.",
            ),
            OptionSpec(
                "item_selector",
                "CSS: listing item",
                "text",
                "",
                "Optional CSS selector matching **one listing** on the page; the field selectors below are evaluated inside it. "
                "Find it with your browser's *Inspect* tool. Example: `li.job-result`, `div.posting`, `table.jobs tr`.",
            ),
            OptionSpec(
                "title_selector",
                "CSS: title",
                "text",
                "",
                "Selector for the role title inside the item. Blank = first heading or link. Example: `h3 a`, `.job-title`.",
            ),
            OptionSpec(
                "link_selector",
                "CSS: link",
                "text",
                "",
                "Selector for the `<a>` that leads to the job page. Blank = first link in the item. Example: `a.apply`, `h3 > a`.",
            ),
            OptionSpec(
                "company_selector",
                "CSS: company",
                "text",
                "",
                "Selector for the employer name inside the item (leave blank for a single-company careers page). Example: `.company`, `span.employer`.",
            ),
            OptionSpec(
                "location_selector",
                "CSS: location",
                "text",
                "",
                "Selector for the location text inside the item; it feeds your *Locations* and *Workplace* preferences. Example: `.location`, `td:nth-child(3)`.",
            ),
            OptionSpec(
                "salary_selector",
                "CSS: salary",
                "text",
                "",
                "Selector for the pay text; figures such as `$85k–$105k` or `£45,000 per annum` are parsed into your *Salary* filter. Example: `.salary`.",
            ),
            OptionSpec(
                "date_selector",
                "CSS: date",
                "text",
                "",
                "Selector for the posting date (ISO, RFC 2822 or `12 Oct 2026` formats are understood) — used by *Posted within*. Example: `time`, `.posted`.",
            ),
            OptionSpec(
                "job_type_selector",
                "CSS: job type",
                "text",
                "",
                "Selector for the employment type text (`Full-time`, `Contract`, `Temporary`, …) — used by your *Job types* filter. Example: `.type`, `em`.",
            ),
            OptionSpec(
                "workplace",
                "Default workplace",
                "select",
                "",
                "Work mode to assume when the page does not mention remote/hybrid/on-site. Example: `onsite` for a factory's careers page.",
                ("", "remote", "hybrid", "onsite"),
            ),
        ),
    ),
    "json": ProviderSpec(
        key="json",
        label="Generic JSON API",
        description="Any JSON endpoint. Map response fields to the job columns with dotted paths.",
        homepage="",
        custom=True,
        server_side=(),
        options=(
            OptionSpec(
                "url",
                "Endpoint URL",
                "text",
                "",
                "JSON endpoint to call. `{keyword}`, `{location}` and `{limit}` are replaced at search time. "
                "Example: `https://boards.example.com/api/jobs?search={keyword}&per_page={limit}`.",
                required=True,
            ),
            OptionSpec(
                "items_path",
                "Items path",
                "text",
                "",
                "Dotted path from the response root to the **list** of jobs. Blank when the response itself is a list. "
                "Example: `data.jobs` for `{\"data\": {\"jobs\": [...]}}`, `results` for `{\"results\": [...]}`.",
            ),
            OptionSpec(
                "mapping",
                "Field mapping (JSON)",
                "json",
                {
                    "title": "title",
                    "organization": "company",
                    "location": "location",
                    "url": "url",
                    "description": "description",
                    "salary_min": "salary_min",
                    "salary_max": "salary_max",
                    "job_type": "type",
                    "published": "date",
                    "id": "id",
                },
                "Maps each job column to a dotted path inside one item. Lists can be indexed (`locations.0.name`) or joined "
                "(`tags.*.name`). Unmapped columns stay empty. Example: `{\"title\": \"name\", \"organization\": \"employer.name\", "
                "\"url\": \"link\"}`.",
            ),
            OptionSpec(
                "headers",
                "Extra headers (JSON)",
                "json",
                {},
                "HTTP headers sent with every request, as a JSON object; `${ENV_VAR}` values are filled from the environment. "
                "Example: `{\"Authorization\": \"Bearer ${MY_TOKEN}\", \"Accept\": \"application/json\"}`.",
            ),
            OptionSpec(
                "workplace",
                "Default workplace",
                "select",
                "",
                "Work mode to assume when an item has no workplace field. Example: `remote` for a remote-only board's API.",
                ("", "remote", "hybrid", "onsite"),
            ),
        ),
    ),
}


def provider(key: str) -> ProviderSpec | None:
    return PROVIDERS.get((key or "").lower())


def builtin_providers() -> list[ProviderSpec]:
    return [spec for spec in PROVIDERS.values() if not spec.custom and not spec.platform]


def platform_providers() -> list[ProviderSpec]:
    return [spec for spec in PROVIDERS.values() if spec.platform]


def custom_providers() -> list[ProviderSpec]:
    return [spec for spec in PROVIDERS.values() if spec.custom]


def default_options(key: str) -> dict[str, Any]:
    spec = provider(key)
    if not spec:
        return {}
    return {opt.key: (dict(opt.default) if isinstance(opt.default, dict) else opt.default) for opt in spec.options}
