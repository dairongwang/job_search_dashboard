"""Access policy: sticky terms-based blocks, refusal to add, daily compliance scan, administrator switch."""

from __future__ import annotations

from pathlib import Path

import pytest

import jobsearch_config as jc
import jobsearch_sources as js
from jobsearch_sources import robots

ROOT = Path(__file__).resolve().parent.parent
CRAIGSLIST = "https://www.craigslist.org/search/area/philadelphia?cat=jjj#search=2~thumb~0"
PAGE = "<!DOCTYPE html><html><head><title>jobs</title></head><body><div class='listing'>nothing here</div></body></html>"
ROBOTS_OK = "User-agent: *\nAllow: /\n"


@pytest.fixture(autouse=True)
def _fresh_robots():
    robots.clear_cache()
    yield
    robots.clear_cache()


# --- registry: a terms-based block is policy, not a fetch result ---------------------------------------


def test_terms_block_is_not_lifted_by_a_successful_fetch():
    registry = jc.load_registry()
    row = registry.lookup(CRAIGSLIST)
    assert row is not None and row.policy_block and row.reason == "terms" and not row.active
    registry.record(CRAIGSLIST, "empty", "Reachable.", source="probe", status_code=200)  # what investigate used to do
    row = jc.load_registry().lookup(CRAIGSLIST)
    assert not row.active and row.status == "forbidden" and row.reason == "terms" and "terms prohibit robots" in row.message
    assert row.checks == 1 and row.last_url == CRAIGSLIST
    # technical blocks (403 / robots) do recover when the site allows access again
    registry.record("https://wall.example.com/jobs", "forbidden", "the site refused automated access (HTTP 403)", status_code=403, reason="http")
    assert jc.load_registry().lookup("wall.example.com").reason == "http"
    registry.record("https://wall.example.com/jobs", "ok", "fine")
    assert jc.load_registry().lookup("wall.example.com").active
    # only an administrator override lifts a terms block
    registry.set_active("craigslist.org", True, message="lifted")
    assert jc.load_registry().lookup(CRAIGSLIST).active
    registry.set_active("newboard.example.com", False, message="terms say no", reason="terms")
    assert jc.load_registry().lookup("https://newboard.example.com/x").policy_block
    assert jc.block_reason("robots.txt disallows /x") == "robots" and jc.block_reason("x", 403) == "http" and jc.block_reason("terms prohibit") == "terms"


def test_investigate_refuses_a_host_whose_terms_prohibit_robots(transport):
    fake = transport({"/robots.txt": ROBOTS_OK, "craigslist.org": PAGE})
    report = js.investigate(CRAIGSLIST, render=False)
    assert report.verdict == "forbidden" and report.denied and report.suggested_site is None and report.suggested_form_site is None
    assert "prohibits automated access by its terms of use" in report.summary and "RSS feeds were retired" in report.summary
    assert fake.calls == []  # not even fetched
    row = jc.load_registry().lookup(CRAIGSLIST)
    assert not row.active and row.reason == "terms" and row.checks == 1
    assert "Verdict: forbidden" in js.format_report(report)
    # the search-form detector and the URL probe refuse too
    detection = js.searchforms.detect(CRAIGSLIST, options={"search_form": {"strategy": "yahoo-careers"}}, render=False)
    assert detection.denied and "terms of use" in detection.error
    assert js.probe(CRAIGSLIST, expect="html").status == "blocked"
    assert fake.calls == []


def test_config_dashboard_does_not_offer_to_add_a_policy_blocked_host(config_path, tmp_path, monkeypatch, transport):
    AppTest = pytest.importorskip("streamlit.testing.v1").AppTest
    monkeypatch.setenv("JOB_SEARCH_DB", str(tmp_path / "t.db"))
    jc.save_config(jc.default_config())
    transport({"/robots.txt": ROBOTS_OK, "craigslist.org": PAGE})
    at = AppTest.from_file(str(ROOT / "config_dashboard.py"), default_timeout=60).run()
    at.text_input(key="inv-url").set_value(CRAIGSLIST).run()
    [b for b in at.button if b.label == "Investigate"][0].click().run()
    assert not at.exception
    assert any("forbidden" in e.value and "terms of use" in e.value for e in at.error), [e.value for e in at.error]
    assert not [b for b in at.button if b.label in ("Add suggested site", "Add search-form site (disabled until tested)")]
    # the search-form tab refuses the host before any test
    at.selectbox(key="add-form-strategy").set_value("yahoo-careers")
    at.text_input(key="add-form-url").set_value("https://www.craigslist.org/search/jjj").run()
    assert any("prohibits automated access by its terms" in e.value for e in at.error)
    assert not [b for b in at.button if b.label == "Find jobs" and "searchform-new" in str(b.key)]


# --- compliance scan -------------------------------------------------------------------------------


def _sites(config):
    config.sites = [
        jc.SiteConfig(id="ok-feed", provider="rss", name="OK feed", enabled=True, options={"url": "https://good.example.com/jobs.rss"}),
        jc.SiteConfig(id="walled", provider="html", name="Walled page", enabled=True, options={**jc.default_options("html"), "url": "https://wall.example.com/jobs"}),
        jc.SiteConfig(id="robotted", provider="json", name="Robotted API", enabled=True, options={**jc.default_options("json"), "url": "https://norobots.example.com/api/jobs"}),
        jc.SiteConfig(id="craig", provider="html", name="Craigslist", enabled=True, options={**jc.default_options("html"), "url": "https://www.craigslist.org/search/jjj"}),
        jc.SiteConfig(id="down", provider="rss", name="Down", enabled=True, options={"url": "https://down.example.com/feed"}),
        jc.SiteConfig(id="remotive", provider="remotive", name="Remotive", enabled=True),
    ]


def test_compliance_scan_disables_sites_that_are_no_longer_allowed(config, transport):
    _sites(config)
    jc.save_config(config)
    transport({
        "norobots.example.com/robots.txt": "User-agent: *\nDisallow: /api\n",
        "/robots.txt": ROBOTS_OK,
        "good.example.com": "<?xml version='1.0'?><rss><channel></channel></rss>",
        "wall.example.com": js.FetchError("HTTP 403 from wall.example.com", status=403, url="https://wall.example.com/jobs"),
        "craigslist.org": PAGE,
        "down.example.com": js.FetchError("Cannot reach down.example.com (timed out)", url="https://down.example.com/feed"),
    })
    report = js.compliance.scan(config)
    by_id = {r.site_id: r for r in report.results}
    assert set(by_id) == {"ok-feed", "walled", "robotted", "craig", "down"}  # built-in API providers are not scanned
    assert by_id["ok-feed"].compliant and not by_id["ok-feed"].disabled
    assert by_id["walled"].compliant is False and by_id["walled"].reason == "http" and by_id["walled"].disabled
    assert by_id["robotted"].compliant is False and by_id["robotted"].reason == "robots" and by_id["robotted"].disabled
    assert by_id["craig"].compliant is False and by_id["craig"].reason == "terms" and by_id["craig"].disabled
    assert by_id["down"].compliant is None and by_id["down"].reason == "error" and not by_id["down"].disabled  # unreachable ≠ forbidden
    assert report.config_saved and "3 non-compliant" in report.summary() and "3 disabled" in report.summary()
    saved = jc.load_config()
    assert [s.id for s in saved.enabled_sites()] == ["ok-feed", "down", "remotive"]
    assert saved.get_site("walled").notes.startswith("[compliance ") and "HTTP 403" in saved.get_site("walled").notes
    registry = jc.load_registry()
    assert registry.lookup("wall.example.com").reason == "http" and registry.lookup("norobots.example.com").reason == "robots"
    assert registry.lookup("good.example.com").active and registry.lookup("good.example.com").source == "scan"
    stamp, summary = js.compliance.last_scan(registry)
    assert stamp == report.checked_at and summary == report.summary()
    assert not js.compliance.due(saved, registry)  # just ran
    saved.search.compliance_scan_hours = 0
    assert not js.compliance.due(saved, registry)
    saved.search.compliance_scan_hours = 24
    registry.meta["last_compliance_scan"] = "2020-01-01T00:00:00"
    assert js.compliance.due(saved, registry)
    # report-only mode leaves the configuration alone
    config2 = jc.load_config()
    config2.get_site("walled").enabled = True
    report = js.compliance.scan(config2, disable=False, save=False)
    assert report.non_compliant and not report.disabled and not report.config_saved


def test_compliance_scan_runs_daily_from_the_main_app_and_cli(config, transport, capsys):
    _sites(config)
    config.sites = [s for s in config.sites if s.id in ("ok-feed", "walled")]
    jc.save_config(config)
    transport({"/robots.txt": ROBOTS_OK, "good.example.com": "<rss></rss>",
               "wall.example.com": js.FetchError("HTTP 403 from wall.example.com", status=403, url="https://wall.example.com/jobs")})
    assert js.compliance.run_if_due(background=False)  # never scanned: due now
    assert not jc.load_config().get_site("walled").enabled
    assert not js.compliance.run_if_due(background=False)  # not due again today
    from jobsearch_sources.__main__ import main

    jc.load_config().get_site("walled")  # still disabled
    assert main(["compliance-scan"]) == 2
    out = capsys.readouterr().out
    assert "NON-COMPLIANT" in out and "ok-feed" in out and "HTTP 403" in out
    assert main(["compliance-scan", "--json", "--no-disable"]) == 2
    assert '"reason": "http"' in capsys.readouterr().out


# --- administrator switch for web-page based search -------------------------------------------------


def test_web_page_search_switch_requires_the_administrator_token(monkeypatch):
    config = jc.default_config()
    monkeypatch.delenv(jc.ENV_ADMIN_TOKEN, raising=False)
    assert jc.web_page_search_allowed(config)[0] and not jc.admin_configured()
    with pytest.raises(jc.AdminRequired):
        jc.set_web_page_search(config, False, "anything")  # no token configured at all
    monkeypatch.setenv(jc.ENV_ADMIN_TOKEN, "s3cret")
    assert jc.web_page_search_allowed(config)[0]  # default still on once a token exists
    with pytest.raises(jc.AdminRequired):
        jc.set_web_page_search(config, False, "wrong")
    jc.set_web_page_search(config, False, "s3cret")
    allowed, why = jc.web_page_search_allowed(config)
    assert not allowed and "switched off by the administrator" in why and config.search.web_page_search_signature
    jc.set_web_page_search(config, True, "s3cret")
    assert jc.web_page_search_allowed(config)[0] and jc.signature_valid(config) is True
    # tampering: flipping the JSON by hand without the token fails safe
    config.search.web_page_search = False
    config.search.web_page_search = True
    config.search.web_page_search_changed_at = "2030-01-01T00:00:00"
    allowed, why = jc.web_page_search_allowed(config)
    assert not allowed and "does not verify" in why
    jc.set_web_page_search(config, True, "s3cret")
    # the signed state survives a save/load round trip
    jc.save_config(config)
    assert jc.web_page_search_allowed(jc.load_config())[0]
    # without the token in this process a signed state is trusted but flagged as unverifiable
    monkeypatch.delenv(jc.ENV_ADMIN_TOKEN)
    allowed, why = jc.web_page_search_allowed(jc.load_config())
    assert allowed and "not verifiable" in why


def test_switched_off_web_page_search_skips_html_sites_everywhere(config, monkeypatch, transport):
    from jobsearch_sources import searchforms as sf

    monkeypatch.setenv(jc.ENV_ADMIN_TOKEN, "s3cret")
    jc.set_web_page_search(config, False, "s3cret")
    transport({"/robots.txt": ROBOTS_OK, "careers.example.com": PAGE, "remotive.com": {"jobs": []}})
    page = jc.SiteConfig(id="page", provider="html", name="Page", enabled=True, options={**jc.default_options("html"), "url": "https://careers.example.com/"})
    config.sites = [page, jc.SiteConfig(id="remotive", provider="remotive", name="Remotive", enabled=True)]
    report = js.run_search(config, keyword="x")
    outcomes = {o.site_id: o for o in report.outcomes}
    assert outcomes["page"].policy_off and "switched off by the administrator" in outcomes["page"].error and not outcomes["page"].denied
    assert not outcomes["remotive"].error  # API providers are unaffected
    form_site = jc.SiteConfig(id="yahoo", provider="html", name="Yahoo", options=sf.form_site_options(sf.get("yahoo-careers"), "https://www.yahooinc.com/careers/search.html", {}))
    test = sf.test_form(form_site, config, {"keyword": "x"})
    assert not test.ok and "switched off by the administrator" in test.error
    assert any("search.web_page_search" in str(i) and i.level == "warning" for i in jc.validate(config, registry=False))
    jc.set_web_page_search(config, True, "s3cret")
    assert not [i for i in jc.validate(config, registry=False) if "search.web_page_search" in str(i)]


def test_cli_web_search_switch(config, monkeypatch, capsys):
    from jobsearch_config.cli import main

    jc.save_config(config)
    monkeypatch.delenv(jc.ENV_ADMIN_TOKEN, raising=False)
    assert main(["web-search"]) == 0 and "ON" in capsys.readouterr().out
    assert main(["web-search", "off", "--admin-token", "x"]) == 3
    assert "Refused" in capsys.readouterr().out
    monkeypatch.setenv(jc.ENV_ADMIN_TOKEN, "s3cret")
    assert main(["web-search", "off", "--admin-token", "wrong"]) == 3
    assert main(["web-search", "off"]) == 0  # token from the environment
    assert not jc.web_page_search_allowed(jc.load_config())[0]
    assert main(["web-search"]) == 0 and "OFF" in capsys.readouterr().out.split("\n")[-3]
    assert main(["web-search", "on", "--admin-token", "s3cret"]) == 0
    assert jc.web_page_search_allowed(jc.load_config())[0]


def test_config_dashboard_admin_section_and_registry_override(config_path, tmp_path, monkeypatch, transport):
    AppTest = pytest.importorskip("streamlit.testing.v1").AppTest
    monkeypatch.setenv("JOB_SEARCH_DB", str(tmp_path / "t.db"))
    monkeypatch.setenv(jc.ENV_ADMIN_TOKEN, "s3cret")
    cfg = jc.default_config()
    cfg.sites.append(jc.SiteConfig(id="page", provider="html", name="Page", enabled=False, options={**jc.default_options("html"), "url": "https://careers.example.com/"}))
    jc.save_config(cfg)
    transport({"/robots.txt": ROBOTS_OK, "careers.example.com": PAGE})
    at = AppTest.from_file(str(ROOT / "config_dashboard.py"), default_timeout=60).run()
    assert not at.exception
    # wrong token: refused
    admin_inputs = [t for t in at.text_input if t.label == "Administrator token" and t.key != "reg-admin-token"]
    admin_inputs[0].set_value("wrong")
    [c for c in at.checkbox if c.label == "Allow web-page based search"][0].set_value(False)
    [b for b in at.button if b.label == "Apply as administrator"][0].click().run()
    assert any("token is wrong" in e.value for e in at.error)
    assert jc.web_page_search_allowed(jc.load_config())[0]
    # right token: switched off, signed
    admin_inputs = [t for t in at.text_input if t.label == "Administrator token" and t.key != "reg-admin-token"]
    admin_inputs[0].set_value("s3cret")
    [c for c in at.checkbox if c.label == "Allow web-page based search"][0].set_value(False)
    [b for b in at.button if b.label == "Apply as administrator"][0].click().run()
    assert not at.exception
    saved = jc.load_config()
    assert not saved.search.web_page_search and saved.search.web_page_search_signature and not jc.web_page_search_allowed(saved)[0]
    assert any("switched off by the administrator" in e.value for e in list(at.error) + list(at.success))
    # registry override: lifting a terms block needs the token
    host_box = [s for s in at.selectbox if s.label == "Host"][0]
    host_box.set_value("craigslist.org").run()
    at.text_input(key="reg-admin-token").set_value("nope")
    [b for b in at.button if b.label == "Lift the block"][0].click().run()
    assert any("token is wrong" in e.value for e in at.error) and not jc.load_registry().lookup("craigslist.org").active
    at.text_input(key="reg-admin-token").set_value("s3cret")
    [b for b in at.button if b.label == "Lift the block"][0].click().run()
    assert jc.load_registry().lookup("craigslist.org").active
    # compliance scan button
    [b for b in at.button if b.label == "Scan all sites now"][0].click().run()
    assert not at.exception
    assert js.compliance.last_scan()[0]


def test_registry_repairs_seed_rows_flipped_by_the_old_bug(tmp_path, monkeypatch):
    import json

    path = tmp_path / "damaged.json"
    registry = jc.load_registry()
    rows = [r.to_dict() for r in registry.list()]
    for row in rows:
        if row["host"] == "craigslist.org":  # what investigate used to write
            row.update({"active": True, "status": "empty", "source": "probe", "message": "Reachable.", "reason": ""})
        if row["host"] == "indeed.com":  # an administrator's decision is kept
            row.update({"active": True, "status": "ok", "source": "manual", "message": "lifted by admin", "reason": ""})
    path.write_text(json.dumps({"sites": rows}))
    repaired = jc.load_registry(path)
    craig = repaired.lookup("craigslist.org")
    assert not craig.active and craig.reason == "terms" and "terms prohibit robots" in craig.message
    assert repaired.lookup("indeed.com").active
    assert not jc.load_registry(path).repair_seeds()  # persisted
