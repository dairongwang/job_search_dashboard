"""Reproduces the Indeed / Monster / Craigslist failures and checks the fixes."""

from __future__ import annotations

from datetime import date

import jobsearch_config as jc
import jobsearch_sources as js
from jobsearch_sources.filters import check_location, evaluate, implied_countries
from jobsearch_sources.http import classify_body
from jobsearch_sources.model import Job

HTML_PAGE = "<!DOCTYPE html><html><head><title>Jobs</title></head><body><div>listing</div></body></html>"
HTML_WITH_FEED = (
    '<!DOCTYPE html><html><head><link rel="alternate" type="application/rss+xml" title="Jobs" href="/jobs/feed.rss">'
    "</head><body>careers</body></html>"
)
FEED = (
    '<?xml version="1.0"?><rss version="2.0"><channel><title>Acme</title>'
    "<item><title>Data Analyst</title><link>https://acme.example.com/1</link><description>SQL</description></item>"
    "</channel></rss>"
)


def _user_sites(config: jc.AppConfig) -> None:
    config.sites = [
        jc.SiteConfig(id="indeed", provider="rss", name="Indeed", options={"url": "https://www.indeed.com/"}),
        jc.SiteConfig(id="monster", provider="rss", name="monster", options={"url": "https://www.monster.com/"}),
        jc.SiteConfig(id="craigslist", provider="rss", name="craigslist", options={"url": "https://www.craigslist.org/search/area/philadelphia?cat=jjj#search=2~thumb~0"}),
    ]


def test_classify_body():
    assert classify_body(HTML_PAGE.encode()) == "html"
    assert classify_body(FEED.encode()) == "feed"
    assert classify_body(b'{"jobs": []}') == "json"
    assert classify_body(b"\n  <feed xmlns='http://www.w3.org/2005/Atom'></feed>") == "feed"


def test_reported_failures_now_have_actionable_messages(config, transport):
    _user_sites(config)
    transport({
        "indeed.com": js.FetchError("HTTP 403 from www.indeed.com", status=403, url="https://www.indeed.com/"),
        "monster.com": js.FetchError("HTTP 403 from www.monster.com", status=403, url="https://www.monster.com/"),
        "craigslist.org": HTML_PAGE,
    })
    # live messages (registry bypassed)
    report = js.run_search(config, today=date(2026, 10, 12), registry=False)
    errors = dict(e.split(": ", 1) for e in report.errors)
    assert "refused automated access (HTTP 403)" in errors["Indeed"] and "Adzuna" in errors["Indeed"]
    assert "refused automated access (HTTP 403)" in errors["monster"]
    assert "web page (HTML), not an RSS/Atom feed" in errors["craigslist"] and "RSS feeds were retired" in errors["craigslist"]
    assert report.results == []
    # with the registry: seeded forbidden hosts are skipped without touching the site, and the saved warning is shown
    report = js.run_search(config, today=date(2026, 10, 12))
    errors = dict(e.split(": ", 1) for e in report.errors)
    assert all(e.startswith("skipped — ") for e in errors.values())
    assert "indeed.com forbids automated access (site registry" in errors["Indeed"]
    assert all(o.denied for o in report.outcomes)


def test_rss_adapter_follows_discovered_feed(config, transport):
    fake = transport({"careers.example.com/jobs/feed.rss": FEED, "careers.example.com": HTML_WITH_FEED})
    site = jc.SiteConfig(id="acme", provider="rss", name="Acme", options={"url": "https://careers.example.com/"})
    config.sites = [site]
    report = js.run_search(config, keyword="", today=date(2026, 10, 12))
    assert report.errors == []
    assert [job.title for job, _ in report.results] == ["Data Analyst"]
    assert fake.calls[1][0] == "https://careers.example.com/jobs/feed.rss"


def test_discover_feeds_parses_links_and_anchors():
    html = '<link rel="alternate" type="application/atom+xml" href="https://x.example.com/atom"><a href="/jobs.rss">rss</a>'
    assert js.discover_feeds(html, "https://x.example.com/page") == ["https://x.example.com/atom"]
    assert js.discover_feeds('<a href="/jobs?format=rss">feed</a>', "https://x.example.com/page") == ["https://x.example.com/jobs?format=rss"]
    assert js.discover_feeds(HTML_PAGE, "https://x.example.com/") == []


def test_probe_classifies_urls(transport):
    transport({
        "indeed.com": js.FetchError("HTTP 403 from www.indeed.com", status=403, url="https://www.indeed.com/"),
        "craigslist.org": HTML_PAGE,
        "other.example.com": HTML_PAGE,
        "careers.example.com/jobs/feed.rss": FEED,
        "careers.example.com": HTML_WITH_FEED,
        "api.example.com": b'{"jobs": []}',
        "down.example.com": js.FetchError("Cannot reach down.example.com (timed out)", url="https://down.example.com/"),
    })
    blocked = js.probe("https://www.indeed.com/")
    assert blocked.status == "blocked" and not blocked.ok and "Adzuna" in blocked.message
    page = js.probe("https://www.craigslist.org/search/philadelphia?cat=jjj")  # terms-based policy block: not even fetched
    assert page.status == "blocked" and not page.ok and "terms of use" in page.message and "RSS feeds were retired" in page.message
    page = js.probe("https://other.example.com/page", record=False)
    assert page.status == "html" and page.feeds == []
    discovered = js.probe("https://careers.example.com/")
    assert discovered.status == "html" and discovered.feeds == ["https://careers.example.com/jobs/feed.rss"]
    feed = js.probe("https://careers.example.com/jobs/feed.rss")
    assert feed.ok and feed.items == 1
    assert js.probe("https://api.example.com/v1", expect="json").ok
    assert js.probe("https://api.example.com/v1", expect="feed").status == "json"
    assert js.probe("https://down.example.com/").status == "error"


def test_known_site_guidance():
    assert "Indeed" in js.known_site_guidance("https://www.indeed.com/jobs?q=analyst")
    assert js.known_site_guidance("https://remotive.com/api") == ""


def test_dropped_reason_summary(config, transport):
    transport({"remotive.com": {"jobs": [
        {"id": 1, "title": "Data Analyst", "company_name": "A", "candidate_required_location": "Europe", "job_type": "full_time", "url": "https://r/1", "publication_date": "2026-10-10", "description": "SQL"},
        {"id": 2, "title": "Data Analyst", "company_name": "B", "candidate_required_location": "Europe", "job_type": "internship", "url": "https://r/2", "publication_date": "2026-10-10", "description": "SQL"},
    ]}, "jobicy.com": {"jobs": []}})
    config.preferences.locations = ["Philadelphia, PA"]
    config.preferences.job_types = ["permanent"]
    report = js.run_search(config, today=date(2026, 10, 12))
    assert report.fetched == 2 and report.results == []
    assert report.dropped["location"] == 2 and report.dropped["job type"] == 1


def test_city_implies_country_for_remote_roles():
    assert implied_countries("Philadelphia, PA") == ["united states"]
    assert implied_countries("London") == ["united kingdom"]
    assert implied_countries("Berlin") == []
    prefs = jc.JobPreferences(locations=["Philadelphia, PA"])
    assert check_location(Job(title="t", location="USA", workplace="remote"), prefs) == (True, False)
    assert check_location(Job(title="t", location="United States only", workplace="remote"), prefs) == (True, False)
    assert check_location(Job(title="t", location="Europe", workplace="remote"), prefs) == (False, False)
    # on-site roles elsewhere in the country still do not match a city preference
    assert check_location(Job(title="t", location="New York, USA", workplace="onsite"), prefs) == (False, False)
    assert evaluate(Job(title="Data Analyst", location="USA", workplace="remote"), prefs).passed
