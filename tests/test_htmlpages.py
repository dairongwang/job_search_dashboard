"""Web-page provider: JSON-LD, link following, CSS selectors, robots.txt."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

import jobsearch_config as jc
import jobsearch_sources as js
from jobsearch_sources import robots
from jobsearch_sources.providers import SearchContext

FIX = Path(__file__).parent / "fixtures"
TODAY = date(2026, 10, 12)
ROBOTS = "User-agent: *\nDisallow: /jobs/private/\nDisallow: /*rt=nc\nCrawl-delay: 0\n"


@pytest.fixture(autouse=True)
def _fresh_robots():
    robots.clear_cache()
    yield
    robots.clear_cache()


def page_site(url: str, **options) -> jc.SiteConfig:
    opts = jc.default_options("html")
    opts.update({"url": url, "delay_seconds": 0})
    opts.update(options)
    return jc.SiteConfig(id="page", provider="html", name="Page", options=opts)


def run(config, site, keywords=None):
    config.sites = [site]
    return js.run_search(config, keyword="" if keywords is None else keywords, today=TODAY)


def ctx_for(config, site, keywords=()):
    return SearchContext(site=site, prefs=config.preferences, settings=config.search, options=jc.resolve_options(site.options), keywords=list(keywords))


# --- robots.txt --------------------------------------------------------------


def test_robots_rfc_matching_on_real_rule_sets():
    indeed = "User-agent: *\nAllow: /\nAllow: /*&start=10&\nDisallow: /*rt=nc\nDisallow: /viewjob\nDisallow: /rc/\nDisallow: /*&start=\n"
    rules = robots.parse(indeed)
    ok = lambda u: rules.can_fetch("JobSearchDashboard", u)  # noqa: E731
    assert ok("https://www.indeed.com/jobs?q=analyst&l=Philadelphia")
    assert not ok("https://www.indeed.com/viewjob?jk=1")
    assert not ok("https://www.indeed.com/rc/clk?jk=1")
    assert not ok("https://www.indeed.com/jobs?q=x&rt=nc")
    assert ok("https://www.indeed.com/jobs?q=x&start=10&y=1")
    assert not ok("https://www.indeed.com/jobs?q=x&start=20")
    monster = "User-agent: *\nDisallow: /jobs/search?*&page=\nAllow: /jobs/search?q=\nDisallow: /jobs/search?\n"
    rules = robots.parse(monster)
    assert rules.can_fetch("x", "https://www.monster.com/jobs/search?q=analyst&where=philadelphia")
    assert not rules.can_fetch("x", "https://www.monster.com/jobs/search?q=analyst&page=2")
    specific = "User-agent: JobSearchDashboard\nDisallow: /\n\nUser-agent: *\nAllow: /\n"
    assert not robots.parse(specific).can_fetch("JobSearchDashboard", "https://x/a")
    assert robots.parse(specific).can_fetch("Other", "https://x/a")
    assert robots.product_token("Mozilla/5.0 (compatible; JobSearchDashboard/2.0; personal job tracker)") == "JobSearchDashboard"


def test_robots_missing_allows_and_server_error_disallows(transport):
    transport({"/robots.txt": js.FetchError("HTTP 404", status=404)})
    assert robots.check("https://a.example.com/jobs").allowed
    robots.clear_cache()
    transport({"/robots.txt": js.FetchError("HTTP 503", status=503)})
    verdict = robots.check("https://b.example.com/jobs")
    assert not verdict.allowed and verdict.unreachable and "could not be fetched" in verdict.reason


def test_unreachable_robots_blocks_but_is_not_recorded_as_forbidden(config, transport):
    transport({"/robots.txt": js.FetchError("HTTP 503", status=503)})
    report = run(config, page_site("https://b.example.com/jobs"))
    assert "could not be fetched" in report.errors[0] and not report.outcomes[0].denied
    row = jc.load_registry().lookup("b.example.com")
    assert row.status == "error" and row.active


# --- extraction ---------------------------------------------------------------


def test_jsonld_listing_page(config, transport):
    transport({"/robots.txt": ROBOTS, "careers.acme.example.com/": (FIX / "careers_jsonld.html").read_text()})
    report = run(config, page_site("https://careers.acme.example.com/"))
    assert report.errors == []
    jobs = {job.title: job for job, _ in report.results}
    assert set(jobs) == {"Data Analyst", "Contract BI Developer"}  # expired posting dropped
    analyst = jobs["Data Analyst"]
    assert analyst.organization == "Acme Health" and analyst.location == "Philadelphia, PA, US"
    assert (analyst.salary_min, analyst.salary_max, analyst.salary_currency, analyst.salary_period) == (85000, 105000, "USD", "year")
    assert analyst.job_type == "permanent" and analyst.schedule == "full_time"
    assert analyst.url == "https://careers.acme.example.com/jobs/123" and analyst.external_id == "page:123"
    assert analyst.description == "SQL, Python and Tableau reporting."
    bi = jobs["Contract BI Developer"]
    assert bi.workplace == "remote" and bi.location == "USA" and bi.job_type == "contract" and bi.schedule == "part_time"
    assert (bi.salary_min, bi.salary_period) == (60, "hour")


def test_follows_job_links_and_respects_robots(config, transport):
    fake = transport({
        "/robots.txt": ROBOTS,
        "board.example.com/jobs/501": (FIX / "detail_501.html").read_text(),
        "board.example.com/jobs/502": (FIX / "detail_502.html").read_text(),
        "board.example.com/jobs/private/503": "<html><body>should never be fetched</body></html>",
        "board.example.com/": (FIX / "board_links.html").read_text(),
    })
    report = run(config, page_site("https://board.example.com/"))
    assert report.errors == []
    titles = sorted(job.title for job, _ in report.results)
    assert titles == ["Data Analyst", "Office Manager"]
    fetched = [url for url, _ in fake.calls]
    assert "https://board.example.com/jobs/private/503" not in fetched  # robots.txt
    assert not any("other.example.com" in u for u in fetched)  # external host ignored
    assert not any("/login" in u for u in fetched)
    outcome = report.outcomes[0]
    assert "1 job link(s) skipped because robots.txt disallows them" in outcome.note
    analyst = next(job for job, _ in report.results if job.title == "Data Analyst")
    assert analyst.job_type == "temporary" and analyst.salary_min == 40 and analyst.organization == "Zeta Corp"
    manager = next(job for job, _ in report.results if job.title == "Office Manager")
    assert manager.organization == "Zeta Corp" and manager.workplace == "hybrid"


def test_css_selectors(config, transport):
    transport({"/robots.txt": ROBOTS, "theta.example.com": (FIX / "listing_selectors.html").read_text()})
    site = page_site(
        "https://theta.example.com/jobs",
        item_selector="div.posting", title_selector="h3 a", company_selector=".co", location_selector=".loc",
        salary_selector=".pay", date_selector="time", job_type_selector="em", follow_links="never",
    )
    report = run(config, site)
    assert report.errors == []
    jobs = {job.title: job for job, _ in report.results}
    senior = jobs["Senior Data Analyst"]
    assert senior.url == "https://theta.example.com/p/1" and senior.workplace == "remote"
    assert (senior.salary_min, senior.salary_max) == (110000, 130000) and senior.job_type == "permanent"
    assert jobs["Warehouse Lead"].job_type == "temporary" and jobs["Warehouse Lead"].published == "2026-10-11"


def test_keyword_placeholder_and_local_filtering(config, transport):
    fake = transport({"/robots.txt": ROBOTS, "theta.example.com": (FIX / "listing_selectors.html").read_text()})
    site = page_site("https://theta.example.com/jobs?q={keyword}&page={page}", item_selector="div.posting", follow_links="never", pages=2)
    config.sites = [site]
    report = js.run_search(config, keyword="analyst", today=TODAY)
    urls = [u for u, _ in fake.calls if "theta" in u and "robots" not in u]
    assert urls[0] == "https://theta.example.com/jobs?q=analyst&page=1"
    assert len(report.results) == 2  # keyword in URL -> no local filtering
    site2 = page_site("https://theta.example.com/jobs", item_selector="div.posting", follow_links="never")
    config.sites = [site2]
    report = js.run_search(config, keyword="warehouse", today=TODAY)
    assert [job.title for job, _ in report.results] == ["Warehouse Lead"]


def test_js_rendered_page_is_explained(config, transport):
    transport({"/robots.txt": ROBOTS, "spa.example.com": (FIX / "js_only.html").read_text()})
    report = run(config, page_site("https://spa.example.com/search?q=x", render="never"))
    assert len(report.errors) == 1 and "render results with JavaScript" in report.errors[0]


def test_robots_disallowed_listing_page(config, transport):
    transport({"/robots.txt": "User-agent: *\nDisallow: /search\n", "x.example.com": "<html></html>"})
    report = run(config, page_site("https://x.example.com/search?q=a"))
    assert "robots.txt disallows /search" in report.errors[0]


def test_blocked_site_error_is_recorded_and_enforced(config, transport):
    transport({"/robots.txt": "User-agent: *\nAllow: /\n", "wall.example.com": js.FetchError("HTTP 403 from wall.example.com", status=403, url="https://wall.example.com/jobs?q=x")})
    site = page_site("https://wall.example.com/jobs?q=analyst")
    report = run(config, site)
    assert "refused automated access (HTTP 403)" in report.errors[0]
    assert report.outcomes[0].denied
    row = jc.load_registry().lookup("https://wall.example.com/jobs")
    assert row is not None and row.status == "forbidden" and not row.active and row.last_status_code == 403 and row.source == "search"
    # second run: skipped before any request is made
    fake = transport({"/robots.txt": "User-agent: *\nAllow: /\n", "wall.example.com": "<html>should not be fetched</html>"})
    report = run(config, site)
    assert report.errors[0].startswith("Page: skipped — wall.example.com forbids automated access")
    assert fake.calls == []
    # "Test this site now" re-checks a forbidden host and clears the flag when the site allows access again
    fake = transport({"/robots.txt": "User-agent: *\nAllow: /\n", "wall.example.com": (FIX / "careers_jsonld.html").read_text()})
    jobs, outcome = js.test_site(site, config)  # configured titles ("data analyst") filter the fixture down to one
    assert not outcome.error and [j.title for j in jobs] == ["Data Analyst"]
    row = jc.load_registry().lookup("wall.example.com")
    assert row.active and row.status == "ok" and row.checks == 2


def test_wrong_content_type_hint(config, transport):
    transport({"/robots.txt": ROBOTS, "feed.example.com": '<?xml version="1.0"?><rss><channel></channel></rss>'})
    report = run(config, page_site("https://feed.example.com/jobs.rss"))
    assert "RSS / Atom feed" in report.errors[0]


def test_probe_for_pages(transport):
    transport({"/robots.txt": ROBOTS, "careers.acme.example.com/": (FIX / "careers_jsonld.html").read_text(),
               "board.example.com/": (FIX / "board_links.html").read_text(), "spa.example.com": (FIX / "js_only.html").read_text(),
               "private.example.com": "<html></html>"})
    r = js.probe("https://careers.acme.example.com/", expect="html")
    assert r.ok and r.items == 4 and "3 schema.org JobPosting" in r.message
    r = js.probe("https://board.example.com/", expect="html")
    assert r.ok and "job-looking link" in r.message
    r = js.probe("https://spa.example.com/", expect="html")
    assert r.ok and r.items == 0 and "JavaScript" in r.message
    robots.clear_cache()
    transport({"/robots.txt": "User-agent: *\nDisallow: /\n"})
    r = js.probe("https://private.example.com/jobs", expect="html")
    assert r.status == "robots" and not r.ok


def test_legacy_user_agent_is_upgraded():
    s = jc.SearchSettings(user_agent="JobSearchDashboard/2.0 (personal local tracker)")
    assert s.user_agent.startswith("Mozilla/5.0 (compatible; JobSearchDashboard/2.0")
    assert jc.SearchSettings(user_agent="Custom/1.0").user_agent == "Custom/1.0"
