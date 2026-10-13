"""Adapters (against canned payloads) and the search orchestrator."""

from __future__ import annotations

from datetime import date

import jobsearch_config as jc
import jobsearch_sources as js
from jobsearch_sources.providers import SearchContext, _dig
from tests.conftest import load_fixture

TODAY = date(2026, 10, 12)


def ctx_for(config: jc.AppConfig, site: jc.SiteConfig, keywords=None) -> SearchContext:
    return SearchContext(site=site, prefs=config.preferences, settings=config.search, options=jc.resolve_options(site.options), keywords=keywords if keywords is not None else ["data analyst"], location="Philadelphia, PA")


def test_remotive_adapter(config, transport):
    fake = transport({"remotive.com": load_fixture("remotive.json")})
    site = config.get_site("remotive")
    site.options["category"] = "data"
    jobs = js.ADAPTERS["remotive"](ctx_for(config, site))
    assert [j.title for j in jobs] == ["Senior Data Analyst", "Marketing Intern", "Data Analyst (Contract)"]
    assert "search=data+analyst" in fake.calls[0][0] and "category=data" in fake.calls[0][0]
    first = jobs[0]
    assert first.job_type == "permanent" and first.schedule == "full_time"
    assert (first.salary_min, first.salary_max, first.salary_currency) == (90000, 120000, "USD")
    assert first.description == "We need SQL, Python and Tableau."  # HTML stripped
    assert jobs[2].job_type == "contract"


def test_remotive_category_derived_from_industry(config, transport):
    fake = transport({"remotive.com": {"jobs": []}})
    config.preferences.industries = ["Data / Analytics"]
    site = config.get_site("remotive")
    js.ADAPTERS["remotive"](ctx_for(config, site))
    assert "category=data" in fake.calls[0][0]


def test_jobicy_adapter(config, transport):
    fake = transport({"jobicy.com": load_fixture("jobicy.json")})
    site = config.get_site("jobicy")
    site.options.update({"geo": "usa", "industry": ""})
    jobs = js.ADAPTERS["jobicy"](ctx_for(config, site))
    assert "geo=usa" in fake.calls[0][0] and "tag=data+analyst" in fake.calls[0][0]
    assert jobs[0].salary_min == 60000 and jobs[0].salary_period == "year"
    assert jobs[0].industry == "Data Science"


def test_arbeitnow_filters_locally(config, transport):
    transport({"arbeitnow.com": load_fixture("arbeitnow.json")})
    site = jc.SiteConfig(id="arbeitnow", provider="arbeitnow", options={"pages": 1})
    jobs = js.ADAPTERS["arbeitnow"](ctx_for(config, site))
    assert [j.title for j in jobs] == ["Data Analyst (m/w/d)"]
    assert jobs[0].workplace == "onsite" and jobs[0].location == "Berlin"


def test_adzuna_pushes_filters_and_needs_keys(config, transport, monkeypatch):
    monkeypatch.setenv("ADZUNA_APP_ID", "id123")
    monkeypatch.setenv("ADZUNA_APP_KEY", "key456")
    fake = transport({"api.adzuna.com": load_fixture("adzuna.json")})
    config.preferences.job_types = ["permanent"]
    config.preferences.schedules = ["full_time"]
    config.preferences.salary = jc.SalaryRange(minimum=80000, maximum=120000)
    config.preferences.posted_within_days = 14
    site = config.get_site("adzuna")
    jobs = js.ADAPTERS["adzuna"](ctx_for(config, site))
    url = fake.calls[0][0]
    for part in ("app_id=id123", "app_key=key456", "what=data+analyst", "where=Philadelphia%2C+PA", "salary_min=80000", "salary_max=120000", "permanent=1", "full_time=1", "max_days_old=14", "/jobs/us/search/1"):
        assert part in url, part
    assert jobs[0].job_type == "permanent" and jobs[0].schedule == "full_time"
    assert jobs[0].salary_currency == "USD" and jobs[0].industry == "IT Jobs"

    monkeypatch.delenv("ADZUNA_APP_ID")
    _, outcome = js.search_site(site, config, ["data analyst"])
    assert "app id" in outcome.error.lower()


def test_rss_adapter(config, transport):
    transport({"acme.example.com": (__import__("pathlib").Path(__file__).parent / "fixtures" / "feed.rss").read_text()})
    site = jc.SiteConfig(id="acme", provider="rss", name="Acme", options={"url": "https://acme.example.com/jobs.rss", "title_format": "company: title", "workplace": "onsite"})
    jobs = js.ADAPTERS["rss"](ctx_for(config, site, keywords=[]))
    assert [(j.title, j.organization) for j in jobs] == [("Data Analyst", "Acme"), ("Warehouse Associate", "Acme")]
    assert jobs[0].workplace == "remote" and jobs[0].published == "2026-10-10"
    assert jobs[0].job_type == "permanent"
    assert (jobs[0].salary_min, jobs[0].salary_max) == (None, None)  # salary only in free text; not parsed from description
    assert jobs[1].job_type == "temporary" and jobs[1].workplace == "onsite"
    # keyword filtering applies locally when the URL has no {keyword} placeholder
    jobs = js.ADAPTERS["rss"](ctx_for(config, site, keywords=["warehouse"]))
    assert [j.title for j in jobs] == ["Warehouse Associate"]


def test_generic_json_adapter_with_mapping(config, transport, monkeypatch):
    monkeypatch.setenv("THETA_TOKEN", "tok")
    fake = transport({"theta.example.com": load_fixture("generic.json")})
    site = jc.SiteConfig(
        id="theta",
        provider="json",
        options={
            "url": "https://theta.example.com/api/jobs?q={keyword}&limit={limit}",
            "items_path": "data.jobs",
            "headers": {"Authorization": "Bearer ${THETA_TOKEN}"},
            "mapping": {"title": "name", "organization": "employer.name", "location": "where", "url": "link", "description": "body",
                        "salary_min": "pay.min", "salary_max": "pay.max", "job_type": "kind", "published": "posted", "id": "id"},
        },
    )
    jobs = js.ADAPTERS["json"](ctx_for(config, site))
    assert fake.calls[0][0] == "https://theta.example.com/api/jobs?q=data+analyst&limit=20"
    assert fake.calls[0][1]["Authorization"] == "Bearer tok"
    assert jobs[0].organization == "Theta" and jobs[0].workplace == "remote"
    assert (jobs[0].salary_min, jobs[0].salary_max) == (100000, 130000)
    assert jobs[0].job_type == "permanent" and jobs[1].schedule == "part_time"
    assert jobs[0].external_id == "theta:a1"


def test_dig_paths():
    data = {"a": {"b": [{"c": 1}, {"c": 2}]}}
    assert _dig(data, "a.b.1.c") == 2
    assert _dig(data, "a.b.*") == [{"c": 1}, {"c": 2}]
    assert _dig(data, "a.x.y") is None


def test_run_search_end_to_end(config, transport):
    transport({"remotive.com": load_fixture("remotive.json"), "jobicy.com": load_fixture("jobicy.json")})
    config.preferences.salary = jc.SalaryRange(minimum=80000, currency="USD", include_unlisted=True)
    report = js.run_search(config, today=TODAY)
    assert report.errors == []
    titles = [job.title for job, _ in report.results]
    # duplicate URL across sites removed, intern (Europe, old) dropped, BI analyst (60-70k) dropped by salary
    assert titles == ["Senior Data Analyst", "Data Analyst (Contract)"]
    outcomes = {o.site_id: o for o in report.outcomes}
    assert outcomes["remotive"].fetched == 3 and outcomes["remotive"].kept == 2
    assert outcomes["jobicy"].fetched == 2 and outcomes["jobicy"].kept == 0
    assert any("Remotive" in a for a in report.attributions)
    rows = report.rows()
    assert rows[0]["matched_skills"] == "SQL, Python, Tableau" and rows[0]["score"] > rows[1]["score"]


def test_run_search_non_strict_keeps_failures_with_reasons(config, transport):
    transport({"remotive.com": load_fixture("remotive.json"), "jobicy.com": load_fixture("jobicy.json")})
    report = js.run_search(config, strict=False, today=TODAY)
    rows = report.rows()
    assert len(rows) == 4
    failing = [r for r in rows if not r["passes"]]
    assert failing and all(r["filter_notes"] for r in failing)
    assert all(r["passes"] for r in rows[:2])  # passing listings sort first


def test_run_search_keyword_override_and_site_subset(config, transport):
    fake = transport({"remotive.com": {"jobs": []}, "jobicy.com": {"jobs": []}})
    report = js.run_search(config, keyword="machine learning", site_ids=["remotive"], today=TODAY)
    assert [o.site_id for o in report.outcomes] == ["remotive"]
    assert len(fake.calls) == 1 and "search=machine+learning" in fake.calls[0][0]


def test_run_search_reports_site_errors_without_failing(config, transport):
    transport({"remotive.com": load_fixture("remotive.json"), "jobicy.com": js.FetchError("HTTP 503 from jobicy.com")})
    report = js.run_search(config, today=TODAY)
    assert report.errors == ["Jobicy: HTTP 503 from jobicy.com"]
    assert len(report.results) >= 1


def test_unknown_provider_is_reported(config):
    config.sites.append(jc.SiteConfig(id="weird", provider="nothing", enabled=True))
    report = js.run_search(config, site_ids=["weird"], today=TODAY)
    assert "no adapter" in report.errors[0]
