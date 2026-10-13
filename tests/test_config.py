"""Schema, store, validation and CLI of the configuration library."""

from __future__ import annotations

import json

import pytest

import jobsearch_config as jc
from jobsearch_config.cli import main as cli


def test_defaults_are_valid():
    cfg = jc.default_config()
    assert jc.validate(cfg) == []
    assert {s.id for s in cfg.enabled_sites()} == {"remotive", "jobicy"}


def test_round_trip_preserves_everything():
    cfg = jc.default_config()
    cfg.preferences.titles = ["data analyst", "BI analyst"]
    cfg.preferences.salary = jc.SalaryRange(minimum=80000, maximum=120000, currency="usd", period="year", include_unlisted=False)
    cfg.get_site("remotive").options["category"] = "data"
    again = jc.loads(jc.dumps(cfg))
    assert again.to_dict() == cfg.to_dict()
    assert again.preferences.salary.currency == "USD"


def test_lists_are_cleaned_and_deduped():
    prefs = jc.JobPreferences(titles=" data analyst,  Data Analyst \n analyst ", skills=["SQL", "sql", ""], job_types=["permanent", "bogus"])
    assert prefs.titles == ["data analyst", "analyst"]
    assert prefs.skills == ["SQL"]
    assert prefs.job_types == ["permanent"]


def test_empty_vocab_lists_fall_back_to_all():
    prefs = jc.JobPreferences(job_types=[], workplaces=[], schedules=[])
    assert prefs.job_types == list(jc.JOB_TYPES)
    assert prefs.workplaces == list(jc.WORKPLACES)


def test_unknown_keys_are_ignored_and_missing_sections_defaulted():
    cfg = jc.AppConfig.from_dict({"version": 1, "sites": [{"id": "x", "provider": "remotive", "extra": 1}], "mystery": True})
    assert cfg.sites[0].provider == "remotive"
    assert cfg.preferences.job_types == list(jc.JOB_TYPES)
    assert cfg.search.timeout_seconds == 15


def test_store_creates_saves_and_backs_up(config_path):
    assert not config_path.exists()
    cfg = jc.load_config(create=True)
    assert config_path.exists()
    cfg.preferences.titles = ["qa engineer"]
    jc.save_config(cfg)
    assert config_path.with_suffix(".json.bak").exists()
    assert jc.load_config().preferences.titles == ["qa engineer"]
    assert jc.mtime() > 0


def test_store_rejects_non_object(config_path):
    config_path.write_text("[1, 2]")
    with pytest.raises(ValueError):
        jc.load_config()


def test_env_secret_resolution(monkeypatch):
    monkeypatch.setenv("MY_KEY", "s3cret")
    monkeypatch.delenv("MISSING", raising=False)
    assert jc.resolve_secret("${MY_KEY}") == "s3cret"
    assert jc.resolve_secret("Bearer ${MY_KEY}") == "Bearer s3cret"
    assert jc.resolve_secret("${MISSING}") == ""
    out = jc.resolve_options({"headers": {"Authorization": "${MY_KEY}"}, "pages": 2})
    assert out == {"headers": {"Authorization": "s3cret"}, "pages": 2}


def test_validation_catches_errors(monkeypatch):
    monkeypatch.delenv("ADZUNA_APP_ID", raising=False)
    cfg = jc.default_config()
    cfg.sites.append(jc.SiteConfig(id="Bad Id", provider="nope"))
    cfg.sites.append(jc.SiteConfig(id="remotive", provider="remotive"))  # duplicate
    cfg.get_site("adzuna").enabled = True
    cfg.get_site("adzuna").options["app_id"] = ""
    cfg.preferences.salary = jc.SalaryRange(minimum=200000, maximum=100000)
    cfg.preferences.min_skill_matches = 99
    messages = [str(i) for i in jc.validate(cfg)]
    assert any("Site id must be" in m for m in messages)
    assert any("Unknown provider" in m for m in messages)
    assert any("Duplicate site id" in m for m in messages)
    assert any("App ID' is required" in m for m in messages)
    assert any("greater than maximum" in m for m in messages)
    assert any("more skill matches" in m for m in messages)
    assert jc.has_errors(jc.validate(cfg))


def test_validation_warns_on_unset_env_reference(monkeypatch):
    monkeypatch.delenv("REED_API_KEY", raising=False)
    cfg = jc.default_config()
    cfg.get_site("reed").enabled = True
    issues = jc.validate(cfg)
    assert any(i.level == "warning" and "REED_API_KEY" in i.message for i in issues)
    assert not jc.has_errors(issues)


def test_custom_site_url_validation():
    cfg = jc.default_config()
    cfg.sites.append(jc.SiteConfig(id="feed", provider="rss", options={"url": "ftp://nope"}))
    assert any("http://" in str(i) for i in jc.validate(cfg))


def test_cli_flow(config_path, capsys):
    assert cli(["init"]) == 0
    assert cli(["init"]) == 1  # exists
    assert cli(["disable", "jobicy"]) == 0
    assert cli(["enable", "remoteok"]) == 0
    assert cli(["enable", "does-not-exist"]) == 1
    assert cli(["set-pref", "titles", "data analyst, BI analyst"]) == 0
    assert cli(["set-pref", "salary.minimum", "90000"]) == 0
    assert cli(["set-pref", "include_unknown_job_type", "false"]) == 0
    assert cli(["set-pref", "nope", "x"]) == 1
    assert cli(["validate"]) == 0
    cfg = jc.load_config()
    assert [s.id for s in cfg.enabled_sites()] == ["remotive", "remoteok"]
    assert cfg.preferences.titles == ["data analyst", "BI analyst"]
    assert cfg.preferences.salary.minimum == 90000
    assert cfg.preferences.include_unknown_job_type is False
    capsys.readouterr()
    cli(["export"])
    exported = json.loads(capsys.readouterr().out)
    assert exported["preferences"]["titles"] == ["data analyst", "BI analyst"]


def test_cli_import_refuses_errors(config_path, tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"sites": [{"id": "BAD", "provider": "remotive"}]}))
    assert cli(["import", str(bad)]) == 2
    assert cli(["import", str(bad), "--force"]) == 0
    assert cli(["validate"]) == 2
