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
