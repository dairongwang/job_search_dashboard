"""ATS providers (Greenhouse, Lever, Ashby, SmartRecruiters, Recruitee, Workable, Workday) and the investigator."""

from __future__ import annotations

import json
from datetime import date

import jobsearch_config as jc
import jobsearch_sources as js
from jobsearch_sources import robots
from jobsearch_sources.ats import workday_base, workday_posted_on
from jobsearch_sources.providers import SearchContext

TODAY = date(2026, 10, 12)


def ctx_for(config, provider, options, keywords=("data analyst",)):
    opts = jc.default_options(provider)
    opts.update(options)
    site = jc.SiteConfig(id=provider, provider=provider, name=provider.title(), options=opts)
    return SearchContext(site=site, prefs=config.preferences, settings=config.search, options=jc.resolve_options(site.options), keywords=list(keywords), location="Philadelphia, PA")


def test_greenhouse(config, transport):
    fake = transport({"boards-api.greenhouse.io": {"jobs": [
        {"id": 1, "title": "Data Analyst", "absolute_url": "https://boards.greenhouse.io/acme/jobs/1", "location": {"name": "Philadelphia, PA"},
         "content": "&lt;p&gt;SQL and Python&lt;/p&gt;", "departments": [{"name": "Data"}], "offices": [{"name": "Philly"}], "updated_at": "2026-10-10T00:00:00-04:00"},
        {"id": 2, "title": "Nurse", "absolute_url": "https://boards.greenhouse.io/acme/jobs/2", "location": {"name": "Remote"}, "content": "", "departments": [{"name": "Clinical"}]},
    ]}})
    jobs = js.ADAPTERS["greenhouse"](ctx_for(config, "greenhouse", {"board": "acme", "company": "Acme"}))
    assert fake.calls[0][0] == "https://boards-api.greenhouse.io/v1/boards/acme/jobs?content=true"
    assert [j.title for j in jobs] == ["Data Analyst"] and jobs[0].organization == "Acme" and jobs[0].industry == "Data"


def test_lever(config, transport):
    transport({"api.lever.co": [
        {"id": "a", "text": "Data Analyst", "hostedUrl": "https://jobs.lever.co/acme/a", "createdAt": 1791000000000, "workplaceType": "remote",
         "categories": {"commitment": "Full-time", "department": "Analytics", "location": "Remote - US", "allLocations": ["Remote - US"]},
         "descriptionPlain": "SQL", "salaryRange": {"min": 90000, "max": 110000, "currency": "USD", "interval": "per-year-salary"}},
    ]})
    jobs = js.ADAPTERS["lever"](ctx_for(config, "lever", {"site": "acme"}))
    job = jobs[0]
    assert job.workplace == "remote" and job.job_type == "permanent" and job.schedule == "full_time"
    assert (job.salary_min, job.salary_max, job.salary_period) == (90000, 110000, "year") and job.published


def test_ashby(config, transport):
    transport({"api.ashbyhq.com": {"jobs": [
        {"id": "x", "title": "Data Analyst", "employmentType": "Contract", "location": "New York", "isRemote": False, "jobUrl": "https://jobs.ashbyhq.com/acme/x",
         "publishedAt": "2026-10-09T00:00:00Z", "descriptionPlain": "SQL", "department": "Data", "compensation": {"compensationTierSummary": "$60–$80 / hour"}},
    ]}})
    job = js.ADAPTERS["ashby"](ctx_for(config, "ashby", {"board": "acme"}))[0]
    assert job.job_type == "contract" and job.salary_min == 60 and job.salary_period == "hour"


def test_smartrecruiters(config, transport):
    fake = transport({"api.smartrecruiters.com": {"content": [
        {"id": "9", "name": "Data Analyst", "releasedDate": "2026-10-08T00:00:00.000Z", "location": {"city": "Philadelphia", "region": "PA", "country": "us", "remote": False},
         "typeOfEmployment": {"label": "Full-time"}, "department": {"label": "Finance"}, "industry": {"label": "Banking"}, "company": {"name": "Acme Bank"}},
    ]}})
    job = js.ADAPTERS["smartrecruiters"](ctx_for(config, "smartrecruiters", {"company_id": "AcmeBank"}))[0]
    assert "q=data+analyst" in fake.calls[0][0] and "city=Philadelphia" in fake.calls[0][0]
    assert job.organization == "Acme Bank" and job.url == "https://jobs.smartrecruiters.com/AcmeBank/9" and job.industry == "Banking"


def test_recruitee_and_workable(config, transport):
    transport({
        "acme.recruitee.com": {"offers": [{"id": 1, "title": "Data Analyst", "careers_url": "https://acme.recruitee.com/o/data-analyst", "description": "SQL", "requirements": "",
                                           "city": "Berlin", "country": "Germany", "remote": True, "employment_type_code": "fulltime", "department": "Data",
                                           "published_at": "2026-10-01", "salary": {"min": 60000, "max": 70000, "currency": "EUR", "period": "yearly"}}]},
        "www.workable.com": {"name": "Acme Inc", "jobs": [{"title": "Data Analyst", "shortcode": "AB12", "url": "https://apply.workable.com/acme/j/AB12", "city": "Austin", "state": "TX",
                                                          "country": "United States", "telecommuting": False, "employment_type": "Full-time", "description": "SQL", "department": "Ops",
                                                          "published_on": "2026-10-05", "experience": "Mid level"}]},
    })
    r = js.ADAPTERS["recruitee"](ctx_for(config, "recruitee", {"company": "acme"}))[0]
    assert r.workplace == "remote" and r.salary_currency == "EUR" and r.salary_period == "year" and r.job_type == "permanent"
    w = js.ADAPTERS["workable"](ctx_for(config, "workable", {"subdomain": "acme"}))[0]
    assert w.organization == "Acme Inc" and w.location == "Austin, TX, United States" and w.tags == ["Mid level"]


def test_workday_search_with_named_facets_and_details(config, transport):
    listing = {
        "total": 2,
        "jobPostings": [
            {"title": "Data Analyst", "externalPath": "/job/Sunnyvale-CA/Data-Analyst_R1", "locationsText": "Sunnyvale, CA", "postedOn": "Posted 3 Days Ago", "bulletFields": ["R1"]},
            {"title": "Data Engineer", "externalPath": "/job/Remote/Data-Engineer_R2", "locationsText": "2 Locations", "postedOn": "Posted Today", "bulletFields": ["R2"]},
        ],
        "facets": [
            {"facetParameter": "locationCountry", "values": [{"descriptor": "United States of America", "id": "us-id"}, {"descriptor": "Canada", "id": "ca-id"}]},
            {"facetParameter": "jobFamilyGroup", "values": [{"descriptor": "Engineering", "id": "eng-id"}, {"descriptor": "Marketing", "id": "mkt-id"}]},
        ],
    }
    detail = {"jobPostingInfo": {"title": "Data Analyst", "jobDescription": "<p>SQL &amp; Python</p>", "location": "Sunnyvale, CA", "timeType": "Full time",
                                 "startDate": "2026-10-09", "externalUrl": "https://ouryahoo.wd5.myworkdayjobs.com/careers/job/Sunnyvale-CA/Data-Analyst_R1"}}
    fake = transport({"/jobs": listing, "/job/Sunnyvale-CA/Data-Analyst_R1": detail, "/job/Remote/Data-Engineer_R2": {"jobPostingInfo": {"timeType": "Full time"}}})
    ctx = ctx_for(config, "workday", {"url": "https://ouryahoo.wd5.myworkdayjobs.com/careers", "company": "Yahoo",
                                       "facets": {"locationCountry": "United States", "jobFamilyGroup": ["Engineering", "Nope"]}})
    jobs = js.ADAPTERS["workday"](ctx)
    # facet lookup call first, then the search with resolved ids
    assert fake.calls[0][0] == "https://ouryahoo.wd5.myworkdayjobs.com/wday/cxs/ouryahoo/careers/jobs"
    search_body = json.loads(fake.bodies[1])
    assert search_body["appliedFacets"] == {"locationCountry": ["us-id"], "jobFamilyGroup": ["eng-id"]} and search_body["searchText"] == "data analyst"
    assert any("jobFamilyGroup=Nope" in n for n in ctx.notes)  # unknown facet value reported with choices
    assert [j.title for j in jobs] == ["Data Analyst", "Data Engineer"]
    analyst = jobs[0]
    assert analyst.organization == "Yahoo" and analyst.description == "SQL & Python" and analyst.schedule == "full_time" and analyst.job_type == "permanent"
    assert analyst.url.endswith("/careers/job/Sunnyvale-CA/Data-Analyst_R1") and analyst.published == "2026-10-09"
    assert workday_posted_on("Posted 30+ Days Ago", TODAY) == "2026-09-12" and workday_posted_on("Posted Yesterday", TODAY) == "2026-10-11"
    assert workday_base({"url": "https://acme.wd1.myworkdayjobs.com/en-US/External"}) == ("https://acme.wd1.myworkdayjobs.com", "acme", "External")


def test_platform_sites_are_registered_and_blocked_on_403(config, transport):
    transport({"api.lever.co": js.FetchError("HTTP 403 from api.lever.co", status=403, url="https://api.lever.co/v0/postings/acme")})
    config.sites = [jc.SiteConfig(id="lever", provider="lever", name="Lever", options={**jc.default_options("lever"), "site": "acme"})]
    report = js.run_search(config, today=TODAY)
    assert report.outcomes[0].denied and jc.load_registry().lookup("api.lever.co").status == "forbidden"


# --- investigate ------------------------------------------------------------

YAHOO_LIKE = """<!DOCTYPE html><html><head><title>Careers</title></head><body>
<input placeholder="Key words"><div role="combobox" aria-label="Select job categories"></div>
<select aria-label="Select countries"><option>Select countries</option><option>United States</option></select>
<button>Find jobs</button>
<a href="https://ouryahoo.wd5.myworkdayjobs.com/careers/job/Sunnyvale/Data-Analyst_R1">Apply</a>
<script src="/bundle.js"></script></body></html>"""


def test_investigate_detects_workday_and_form_controls(transport):
    robots.clear_cache()
    transport({"/robots.txt": "User-agent: *\nAllow: /\n", "yahooinc.com": YAHOO_LIKE})
    report = js.investigate("https://www.yahooinc.com/careers/")
    assert report.verdict == "crawlable" and report.robots_allowed
    assert report.platform == "workday" and report.platform_options["tenant"] == "ouryahoo" and report.platform_options["site"] == "careers"
    labels = {(c.kind, c.label) for c in report.form_controls}
    assert ("input", "Key words") in labels and ("button", "Find jobs") in labels and ("select", "Select countries") in labels
    assert ("combobox", "Select job categories") in labels
    site = report.suggested_config()
    assert site.provider == "workday" and site.options["host"] == "ouryahoo.wd5.myworkdayjobs.com"
    text = js.format_report(report)
    assert "Platform: Workday" in text and "Find jobs" in text
    assert jc.load_registry().lookup("www.yahooinc.com").status == "ok"


def test_investigate_forbidden_and_blocked(transport):
    robots.clear_cache()
    transport({"/robots.txt": "User-agent: *\nDisallow: /careers\n", "x.example.com": "<html></html>"})
    report = js.investigate("https://x.example.com/careers/")
    assert report.verdict == "forbidden" and "robots.txt disallows" in report.summary and report.suggested_site is None
    robots.clear_cache()
    transport({"/robots.txt": "User-agent: *\nAllow: /\n", "wall.example.com": js.FetchError("HTTP 403 from wall.example.com", status=403, url="https://wall.example.com/")})
    report = js.investigate("https://wall.example.com/jobs")
    assert report.verdict == "forbidden" and report.denied and report.http_status == 403
    assert not jc.load_registry().lookup("wall.example.com").active


def test_investigate_greenhouse_feed_and_plain_page(transport):
    robots.clear_cache()
    transport({
        "/robots.txt": "User-agent: *\nAllow: /\n",
        "gh.example.com": '<html><body><iframe src="https://boards.greenhouse.io/embed/job_board?for=acme"></iframe></body></html>',
        "feedy.example.com": '<html><head><link rel="alternate" type="application/rss+xml" href="/jobs.rss"></head><body>x</body></html>',
        "plain.example.com": '<html><body><a href="/jobs/1">Data Analyst</a><a href="/jobs/2">Nurse</a></body></html>',
    })
    gh = js.investigate("https://gh.example.com/careers")
    assert gh.platform == "greenhouse" and gh.suggested_config().options["board"] == "acme"
    feed = js.investigate("https://feedy.example.com/careers")
    assert feed.suggested_config().provider == "rss" and feed.suggested_config().options["url"] == "https://feedy.example.com/jobs.rss"
    plain = js.investigate("https://plain.example.com/careers")
    assert plain.suggested_config().provider == "html" and plain.job_links == 2


def test_detect_html_platforms():
    key, label, _ = js.detect_platform('<a href="https://careers-acme.icims.com/jobs/search">x</a>', "https://acme.com")
    assert key == "icims" and "Web page provider" in label
    assert js.detect_platform("<html></html>", "https://acme.com") == ("", "", {})
