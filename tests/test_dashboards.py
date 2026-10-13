"""Headless UI tests with Streamlit's AppTest for both dashboards."""

from __future__ import annotations

from pathlib import Path

import pytest

import jobsearch_config as jc
from tests.conftest import load_fixture

AppTest = pytest.importorskip("streamlit.testing.v1").AppTest
ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def apps(config_path, tmp_path, monkeypatch):
    monkeypatch.setenv("JOB_SEARCH_DB", str(tmp_path / "test.db"))
    jc.save_config(jc.default_config())
    return config_path


def _buttons(at, label):
    return [b for b in at.button if b.label == label]


FEED = '<?xml version="1.0"?><rss version="2.0"><channel><title>A</title><item><title>Data Analyst</title><link>https://acme.example.com/1</link></item></channel></rss>'


def test_config_dashboard_saves_preferences_and_sites(apps, transport):
    transport({"acme.example.com": FEED})
    at = AppTest.from_file(str(ROOT / "config_dashboard.py"), default_timeout=60).run()
    assert not at.exception
    ms = {m.label: m for m in at.multiselect}
    ms["Target titles / keywords"].set_value(["data analyst", "BI analyst"])
    ms["Job types"].set_value(["permanent"])
    ms["Preferred locations"].set_value(["United States", "Philadelphia, PA"])
    ni = {n.label: n for n in at.number_input}
    ni["Minimum"].set_value(85000)
    _buttons(at, "Save preferences")[0].click().run()
    assert "Preferences saved." in [s.value for s in at.success]
    cfg = jc.load_config()
    assert cfg.preferences.titles == ["data analyst", "BI analyst"]
    assert cfg.preferences.job_types == ["permanent"]
    assert cfg.preferences.salary.minimum == 85000

    ms = {m.label: m for m in at.multiselect}
    ms["Quick toggle — enabled sites"].set_value(["remotive"])
    _buttons(at, "Apply quick toggle")[0].click().run()
    assert [s.id for s in jc.load_config().enabled_sites()] == ["remotive"]

    ti = {t.label: t for t in at.text_input}
    ti["Site id"].set_value("acme-rss")
    ti["Display name"].set_value("Acme RSS")
    ti["URL"].set_value("https://acme.example.com/jobs.rss")
    _buttons(at, "Create site")[0].click().run()
    assert jc.load_config().get_site("acme-rss").provider == "rss"

    ti = {t.label: t for t in at.text_input}
    ti["Site id"].set_value("Bad Id")
    ti["URL"].set_value("https://x.example.com")
    _buttons(at, "Create site")[0].click().run()
    assert any("Site id must be" in e.value for e in at.error)


def test_config_dashboard_blocks_invalid_save(apps):
    at = AppTest.from_file(str(ROOT / "config_dashboard.py"), default_timeout=60).run()
    ni = {n.label: n for n in at.number_input}
    ni["Minimum"].set_value(200000)
    ni["Maximum"].set_value(100000)
    _buttons(at, "Save preferences")[0].click().run()
    assert any("greater than maximum" in e.value for e in at.error)
    assert jc.load_config().preferences.salary.minimum is None  # unchanged on disk


def test_main_app_uses_config_for_search(apps, transport):
    cfg = jc.load_config()
    cfg.preferences.locations = ["United States"]
    cfg.preferences.salary = jc.SalaryRange(minimum=80000)
    jc.save_config(cfg)
    transport({"remotive.com": load_fixture("remotive.json"), "jobicy.com": load_fixture("jobicy.json")})

    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60).run()
    assert not at.exception
    at.sidebar.radio[0].set_value("Research").run()
    _buttons(at, "Search listings")[0].click().run()
    assert not at.exception
    results = at.dataframe[1].value
    assert list(results["title"]) == ["Senior Data Analyst", "Data Analyst (Contract)"]
    assert results.iloc[0]["matched_skills"] == "SQL, Python, Tableau"

    save = [m for m in at.multiselect if m.label == "Save into the tracker"][0]
    save.set_value([save.options[0]])
    _buttons(at, "Save selected")[0].click().run()
    assert "Saved 1. Already tracked: 0." in [s.value for s in at.success]

    at.sidebar.radio[0].set_value("Jobs").run()
    jobs = at.dataframe[0].value
    assert jobs.iloc[0]["job_type"] == "permanent" and jobs.iloc[0]["salary"] == "$90k - $120k / year"

    at.sidebar.radio[0].set_value("Configuration").run()
    assert not at.exception and "Configuration is valid." in [s.value for s in at.success]


def test_main_app_hot_reloads_config(apps, transport):
    transport({"remotive.com": {"jobs": []}, "jobicy.com": {"jobs": []}})
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60).run()
    assert "Searching 2 site(s)" in " ".join(c.value for c in at.sidebar.caption)
    cfg = jc.load_config()
    cfg.get_site("jobicy").enabled = False
    import os, time
    jc.save_config(cfg)
    os.utime(jc.config_path(), (time.time() + 5, time.time() + 5))  # guarantee a different mtime
    at.run()
    assert "Searching 1 site(s): Remotive" in " ".join(c.value for c in at.sidebar.caption)


def test_config_dashboard_refuses_non_feed_urls(apps, transport):
    import jobsearch_sources as js

    transport({
        "indeed.com": js.FetchError("HTTP 403 from www.indeed.com", status=403, url="https://www.indeed.com/"),
        "craigslist.org": "<!DOCTYPE html><html><body>page</body></html>",
        "careers.example.com/feed.rss": FEED,
        "careers.example.com": '<!DOCTYPE html><html><head><link rel="alternate" type="application/rss+xml" href="/feed.rss"></head></html>',
    })
    at = AppTest.from_file(str(ROOT / "config_dashboard.py"), default_timeout=60).run()

    def create(sid, url):
        ti = {t.label: t for t in at.text_input}
        ti["Site id"].set_value(sid)
        ti["Display name"].set_value(sid)
        ti["URL"].set_value(url)
        _buttons(at, "Create site")[0].click().run()

    create("indeed", "https://www.indeed.com/")
    assert any("refused automated access" in e.value and "Adzuna" in e.value for e in at.error)
    assert any("Indeed publishes no feed" in w.value for w in at.warning)  # shown as soon as the URL is typed
    assert jc.load_config().get_site("indeed") is None

    create("craigslist", "https://www.craigslist.org/search/area/philadelphia?cat=jjj")
    assert any("web page (HTML)" in e.value for e in at.error)
    assert jc.load_config().get_site("craigslist") is None

    create("acme", "https://careers.example.com/")
    assert jc.load_config().get_site("acme").options["url"] == "https://careers.example.com/feed.rss"
    assert any("advertised a feed" in s.value for s in at.success)


def test_main_app_explains_dropped_listings(apps, transport):
    transport({"remotive.com": {"jobs": [
        {"id": 1, "title": "Data Analyst", "company_name": "A", "candidate_required_location": "Europe", "job_type": "full_time",
         "url": "https://r/1", "publication_date": "2026-10-10", "description": "SQL"}]}, "jobicy.com": {"jobs": []}})
    cfg = jc.load_config()
    cfg.preferences.locations = ["Philadelphia, PA"]
    jc.save_config(cfg)
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60).run()
    at.sidebar.radio[0].set_value("Research").run()
    _buttons(at, "Search listings")[0].click().run()
    assert not at.exception
    assert any("removed by your preferences" in i.value and "location (1)" in i.value for i in at.info)


def test_config_dashboard_registry_tab_and_enforcement(apps, transport):
    transport({
        "/robots.txt": "User-agent: *\nAllow: /\n",
        "wall.example.com": __import__("jobsearch_sources").FetchError("HTTP 403 from wall.example.com", status=403, url="https://wall.example.com/jobs"),
    })
    at = AppTest.from_file(str(ROOT / "config_dashboard.py"), default_timeout=60).run()
    # registry table is rendered with the seeded rows
    table = next(df.value for df in at.dataframe if "host" in getattr(df.value, "columns", []))
    assert {"host", "active", "status", "checks", "created", "updated", "message"} <= set(table.columns)
    assert "indeed.com" in set(table["host"]) and not table.set_index("host").loc["indeed.com", "active"]

    # creating a web-page site on a host that answers 403: refused + recorded
    ti = {t.label: t for t in at.text_input}
    sb = {s.label: s for s in at.selectbox}
    sb["Type"].set_value(next(o for o in sb["Type"].options if "Web page" in str(o)))
    ti["Site id"].set_value("wall")
    ti["URL"].set_value("https://wall.example.com/jobs")
    _buttons(at, "Create site")[0].click().run()
    assert any("refused automated access" in e.value for e in at.error)
    assert jc.load_config().get_site("wall") is None
    row = jc.load_registry().lookup("wall.example.com")
    assert row is not None and not row.active and row.checks == 1

    # skipping the check does not bypass the registry
    cb = {c.label: c for c in at.checkbox}
    cb["Skip the URL check (not recommended)"].set_value(True)
    ti = {t.label: t for t in at.text_input}
    ti["Site id"].set_value("wall2")
    ti["URL"].set_value("https://wall.example.com/other")
    _buttons(at, "Create site")[0].click().run()
    assert any("forbids automated access (site registry" in e.value for e in at.error)
    assert jc.load_config().get_site("wall2") is None


def test_enabling_a_forbidden_site_is_rejected(apps):
    cfg = jc.load_config()
    cfg.sites.append(jc.SiteConfig(id="indeed", provider="html", name="Indeed", enabled=False, options={"url": "https://www.indeed.com/jobs?q=x"}))
    jc.save_config(cfg)
    at = AppTest.from_file(str(ROOT / "config_dashboard.py"), default_timeout=60).run()
    ms = {m.label: m for m in at.multiselect}
    ms["Quick toggle — enabled sites"].set_value(["remotive", "jobicy", "indeed"])
    _buttons(at, "Apply quick toggle")[0].click().run()
    assert any("indeed.com forbids automated access" in e.value for e in at.error)
    assert jc.load_config().get_site("indeed").enabled is False


def test_investigate_panel_suggests_and_adds_workday_site(apps, transport):
    from jobsearch_sources import robots

    robots.clear_cache()
    transport({
        "/robots.txt": "User-agent: *\nAllow: /\n",
        "yahooinc.com": '<html><body><input placeholder="Key words"><button>Find jobs</button>'
        '<a href="https://ouryahoo.wd5.myworkdayjobs.com/careers/job/X/Y_R1">apply</a></body></html>',
    })
    at = AppTest.from_file(str(ROOT / "config_dashboard.py"), default_timeout=60).run()
    ti = {t.label: t for t in at.text_input}
    ti["Careers URL"].set_value("https://www.yahooinc.com/careers/")
    at.run()  # enables the button
    _buttons(at, "Investigate")[0].click().run()
    assert not at.exception
    assert any("crawlable" in s.value and "Workday" in s.value for s in at.success)
    _buttons(at, "Add suggested site")[0].click().run()
    site = jc.load_config().get_site("yahooinc-com-workday")
    assert site is not None and site.provider == "workday" and site.options["tenant"] == "ouryahoo" and site.options["site"] == "careers"


def test_platform_tab_creates_site(apps):
    at = AppTest.from_file(str(ROOT / "config_dashboard.py"), default_timeout=60).run()
    sb = {s.label: s for s in at.selectbox}
    sb["Platform"].set_value(next(o for o in sb["Platform"].options if "Greenhouse" in str(o)))
    at.run()
    by_key = {t.key: t for t in at.text_input}
    by_key["add-platform-id"].set_value("airbnb-gh")
    by_key["add-platform-name"].set_value("Airbnb")
    by_key["add-platform:greenhouse:board"].set_value("airbnb")
    _buttons(at, "Create platform site")[0].click().run()
    assert not at.exception, at.exception
    site = jc.load_config().get_site("airbnb-gh")
    assert site is not None and site.provider == "greenhouse" and site.options["board"] == "airbnb" and site.enabled
