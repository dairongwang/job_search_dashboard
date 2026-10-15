"""Configuration dashboard: the mirrored search-form panel, tested end to end against the Yahoo replica site."""

from __future__ import annotations

import http.server
import socketserver
import threading
from pathlib import Path

import pytest

import jobsearch_config as jc
import jobsearch_sources as js
from jobsearch_sources import browser, robots

AppTest = pytest.importorskip("streamlit.testing.v1").AppTest
ROOT = Path(__file__).resolve().parent.parent
YAHOO_FIX = ROOT / "tests" / "fixtures" / "yahoo"

pytestmark = pytest.mark.skipif(not browser.available()[0], reason="Playwright/Chromium not installed")


@pytest.fixture(scope="module")
def yahoo_server():
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a, **k):  # noqa: D401
            pass

    httpd = socketserver.TCPServer(("127.0.0.1", 0), lambda *a, **k: Quiet(*a, directory=str(YAHOO_FIX), **k))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


@pytest.fixture(autouse=True)
def _real_network():
    js.set_fetcher(None)
    robots.clear_cache()
    yield
    robots.clear_cache()


@pytest.fixture
def apps(config_path, tmp_path, monkeypatch):
    monkeypatch.setenv("JOB_SEARCH_DB", str(tmp_path / "test.db"))
    jc.save_config(jc.default_config())
    return config_path


def _button(at, label):
    found = [b for b in at.button if b.label == label]
    assert found, f"no button {label!r}; have {[b.label for b in at.button]}"
    return found[0]


def test_site_panel_find_jobs_then_save_enables_the_site(apps, yahoo_server):
    from jobsearch_sources import searchforms as sf

    cfg = jc.load_config()
    options = sf.form_site_options(sf.get("yahoo-careers"), f"{yahoo_server}/search.html", {"categories": ["Engineering"]})
    options.update({"delay_seconds": 0, "follow_links": "never"})
    cfg.sites.append(jc.SiteConfig(id="yahoo", provider="html", name="Yahoo (form)", enabled=False, options=options))
    jc.save_config(cfg)

    at = AppTest.from_file(str(ROOT / "config_dashboard.py"), default_timeout=120).run()
    assert not at.exception
    # the panel mirrors the site's form with the site's dropdown choices
    assert at.text_input(key="sf:yahoo:keyword").value == "data analyst"  # pre-filled from the preferred titles
    assert at.multiselect(key="sf:yahoo:categories").value == ["Engineering"]
    assert len(at.multiselect(key="sf:yahoo:countries").options) == 20 and "Yahoo Finance" in at.multiselect(key="sf:yahoo:brands").options
    assert any("has not passed a Find jobs test" in c.value for c in at.caption)

    at.text_input(key="sf:yahoo:keyword").set_value("analyst")
    at.multiselect(key="sf:yahoo:countries").set_value(["United States"])
    at.multiselect(key="sf:yahoo:brands").set_value(["Yahoo", "Yahoo Finance"])
    _button(at, "Find jobs").click().run()
    assert not at.exception
    assert any("Search test passed" in s.value and "3 job(s)" in s.value for s in at.success), [s.value for s in at.success]
    assert any("strategy yahoo-careers@2" in c.value for c in at.caption)
    assert jc.load_config().get_site("yahoo").enabled is False  # nothing saved yet

    assert any("the keyword box is left **empty**" in c.value for c in at.caption), [c.value for c in at.caption]  # nothing saved yet
    _button(at, "Save criteria & enable site").click().run()
    assert not at.exception
    site = jc.load_config().get_site("yahoo")
    assert site.enabled and site.options["search_form"]["validated"]["jobs"] == 3 and site.options["search_form"]["keyword_mode"] == "criteria"
    at = AppTest.from_file(str(ROOT / "config_dashboard.py"), default_timeout=120).run()
    assert any("the keyword box gets the saved keyword **analyst**" in c.value for c in at.caption), [c.value for c in at.caption]
    assert site.options["search_form"]["criteria"] == {"keyword": "analyst", "categories": ["Engineering"], "countries": ["United States"], "brands": ["Yahoo", "Yahoo Finance"], "experience": []}
    assert site.options["search_form"]["live_options"]["brands"][0] == "Boundless"
    assert jc.search_form_status(site)[0] is True


def test_site_panel_failed_test_does_not_enable(apps, yahoo_server):
    from jobsearch_sources import searchforms as sf

    cfg = jc.load_config()
    options = sf.form_site_options(sf.get("yahoo-careers"), f"{yahoo_server}/search.html", {})
    options.update({"delay_seconds": 0, "follow_links": "never"})
    cfg.sites.append(jc.SiteConfig(id="yahoo", provider="html", name="Yahoo (form)", enabled=False, options=options))
    jc.save_config(cfg)
    at = AppTest.from_file(str(ROOT / "config_dashboard.py"), default_timeout=120).run()
    at.text_input(key="sf:yahoo:keyword").set_value("astronaut")
    _button(at, "Find jobs").click().run()
    assert any("no job listings came back" in e.value for e in list(at.warning) + list(at.error)), [e.value for e in list(at.warning) + list(at.error)]
    assert not [b for b in at.button if b.label.startswith("Save criteria")]
    assert jc.load_config().get_site("yahoo").enabled is False
    # and the quick toggle refuses to enable it
    ms = {m.label: m for m in at.multiselect}
    ms["Quick toggle — enabled sites"].set_value(["remotive", "jobicy", "yahoo"])
    _button(at, "Apply quick toggle").click().run()
    assert any("only added to the job search when a test has returned jobs" in e.value for e in at.error)
    assert jc.load_config().get_site("yahoo").enabled is False


def test_add_site_with_search_form_requires_a_passing_test(apps, yahoo_server):
    at = AppTest.from_file(str(ROOT / "config_dashboard.py"), default_timeout=120).run()
    at.selectbox(key="add-form-strategy").set_value("yahoo-careers")
    at.text_input(key="add-form-url").set_value(f"{yahoo_server}/search.html")
    at.text_input(key="add-form-id").set_value("yahoo-form")
    at.text_input(key="add-form-name").set_value("Yahoo careers (form)")
    at.run()
    assert not at.exception
    assert at.multiselect(key="sf:new:categories").options[7] == "Engineering"
    # a search that returns nothing: no "Add site" button
    at.text_input(key="sf:new:keyword").set_value("analyst")
    at.multiselect(key="sf:new:countries").set_value(["Japan"])
    [b for b in at.button if b.label == "Find jobs" and "searchform-new" in str(b.key)][0].click().run()
    assert any("no job listings came back" in e.value for e in list(at.warning) + list(at.error))
    assert not [b for b in at.button if b.label == "Add site (validated)"]
    assert jc.load_config().get_site("yahoo-form") is None
    # a search that returns jobs: the site can be added, validated and enabled
    at.multiselect(key="sf:new:countries").set_value(["United States"])
    at.multiselect(key="sf:new:experience").set_value(["Individual Contributor"])
    at.checkbox(key="sf:new:keyword_mode").set_value(True)
    [b for b in at.button if b.label == "Find jobs" and "searchform-new" in str(b.key)][0].click().run()
    assert any("Search test passed" in s.value for s in at.success), [s.value for s in at.success]
    _button(at, "Add site (validated)").click().run()
    assert not at.exception
    site = jc.load_config().get_site("yahoo-form")
    assert site is not None and site.enabled and site.provider == "html" and site.options["search_form"]["keyword_mode"] == "titles"
    assert site.options["search_form"]["strategy"] == "yahoo-careers" and site.options["search_form"]["version"] == "2"
    assert site.options["search_form"]["criteria"]["countries"] == ["United States"] and site.options["search_form"]["validated"]["jobs"] == 3
    assert site.options["url"] == f"{yahoo_server}/search.html" and site.options["render"] == "always"
    assert not [i for i in jc.validate(jc.load_config()) if i.level == "error"]


def test_refresh_form_reads_live_choices(apps, yahoo_server):
    from jobsearch_sources import searchforms as sf

    cfg = jc.load_config()
    options = sf.form_site_options(sf.get("yahoo-careers"), f"{yahoo_server}/search.html", {})
    options.update({"delay_seconds": 0})
    cfg.sites.append(jc.SiteConfig(id="yahoo", provider="html", name="Yahoo (form)", enabled=False, options=options))
    jc.save_config(cfg)
    at = AppTest.from_file(str(ROOT / "config_dashboard.py"), default_timeout=120).run()
    _button(at, "Refresh form from the site").click().run()
    assert not at.exception
    assert any("matched yahoo-careers@2" in s.value for s in at.success), [s.value for s in list(at.success) + list(at.warning)]
    assert at.session_state["formopts:yahoo"]["experience"] == ["Developmental Programs", "Early Career", "Individual Contributor", "Management", "Sr Management", "Executive Leadership"]


def test_add_site_panel_shows_no_fake_jobs_for_an_empty_search(apps, yahoo_server):
    at = AppTest.from_file(str(ROOT / "config_dashboard.py"), default_timeout=120).run()
    at.selectbox(key="add-form-strategy").set_value("yahoo-careers")
    at.text_input(key="add-form-url").set_value(f"{yahoo_server}/search.html")
    at.text_input(key="add-form-id").set_value("yahoo")
    at.text_input(key="add-form-name").set_value("yahoo")
    at.run()
    at.text_input(key="sf:new:keyword").set_value("data analyst")
    at.multiselect(key="sf:new:categories").set_value(["Business Operations", "Engineering"])
    at.multiselect(key="sf:new:countries").set_value(["United States"])
    at.multiselect(key="sf:new:brands").set_value(["Boundless"])
    at.multiselect(key="sf:new:experience").set_value(["Individual Contributor"])
    [b for b in at.button if b.label == "Find jobs" and "searchform-new" in str(b.key)][0].click().run()
    assert not at.exception
    assert not [s for s in at.success if "Search test passed" in s.value]
    assert any("We currently do not have any jobs matching your criteria" in e.value for e in list(at.warning) + list(at.error))
    assert not at.dataframe or all("Job Search Filter" not in str(df.value) for df in at.dataframe)
    assert not [b for b in at.button if b.label == "Add site (validated)"]
    assert jc.load_config().get_site("yahoo") is None


def test_add_site_learns_a_new_version_when_the_page_changed(apps, yahoo_server):
    """The page matches no known version: Find jobs learns one, the panel switches to its fields, adding keeps it."""
    at = AppTest.from_file(str(ROOT / "config_dashboard.py"), default_timeout=120).run()
    at.selectbox(key="add-form-strategy").set_value("yahoo-careers")
    at.text_input(key="add-form-url").set_value(f"{yahoo_server}/redesign.html")
    at.text_input(key="add-form-id").set_value("yahoo-new")
    at.text_input(key="add-form-name").set_value("Yahoo (new layout)")
    at.run()
    at.text_input(key="sf:new:keyword").set_value("analyst")
    at.multiselect(key="sf:new:countries").set_value(["United States"])  # version-2 field: cannot be mapped onto the new form
    [b for b in at.button if b.label == "Find jobs" and "searchform-new" in str(b.key)][0].click().run()
    assert not at.exception
    assert any("was learned from it" in c.value or "learned from the live page" in c.value for c in at.caption), [c.value for c in at.caption]
    assert any("auto-1" in i.value for i in at.info)
    # the mirrored form now shows the learned version's controls
    assert at.text_input(key="sf:new:keyword").value == "analyst"
    assert at.multiselect(key="sf:new:loc").options == ["United States", "Ireland", "India"]
    assert at.selectbox(key="sf:new:team").options == ["(any)", "Engineering", "Marketing", "Finance"]
    at.multiselect(key="sf:new:loc").set_value(["United States"])
    at.selectbox(key="sf:new:team").set_value("Engineering")
    [b for b in at.button if b.label == "Find jobs" and "searchform-new" in str(b.key)][0].click().run()
    assert any("Search test passed" in s.value and "2 job(s)" in s.value for s in at.success), [s.value for s in at.success]
    _button(at, "Add site (validated)").click().run()
    assert not at.exception
    site = jc.load_config().get_site("yahoo-new")
    assert site is not None and site.enabled
    block = site.options["search_form"]
    assert block["strategy"] == "yahoo-careers" and block["version"] == "auto-1" and block["learned"][0]["fingerprint"][0] == "form#jobSearchV3"
    assert block["criteria"] == {"keyword": "analyst", "loc": ["United States"], "team": "Engineering"} and block["validated"]["jobs"] == 2
    # the site card now mirrors the learned version
    at = AppTest.from_file(str(ROOT / "config_dashboard.py"), default_timeout=120).run()
    assert at.multiselect(key="sf:yahoo-new:loc").value == ["United States"] and at.selectbox(key="sf:yahoo-new:team").value == "Engineering"
    assert any("configured version auto-1" in c.value and "learned" in c.value for c in at.caption)
