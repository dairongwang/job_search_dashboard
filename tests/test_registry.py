"""Site registry: persistence, seeding, lookup, recording and enforcement."""

from __future__ import annotations

import json

import jobsearch_config as jc
import jobsearch_sources as js


def test_seeded_on_first_load_and_persisted(tmp_path, monkeypatch):
    path = tmp_path / "reg.json"
    monkeypatch.setenv(jc.ENV_REGISTRY_VAR, str(path))
    reg = jc.load_registry()
    assert path.exists()
    row = reg.lookup("https://www.indeed.com/jobs?q=x")
    assert row.host == "indeed.com" and row.status == "forbidden" and not row.active and row.source == "builtin"
    assert row.created_at and row.updated_at and row.checks == 0
    assert reg.lookup("https://uk.indeed.com/") is row  # sub-host matches the seed domain
    assert reg.lookup("https://remotive.com/") is None
    data = json.loads(path.read_text())
    assert {r["host"] for r in data["sites"]} >= {"indeed.com", "monster.com", "craigslist.org"}


def test_record_updates_fields_and_active_flag():
    reg = jc.load_registry()
    row = reg.record("https://jobs.example.com/list", "ok", "fine", source="probe")
    created = row.created_at
    assert row.active and row.checks == 1 and row.last_url == "https://jobs.example.com/list"
    row2 = reg.record("https://jobs.example.com/other", "forbidden", "HTTP 403", source="search", status_code=403)
    assert row2 is row and not row.active and row.checks == 2 and row.last_status_code == 403 and row.created_at == created
    assert row.updated_at >= created
    reg.record("https://jobs.example.com/", "error", "timeout")
    assert not row.active and row.status == "error"  # errors do not change the flag
    reg.record("https://jobs.example.com/", "empty", "nothing")
    assert row.active and row.status == "empty"
    again = jc.load_registry()
    assert again.lookup("jobs.example.com").checks == 4


def test_host_normalisation():
    assert jc.host_of("https://WWW.Example.com:443/path") == "example.com"
    assert jc.host_of("www.example.com") == "example.com"
    assert jc.host_of("") == ""


def test_manual_toggle_and_remove():
    reg = jc.load_registry()
    row = reg.set_active("indeed.com", True, "checked by hand")
    assert row.active and row.source == "manual" and row.status == "ok"
    assert jc.load_registry().lookup("indeed.com").active
    assert reg.remove("indeed.com") and jc.load_registry().lookup("indeed.com") is None
    assert not reg.remove("indeed.com")


def test_validation_blocks_enabled_sites_on_forbidden_hosts():
    cfg = jc.default_config()
    cfg.sites.append(jc.SiteConfig(id="indeed", provider="html", name="Indeed", enabled=True, options={"url": "https://www.indeed.com/jobs?q=x"}))
    issues = jc.validate(cfg)
    assert any(i.level == "error" and "indeed.com forbids automated access" in i.message for i in issues)
    cfg.get_site("indeed").enabled = False
    assert not any("forbids" in i.message for i in jc.validate(cfg))
    assert not any("forbids" in i.message for i in jc.validate(cfg, registry=False))


def test_probe_records_into_registry(transport):
    transport({
        "wall.example.com": js.FetchError("HTTP 403 from wall.example.com", status=403, url="https://wall.example.com/"),
        "feed.example.com": '<?xml version="1.0"?><rss><channel><item><title>x</title></item></channel></rss>',
    })
    assert js.probe("https://wall.example.com/jobs").registry_status == "forbidden"
    row = jc.load_registry().lookup("wall.example.com")
    assert row.status == "forbidden" and not row.active and row.last_status_code == 403 and row.source == "probe"
    assert js.probe("https://feed.example.com/jobs.rss").registry_status == "ok"
    assert jc.load_registry().lookup("feed.example.com").active


def test_classify_outcome():
    assert jc.classify_outcome("HTTP 403", True, False)[0] == "forbidden"
    assert jc.classify_outcome("boom", False, False)[0] == "error"
    assert jc.classify_outcome("", False, True)[0] == "empty"
    assert jc.classify_outcome("", False, False)[0] == "ok"
