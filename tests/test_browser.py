"""Real headless-browser rendering against a local JavaScript-driven page."""

from __future__ import annotations

import http.server
import socketserver
import threading
from pathlib import Path

import pytest

import jobsearch_config as jc
import jobsearch_sources as js
from jobsearch_sources import browser, robots

pytestmark = pytest.mark.skipif(not browser.available()[0], reason="Playwright/Chromium not installed")

SITE = Path(__file__).parent / "fixtures" / "jssite"


@pytest.fixture(scope="module")
def server():
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a, **k):  # noqa: D401
            pass

        def guess_type(self, path):  # extension-less job pages are HTML
            return "text/html" if "." not in Path(path).name else super().guess_type(path)

    handler = Quiet
    httpd = socketserver.TCPServer(("127.0.0.1", 0), lambda *a, **k: handler(*a, directory=str(SITE), **k))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


@pytest.fixture(autouse=True)
def _real_network():
    js.set_fetcher(None)
    robots.clear_cache()
    yield
    robots.clear_cache()


def test_render_pages_executes_javascript(server):
    pages = browser.render_pages([f"{server}/board.html", f"{server}/nope.html"], delay_seconds=0)
    assert pages[0].status == 200 and "Data Analyst (JS)" in pages[0].html and not pages[0].denied
    assert pages[1].status == 404


def test_provider_falls_back_to_browser_for_js_pages(server, config):
    config.preferences.locations = ["Philadelphia, PA"]
    opts = jc.default_options("html")
    opts.update({"url": f"{server}/board.html", "delay_seconds": 0, "render": "auto"})
    config.sites = [jc.SiteConfig(id="spa", provider="html", name="SPA board", options=opts)]
    report = js.run_search(config, keyword="")
    assert report.errors == [], report.errors
    titles = {job.title for job, _ in report.results}
    assert "Data Analyst (JS)" in titles
    assert "rendered" in report.outcomes[0].note
    assert jc.load_registry().lookup(server).status == "ok"
    # plain HTTP only: the same page yields nothing and says why
    config.sites[0].options["render"] = "never"
    robots.clear_cache()
    report = js.run_search(config, keyword="")
    assert "render results with JavaScript" in report.errors[0]


YAHOO_STYLE_STEPS = [
    {"fill": {"placeholder": "Key words"}, "value": "{keyword}"},
    {"click": {"text": "Select job categories"}},
    {"click": {"option": "{category}"}},
    {"select": {"label": "Select countries"}, "value": "{country}"},
    {"check": {"label": "{brands}"}},
    {"click": {"button": "Find jobs"}},
    {"wait": {"css": "#results li"}},
    {"click": {"button": "Load more"}, "repeat": 3, "optional": True, "snapshot": True},
]


def test_search_form_steps_drive_the_page_like_a_user(server, config):
    config.preferences.locations = []
    config.preferences.posted_within_days = None
    opts = jc.default_options("html")
    opts.update({
        "url": f"{server}/findjobs.html",
        "delay_seconds": 0,
        "render": "auto",
        "follow_links": "always",
        "actions": YAHOO_STYLE_STEPS,
        "form_values": {"category": "Engineering", "country": "United States", "brands": ["Yahoo", "Yahoo Finance"]},
    })
    config.sites = [jc.SiteConfig(id="findjobs", provider="html", name="Find jobs", options=opts)]
    report = js.run_search(config, keyword="analyst", strict=False)
    assert report.errors == [], report.errors
    titles = {job.title for job, _ in report.results}
    # keyword 'analyst' + Engineering + United States + brands Yahoo/Yahoo Finance -> 77, 78, 82 (not Marketing 79, Canada 80, AOL 81)
    assert titles == {"Data Analyst (JS)", "Senior Data Analyst", "Analyst, Ads"}, titles
    senior = next(job for job, _ in report.results if job.title == "Senior Data Analyst")
    assert senior.salary_min == 120000 and senior.organization == "Yahoo Finance" and senior.job_type == "permanent"
    note = report.outcomes[0].note
    assert "rendered" in note and "search form" not in note  # all steps succeeded


def test_search_form_step_failure_is_reported(server, config):
    opts = jc.default_options("html")
    opts.update({"url": f"{server}/findjobs.html", "delay_seconds": 0, "actions": [{"click": {"button": "No such button"}, "timeout_ms": 800}]})
    config.sites = [jc.SiteConfig(id="findjobs", provider="html", name="Find jobs", options=opts)]
    report = js.run_search(config, keyword="")
    assert "search form: step 1" in report.outcomes[0].note and "failed" in report.outcomes[0].note


def test_expand_steps_substitutes_and_repeats():
    from jobsearch_sources.htmlpages import expand_steps

    steps = expand_steps(
        [{"fill": {"placeholder": "Key words"}, "value": "{keyword}"}, {"check": {"label": "{brands}"}}, {"click": {"option": "{missing}"}}],
        {"keyword": "analyst", "brands": ["Yahoo", "AOL"]},
    )
    assert steps[0]["value"] == "analyst"
    assert [s["check"]["label"] for s in steps[1:3]] == ["Yahoo", "AOL"]
    assert steps[3]["click"]["option"] == "{missing}"


# ---------------------------------------------------------------------------
# Search-form strategies (Yahoo careers replica: collapsed filter form, checkbox dropdowns, JS results, Load more)
# ---------------------------------------------------------------------------

YAHOO_FIX = Path(__file__).parent / "fixtures" / "yahoo"


@pytest.fixture(scope="module")
def yahoo_server():
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a, **k):  # noqa: D401
            pass

    httpd = socketserver.TCPServer(("127.0.0.1", 0), lambda *a, **k: Quiet(*a, directory=str(YAHOO_FIX), **k))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def yahoo_site(url: str, criteria: dict, version: str = "2", **extra) -> jc.SiteConfig:
    from jobsearch_sources import searchforms as sf

    options = sf.form_site_options(sf.get("yahoo-careers", version), url, criteria)
    options.update({"delay_seconds": 0, "pages": 3, **extra})
    options["search_form"]["validated"] = {"at": "2026-03-01T09:00:00", "jobs": 1, "strategy": f"yahoo-careers@{version}"}
    return jc.SiteConfig(id="yahoo", provider="html", name="Yahoo (form)", enabled=True, options=options)


def test_yahoo_strategy_drives_the_filter_form_and_reads_the_result_table(yahoo_server, config):
    config.preferences.locations = []
    config.preferences.posted_within_days = None
    site = yahoo_site(f"{yahoo_server}/search.html", {"categories": ["Engineering"], "countries": ["United States"], "brands": ["Yahoo", "Yahoo Finance"]}, follow_links="always")
    config.sites = [site]
    report = js.run_search(config, keyword="analyst", strict=False)
    assert report.errors == [], report.errors
    titles = {job.title for job, _ in report.results}
    # keyword + Engineering + United States + Yahoo/Yahoo Finance -> 101, 102, 109 (not 103 Software Dev, 104 India, 105 Marketing, 107 Ireland)
    assert titles == {"Senior Data Analyst", "Data Analyst, Ads", "Staff Data Analyst"}, titles
    senior = next(job for job, _ in report.results if job.title == "Senior Data Analyst")
    assert senior.organization == "Yahoo Finance" and senior.location == "United States of America"  # from the result table
    assert senior.salary_min == 120000 and senior.job_type == "permanent" and "Tableau" in senior.description  # from the job page
    staff = next(job for job, _ in report.results if job.title == "Staff Data Analyst")
    assert staff.job_type == "contract"
    outcome = report.outcomes[0]
    assert "rendered" in outcome.note and "search form" not in outcome.note and not outcome.form_changed
    info = outcome.details["search_form"]
    assert info["matched"] == "yahoo-careers@2" and not info["changed"] and info["runs"][0]["total"] == 3
    assert info["live_options"]["categories"][:2] == ["Administration", "Business Development"]
    assert jc.load_registry().lookup(yahoo_server).status == "ok"


def test_yahoo_strategy_collects_load_more_pages_and_pushes_the_keyword(yahoo_server, config):
    config.preferences.locations = []
    config.preferences.posted_within_days = None
    site = yahoo_site(f"{yahoo_server}/search.html", {"countries": ["United States"]}, follow_links="never")
    site.max_results = 50
    config.sites = [site]
    report = js.run_search(config, keyword="", strict=False)  # no keyword: the site's own filter only
    assert report.errors == [], report.errors
    assert report.fetched == 7 and report.outcomes[0].details["search_form"]["runs"][0]["total"] == 7  # 3 + Load more x2
    report = js.run_search(config, keyword="data analyst", strict=False)
    assert {job.title for job, _ in report.results} == {"Senior Data Analyst", "Data Analyst, Ads", "Staff Data Analyst"}


def test_search_form_falls_back_to_the_landing_page_version_and_reports_the_change(yahoo_server, config):
    """The site configured with the search-page form (v2) but pointed at the landing page (v1 layout, posts to the results page)."""
    config.preferences.locations = []
    config.preferences.posted_within_days = None
    site = yahoo_site(f"{yahoo_server}/landing.html", {"categories": ["Engineering"], "countries": ["United States"], "brands": ["Yahoo", "Yahoo Finance"]}, follow_links="never")
    config.sites = [site]
    report = js.run_search(config, keyword="analyst", strict=False)
    assert report.errors == [], report.errors
    outcome = report.outcomes[0]
    assert "the search form changed" in outcome.note and "version 1" in outcome.note
    assert outcome.details["search_form"]["matched"] == "yahoo-careers@1" and outcome.details["search_form"]["changed"]
    assert {job.title for job, _ in report.results} == {"Senior Data Analyst", "Data Analyst, Ads", "Staff Data Analyst"}


def test_search_form_redesign_is_learned_used_and_saved(yahoo_server, config):
    """No known version matches the redesigned page: a version is learned from it, used, and (once saved) reused directly."""
    from jobsearch_sources import searchforms as sf

    config.preferences.locations = []
    config.preferences.posted_within_days = None
    site = yahoo_site(f"{yahoo_server}/redesign.html", {"categories": ["Engineering"], "countries": ["United States"]}, follow_links="never")
    config.sites = [site]
    report = js.run_search(config, keyword="analyst", strict=False)
    assert report.errors == [], report.errors
    outcome = report.outcomes[0]
    info = outcome.details["search_form"]
    assert info["matched"] == "yahoo-careers@auto-1" and info["learned"]["fingerprint"][0] == "form#jobSearchV3"
    assert "a new version (auto-1) was learned from it" in outcome.note
    assert {job.title for job, _ in report.results} == {"Senior Data Analyst", "Data Analyst, Ads", "Marketing Analyst", "Data Analyst (Dublin)"}
    # the dashboard's test run carries the learned version; saving it makes it the configured version
    test = sf.test_form(site, config, {"keyword": "analyst", "loc": ["United States"], "team": "Engineering"}, learned=info["learned"])
    assert test.ok and test.learned["version"] == "auto-1" and [j.title for j in test.jobs] == ["Senior Data Analyst", "Data Analyst, Ads"]
    sf.mark_validated(site, test)
    assert site.options["search_form"]["version"] == "auto-1" and site.options["search_form"]["criteria"] == {"keyword": "analyst", "loc": ["United States"], "team": "Engineering"}
    report = js.run_search(config, keyword="data analyst", strict=False)
    assert report.errors == [] and report.outcomes[0].details["search_form"]["matched"] == "yahoo-careers@auto-1"
    assert report.outcomes[0].details["search_form"]["learned"] is None  # used directly, nothing re-learned
    assert {job.title for job, _ in report.results} == {"Senior Data Analyst", "Data Analyst, Ads"}
    # a learned form that finds nothing stays empty (the footer/nav links are never listings)
    report = js.run_search(config, keyword="astronaut")
    assert report.outcomes[0].empty and report.outcomes[0].fetched == 0 and "no job listings came back" in report.errors[0]


def test_search_form_redesign_without_learning_is_detected_not_silently_empty(yahoo_server, config):
    site = yahoo_site(f"{yahoo_server}/redesign.html", {"categories": ["Engineering"]})
    site.options["search_form"]["learn"] = False
    config.sites = [site]
    report = js.run_search(config, keyword="analyst")
    outcome = report.outcomes[0]
    assert outcome.form_changed and not outcome.denied
    assert "no longer matches any known version" in outcome.error and "yahoo-careers@2 (2026-02), yahoo-careers@1 (2026-02)" in outcome.error
    assert jc.load_registry().lookup(yahoo_server).status == "error"


def test_test_form_service_passes_and_fails_like_the_dashboard(yahoo_server, config):
    from jobsearch_sources import searchforms as sf

    site = yahoo_site(f"{yahoo_server}/search.html", {}, follow_links="never")
    site.enabled = False
    site.options["search_form"].pop("validated")
    test = sf.test_form(site, config, {"keyword": "analyst", "countries": ["United States"], "brands": ["Yahoo Finance"]})
    assert test.ok and [j.title for j in test.jobs] == ["Senior Data Analyst", "Staff Data Analyst"] and test.total == 2
    assert test.matched == "yahoo-careers@2" and not test.changed and test.live_options["brands"][1] == "Yahoo"
    assert test.unknown_choices == [] and "2 job(s) of 2" in test.summary()
    sf.mark_validated(site, test)
    site.enabled = True
    config.sites = [site]
    assert not [i for i in jc.validate(config, registry=False) if i.level == "error"]
    assert site.options["search_form"]["criteria"]["brands"] == ["Yahoo Finance"] and site.options["search_form"]["validated"]["jobs"] == 2
    # a combination the site has no jobs for: the test fails and nothing would be saved
    failed = sf.test_form(site, config, {"keyword": "analyst", "countries": ["Japan"]})
    assert not failed.ok and failed.jobs == [] and "no job listings came back" in failed.error and "Select countries: Japan" in failed.error
    assert failed.validated_record()["jobs"] == 0
    # a choice the live form does not offer is reported
    odd = sf.test_form(site, config, {"keyword": "analyst", "brands": ["Yahoo Finance", "Flickr"]})
    assert odd.ok and odd.unknown_choices and odd.unknown_choices[0].startswith("Select brands: Flickr not offered")


def test_detect_reads_the_form_in_the_browser(yahoo_server):
    from jobsearch_sources import searchforms as sf

    report = sf.detect(f"{yahoo_server}/search.html", options={"search_form": {"strategy": "yahoo-careers", "version": "2"}})
    assert report.ok and report.rendered and report.matched == "yahoo-careers@2"
    assert len(report.live_options["countries"]) == 20 and report.live_options["experience"][0] == "Developmental Programs"
    report = sf.detect(f"{yahoo_server}/landing.html", options={"search_form": {"strategy": "yahoo-careers", "version": "2"}})
    assert report.matched == "yahoo-careers@1" and report.changed and len(report.live_options["brands"]) == 8
    report = sf.detect(f"{yahoo_server}/redesign.html", options={"search_form": {"strategy": "yahoo-careers"}})
    assert report.ok and report.learned and report.matched == "yahoo-careers@auto-1" and "was derived from it" in report.message
    report = sf.detect(f"{yahoo_server}/redesign.html", options={"search_form": {"strategy": "yahoo-careers"}}, learn=False)
    assert not report.ok and "no longer matches" in report.message


def test_empty_search_result_stays_empty_in_the_browser(yahoo_server, config):
    """Regression: an empty result table used to fall back to the page's /careers navigation links ('Job Search Filter' jobs)."""
    from jobsearch_sources import searchforms as sf

    site = yahoo_site(f"{yahoo_server}/search.html", {"categories": ["Business Operations", "Engineering"], "countries": ["United States"], "brands": ["Boundless"], "experience": ["Individual Contributor"]}, follow_links="always")
    config.sites = [site]
    report = js.run_search(config, keyword="data analyst", strict=False)
    assert report.results == [] and report.fetched == 0
    outcome = report.outcomes[0]
    assert outcome.empty and outcome.fetched == 0 and not outcome.form_changed
    assert "no job listings came back" in outcome.error and "We currently do not have any jobs matching your criteria" in outcome.error
    assert outcome.details["search_form"]["runs"][0]["total"] == 0 and outcome.details["search_form"]["runs"][0]["owns_results"]
    test = sf.test_form(site, config, site.options["search_form"]["criteria"] | {"keyword": "data analyst"})
    assert not test.ok and test.jobs == [] and test.total == 0 and "We currently do not have any jobs" in test.error


def test_search_submits_the_saved_keyword_not_the_preferred_titles(yahoo_server, config):
    """Regression: a site validated with an empty keyword box must be searched with an empty keyword box."""
    config.preferences.locations = []
    config.preferences.posted_within_days = None
    config.preferences.titles = ["data analyst"]
    site = yahoo_site(f"{yahoo_server}/search.html", {"keyword": "", "countries": ["United States"]}, follow_links="never")
    site.max_results = 50
    config.sites = [site]
    report = js.run_search(config, strict=False)  # no override: the saved (empty) keyword is submitted
    assert report.errors == [], report.errors
    assert report.fetched == 7 and report.outcomes[0].details["search_form"]["runs"][0]["criteria"]["keyword"] == ""
    site.options["search_form"]["keyword_mode"] = "titles"  # opted in: the preferred title goes into the keyword box
    report = js.run_search(config, strict=False)
    assert {job.title for job, _ in report.results} == {"Senior Data Analyst", "Data Analyst, Ads", "Staff Data Analyst"}
    report = js.run_search(config, keyword="marketing", strict=False)  # a Research-page keyword wins for that run
    assert {job.title for job, _ in report.results} == {"Marketing Analyst"}
