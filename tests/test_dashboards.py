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


def test_config_dashboard_saves_preferences_and_sites(apps):
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
