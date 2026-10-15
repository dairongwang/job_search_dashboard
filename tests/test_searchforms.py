"""Search-form strategies: registry, versioning, Yahoo parsing, recipes, validation and service plumbing (offline)."""

from __future__ import annotations

from pathlib import Path

import pytest

import jobsearch_config as jc
import jobsearch_sources as js
from jobsearch_sources import robots
from jobsearch_sources import searchforms as sf
from jobsearch_sources.htmlpages import _soup
from jobsearch_sources.searchforms.yahoo import YAHOO_BRANDS, YAHOO_CATEGORIES, YAHOO_COUNTRIES, YAHOO_EXPERIENCE

FIX = Path(__file__).parent / "fixtures" / "yahoo"
LIVE = (FIX / "live_search_page.html").read_text(encoding="utf-8")  # the real yahooinc.com/careers/search.html capture
LANDING = (FIX / "landing.html").read_text(encoding="utf-8")
REDESIGN = (FIX / "redesign.html").read_text(encoding="utf-8")
YAHOO_URL = "https://www.yahooinc.com/careers/search.html"


@pytest.fixture(autouse=True)
def _fresh_robots():
    robots.clear_cache()
    yield
    robots.clear_cache()


def yahoo_site(url: str = YAHOO_URL, version: str = "2", **extra) -> jc.SiteConfig:
    options = sf.form_site_options(sf.get("yahoo-careers", version), url, {"categories": ["Engineering"], "countries": ["United States"]})
    options.update(extra)
    return jc.SiteConfig(id="yahoo", provider="html", name="Yahoo", enabled=False, options=options)


# --- registry & versioning ---------------------------------------------------------


def test_registry_knows_yahoo_with_two_versions_newest_first():
    versions = sf.versions_of("yahoo-careers")
    assert [v.version for v in versions] == ["2", "1"]
    assert sf.get("yahoo-careers").version == "2" and sf.get("yahoo-careers", "1").version == "1"
    assert sf.get("nope") is None and sf.get("yahoo-careers", "9") is None
    assert [s.key for s in sf.for_url("https://www.yahooinc.com/careers/")] == ["yahoo-careers@2", "yahoo-careers@1"]
    assert sf.for_url("https://careers.example.com/") == []
    assert "yahoo-careers" in sf.families()
    keys = [s.key for s in sf.all_strategies()]
    assert keys.index("yahoo-careers@2") < keys.index("yahoo-careers@1")


def test_candidates_prefer_the_configured_version_then_fall_back():
    ordered = sf.candidates({"search_form": {"strategy": "yahoo-careers", "version": "1"}}, YAHOO_URL)
    assert [s.key for s in ordered] == ["yahoo-careers@1", "yahoo-careers@2"]
    ordered = sf.candidates({"search_form": {"strategy": "yahoo-careers"}}, YAHOO_URL)
    assert [s.key for s in ordered] == ["yahoo-careers@2", "yahoo-careers@1"]
    assert sf.candidates({"search_form": {"strategy": "unknown-site"}}, YAHOO_URL) == []
    assert sf.candidates({}, YAHOO_URL) == []
    assert [s.key for s in sf.candidates({"search_form": {"strategy": "auto"}}, YAHOO_URL)] == ["yahoo-careers@2", "yahoo-careers@1"]


def test_legacy_actions_become_a_recipe_strategy():
    legacy = {"actions": [{"fill": {"placeholder": "Key words"}, "value": "{keyword}"}, {"check": {"label": "{brands}"}}, {"click": {"button": "Find jobs"}}],
              "form_values": {"brands": ["Yahoo", "AOL"]}}
    (strategy,) = sf.candidates(legacy, "https://x.example.com/jobs", "legacy-site")
    assert isinstance(strategy, sf.RecipeStrategy) and strategy.family == "recipe:legacy-site"
    assert [(f.key, f.kind, f.binds) for f in strategy.fields()] == [("keyword", "text", "keyword"), ("brands", "multiselect", "")]
    steps = strategy.steps({"keyword": "analyst", "brands": ["Yahoo", "AOL"]})
    assert steps[0]["value"] == "analyst" and [s["check"]["label"] for s in steps[1:3]] == ["Yahoo", "AOL"]
    assert strategy.fingerprint() == [] and strategy.parse_results(_soup("<html></html>"), "https://x") == []
    # a recipe without a fingerprint is assumed to apply (cannot be told apart)
    assert sf.resolve(_soup(REDESIGN), [strategy]).strategy is strategy


def test_recipe_spec_with_fields_fingerprint_and_result_selectors():
    spec = {
        "strategy": "recipe", "version": "3", "since": "2026-01", "label": "Acme search", "fingerprint": ["input[name=q]"],
        "fields": [{"key": "keyword", "label": "What", "kind": "text"}, {"key": "team", "label": "Team", "kind": "select", "options": ["Eng", "Ops"]}],
        "steps": [{"fill": "input[name=q]", "value": "{keyword}"}, {"select": "select[name=team]", "value": "{team}"}, {"click": {"button": "Go"}}],
        "results": {"item_selector": "ul.jobs li", "title_selector": "a", "link_selector": "a", "location_selector": ".loc"},
        "criteria": {"team": "Eng"},
    }
    (strategy,) = sf.candidates({"search_form": spec}, "https://acme.example.com/jobs", "acme")
    assert strategy.key == "recipe:acme@3" and strategy.label == "Acme search" and strategy.since == "2026-01"
    assert [f.key for f in strategy.fields()] == ["keyword", "team"] and strategy.field("team").options == ["Eng", "Ops"]
    assert strategy.matches(_soup('<form><input name="q"></form>')) and not strategy.matches(_soup(LANDING))
    assert strategy.steps({"keyword": "sql"})[1]["value"] == "Eng"  # spec criteria fill in what the user left blank
    rows = strategy.parse_results(_soup('<ul class="jobs"><li><a href="/j/1">Analyst</a><span class="loc">Remote</span></li></ul>'), "https://acme.example.com/jobs")
    assert rows == [{"title": "Analyst", "company": "", "location": "Remote", "salary": "", "date": "", "description": "", "job_type": "", "link": "https://acme.example.com/j/1"}]
    with pytest.raises(ValueError):
        sf.FormField("x", "X", "wheel")


# --- Yahoo strategy on the real page capture -----------------------------------------


def test_yahoo_v2_recognises_the_live_page_and_reads_its_dropdowns():
    v2, v1 = sf.get("yahoo-careers", "2"), sf.get("yahoo-careers", "1")
    soup = _soup(LIVE)
    assert v2.matches(soup) and not v1.matches(soup)
    options = v2.live_options(soup)
    assert options["categories"] == YAHOO_CATEGORIES and options["countries"] == YAHOO_COUNTRIES
    assert options["brands"] == YAHOO_BRANDS and options["experience"] == YAHOO_EXPERIENCE
    assert [f.key for f in v2.fields()] == ["keyword", "categories", "countries", "brands", "experience"]
    assert v2.field("keyword").binds == "keyword" and v2.field("countries").kind == "multiselect"
    assert v2.applies_to("https://www.yahooinc.com/careers/") and not v2.applies_to("https://yahoo.example.com/")


def test_yahoo_v2_parses_the_result_table():
    v2 = sf.get("yahoo-careers", "2")
    soup = _soup(LIVE)
    rows = v2.parse_results(soup, YAHOO_URL)
    assert len(rows) == 20
    assert rows[0]["title"] == "Senior Campaign Operations Analyst" and rows[0]["company"] == "Yahoo" and rows[0]["location"] == "India"
    assert rows[0]["link"].startswith("https://ouryahoo.wd5.myworkdayjobs.com/careers/job/India/")
    assert {r["company"] for r in rows} >= {"Yahoo", "Yahoo Search", "Yahoo Mail", "Boundless"}
    assert v2.results_total(soup) == (20, 103)


def test_yahoo_v2_steps_fill_tick_submit_and_load_more():
    v2 = sf.get("yahoo-careers", "2")
    steps = v2.steps({"keyword": "data analyst", "categories": ["Engineering"], "countries": ["United States"], "brands": ["Yahoo", "Yahoo Finance"], "experience": []}, pages=3)
    kinds = [next(k for k in ("fill", "click", "check", "wait", "wait_change", "remember") if k in s) for s in steps]
    assert kinds.count("check") == 4 and kinds.count("fill") == 1 and "wait_change" in kinds and "remember" in kinds
    fill = next(s for s in steps if "fill" in s)
    assert fill["fill"]["css"] == "form#collapseFilterJobs input[name=keyword]" and fill["value"] == "data analyst" and fill["force"]
    checks = [s["check"]["css"] for s in steps if "check" in s]
    assert checks[0] == '#JCDropdown input[type=checkbox][value="Engineering"]'
    assert '#JBDropdown input[type=checkbox][value="Yahoo Finance"]' in checks
    submit = next(s for s in steps if "click" in s and "search-page-find-jobs-mobile" in s["click"]["css"])
    assert submit["force"] is True
    load_more = steps[-1]
    assert load_more["click"]["css"] == "button.loadMore" and load_more["repeat"] == 2 and load_more["snapshot"] and load_more["optional"]
    assert not any("JEDropdown" in s.get("check", {}).get("css", "") for s in steps)  # nothing chosen -> nothing ticked
    assert sf.css_string('O"Brien') == '"O\\"Brien"'
    # a value with a quote still yields a valid selector
    assert _soup('<input value=\'O"Brien\'>').select_one(f"input[value={sf.css_string('O' + chr(34) + 'Brien')}]") is not None


LIVE_LANDING = (FIX / "live_landing_page.html").read_text(encoding="utf-8")  # real capture of https://www.yahooinc.com/careers/


def test_yahoo_v1_is_the_landing_page_form_and_plan_carries_both():
    v1, v2 = sf.get("yahoo-careers", "1"), sf.get("yahoo-careers", "2")
    for page in (LIVE_LANDING, LANDING):
        soup = _soup(page)
        assert v1.matches(soup) and not v2.matches(soup)
    assert not v1.matches(_soup(LIVE)) and not v1.matches(_soup(REDESIGN))
    options = v1.live_options(_soup(LIVE_LANDING))
    assert options["categories"] == YAHOO_CATEGORIES and options["countries"] == YAHOO_COUNTRIES and options["brands"] == YAHOO_BRANDS
    assert [f.key for f in v1.fields()] == ["keyword", "categories", "countries", "brands"] and v1.owns_results
    steps = v1.steps({"keyword": "analyst", "categories": ["Engineering"], "countries": [], "brands": ["Yahoo"]})
    assert steps[0] == {"fill": {"css": 'form[action$="search.html"] input[name=keyword]'}, "value": "analyst", "force": True}
    assert {"check": {"css": '#JCDropdown input[type=checkbox][value="Engineering"]'}, "force": True} in steps
    assert any("index-page-find-jobs" in s.get("click", {}).get("css", "") for s in steps)
    assert not any("JLDropdown" in s.get("check", {}).get("css", "") for s in steps)
    plan = sf.browser_plan(sf.versions_of("yahoo-careers"), {"keyword": "x"}, pages=1)
    assert [c["key"] for c in plan["candidates"]] == ["yahoo-careers@2", "yahoo-careers@1"]
    assert plan["candidates"][0]["require"][0] == "form#collapseFilterJobs" and plan["viewport"] == {"width": 820, "height": 1180}
    assert plan["candidates"][1]["absent"] == ["form#collapseFilterJobs"]
    assert v1.parse_results(_soup(LIVE), YAHOO_URL)[0]["title"] == "Senior Campaign Operations Analyst"  # same result table as v2


def test_resolution_detects_version_change_and_redesign():
    both = sf.versions_of("yahoo-careers")
    live = sf.resolve(_soup(LIVE), both)
    assert live.matched and live.strategy.key == "yahoo-careers@2" and not live.changed
    older = sf.resolve(_soup(LANDING), both)
    assert older.strategy.key == "yahoo-careers@1" and older.changed and "changed" in older.message() and "version 1" in older.message()
    gone = sf.resolve(_soup(REDESIGN), both)
    assert not gone.matched and gone.tried == ("yahoo-careers@2", "yahoo-careers@1")
    assert "no longer matches any known version" in gone.message() and "yahoo-careers@2 (2026-02), yahoo-careers@1 (2026-02)" in gone.message()
    assert sf.resolve_key("yahoo-careers@1", both).changed and sf.resolve_key("", both).strategy is None


def test_criteria_normalisation_and_unknown_choices():
    v2 = sf.get("yahoo-careers", "2")
    crit = v2.normalise_criteria({"keyword": " sql ", "categories": "Engineering, Finance", "countries": None, "brands": ["Yahoo"], "bogus": 1})
    assert crit == {"keyword": "sql", "categories": ["Engineering", "Finance"], "countries": [], "brands": ["Yahoo"], "experience": []}
    assert v2.describe_criteria(crit) == "Search by keywords: sql; Select job categories: Engineering, Finance; Select brands: Yahoo"
    assert v2.describe_criteria({}) == "no criteria (all jobs)"
    problems = v2.unknown_choices({"categories": ["Engineering", "Astronomy"], "brands": ["yahoo"]}, {"brands": ["Yahoo", "AOL"]})
    assert len(problems) == 1 and problems[0].startswith("Select job categories: Astronomy not offered")
    assert v2.to_dict()["fields"][1]["options"] == YAHOO_CATEGORIES and v2.to_dict()["key"] == "yahoo-careers@2"


# --- configuration: options, validation, status ----------------------------------------


def test_form_site_options_and_validation_rules(config):
    site = yahoo_site()
    block = site.options["search_form"]
    assert block["strategy"] == "yahoo-careers" and block["version"] == "2" and site.options["render"] == "always"
    assert block["criteria"] == {"keyword": "", "categories": ["Engineering"], "countries": ["United States"], "brands": [], "experience": []}
    assert jc.search_form_status(site) == (False, "the search form has not passed a Find jobs test yet")
    config.sites = [site]
    assert [i for i in jc.validate(config, registry=False) if "sites.yahoo" in str(i)] == []  # disabled: fine
    site.enabled = True
    issues = [str(i) for i in jc.validate(config, registry=False) if "sites.yahoo" in str(i)]
    assert len(issues) == 1 and "[error]" in issues[0] and "only added to the job search when a test has returned jobs" in issues[0]
    block["validated"] = {"at": "2026-03-01T09:00:00", "jobs": 0, "strategy": "yahoo-careers@2"}
    assert "returned no jobs" in [str(i) for i in jc.validate(config, registry=False) if "sites.yahoo" in str(i)][0]
    block["validated"]["jobs"] = 7
    assert [i for i in jc.validate(config, registry=False) if "sites.yahoo" in str(i)] == []
    assert jc.search_form_status(site)[0] is True and "7 job(s)" in jc.search_form_status(site)[1]
    # malformed blocks
    site.options["search_form"] = {"criteria": {}}
    assert any("'strategy' is required" in str(i) for i in jc.validate(config, registry=False))
    site.options["search_form"] = {"strategy": "recipe"}
    assert any("needs 'steps'" in str(i) for i in jc.validate(config, registry=False))
    site.options["search_form"] = "nope"
    assert any("must be a JSON object" in str(i) for i in jc.validate(config, registry=False))
    # legacy steps without a test: cannot be enabled either; plain pages are unaffected
    site.options["search_form"] = {}
    site.options["actions"] = [{"click": {"button": "Find jobs"}}]
    assert any("legacy search-form steps" in str(i) for i in jc.validate(config, registry=False))
    site.options["actions"] = []
    assert jc.search_form_status(site) == (None, "") and not [i for i in jc.validate(config, registry=False) if "sites.yahoo" in str(i)]


def test_validation_status_helper_and_site_with_criteria():
    site = yahoo_site()
    assert sf.validation_status(site)[0] is False
    trial = sf.site_with_criteria(site, {"keyword": "sql", "brands": ["Yahoo"]})
    assert trial is not site and trial.options["search_form"]["criteria"]["brands"] == ["Yahoo"] and trial.options["search_form"]["criteria"]["categories"] == []
    assert site.options["search_form"]["criteria"]["categories"] == ["Engineering"]  # original untouched
    legacy = jc.SiteConfig(id="old", provider="html", name="Old", options={**jc.default_options("html"), "url": "https://x.example.com/", "render": "never",
                                                                            "actions": [{"fill": {"placeholder": "Key words"}, "value": "{keyword}"}], "form_values": {}})
    trial = sf.site_with_criteria(legacy, {"keyword": "bi"})
    assert trial.options["form_values"] == {"keyword": "bi"} and trial.options["render"] == "auto"
    with pytest.raises(ValueError):
        sf.site_with_criteria(jc.SiteConfig(id="p", provider="html", name="P", options={"url": "https://x.example.com/"}), {})


class _FakeJob:
    pass


def _fake_html_adapter(jobs, info=None, error=None):
    def adapter(ctx):
        ctx.extra["search_form"] = info or {"configured": "yahoo-careers@2", "matched": "yahoo-careers@2", "changed": False, "live_options": {"brands": ["Yahoo"]}, "runs": [{"total": 9, "unknown_choices": []}]}
        if error is not None:
            raise error
        return [js.Job(title=t, organization="Yahoo", url=f"https://w/{i}", source=ctx.site.name, site_id=ctx.site.id) for i, t in enumerate(jobs)]

    return adapter


def test_test_form_and_mark_validated_record_the_passing_test(config, monkeypatch):
    from jobsearch_sources import search as search_mod

    site = yahoo_site()
    monkeypatch.setitem(search_mod.ADAPTERS, "html", _fake_html_adapter(["Data Analyst", "BI Analyst"]))
    test = sf.test_form(site, config, {"keyword": "analyst", "categories": ["Engineering"]})
    assert test.ok and [j.title for j in test.jobs] == ["Data Analyst", "BI Analyst"] and test.matched == "yahoo-careers@2" and test.total == 9
    assert test.live_options == {"brands": ["Yahoo"]} and test.criteria["keyword"] == "analyst"
    assert "2 job(s) of 9" in test.summary()
    sf.mark_validated(site, test)
    block = site.options["search_form"]
    assert block["validated"]["jobs"] == 2 and block["validated"]["strategy"] == "yahoo-careers@2" and block["criteria"]["keyword"] == "analyst"
    assert block["live_options"] == {"brands": ["Yahoo"]} and block["version"] == "2"
    assert jc.search_form_status(site)[0] is True
    # the registry saw the run
    row = jc.load_registry().lookup(YAHOO_URL)
    assert row is not None and row.status == "ok"


def test_test_form_fails_without_jobs_or_when_the_form_changed(config, monkeypatch):
    from jobsearch_sources import search as search_mod

    site = yahoo_site()
    monkeypatch.setitem(search_mod.ADAPTERS, "html", _fake_html_adapter([], error=js.NoListings("the search form was submitted but no job listings came back.")))
    test = sf.test_form(site, config, {"keyword": "astronaut"})
    assert not test.ok and test.jobs == [] and "no job listings came back" in test.error and test.validated_record()["jobs"] == 0
    changed = sf.FormChanged("the site's search form no longer matches any known version", family="yahoo-careers", tried=("yahoo-careers@2", "yahoo-careers@1"))
    monkeypatch.setitem(search_mod.ADAPTERS, "html", _fake_html_adapter([], error=changed))
    test = sf.test_form(site, config, {})
    assert not test.ok and test.form_changed and "no longer matches" in test.error
    # the same flag reaches a normal search outcome
    config.sites = [site]
    site.enabled = True
    report = js.run_search(config, keyword="x")
    assert report.outcomes[0].form_changed and "no longer matches" in report.errors[0]
    # mark_validated with a different matched version re-points the configuration at it
    site.options["search_form"]["version"] = "1"
    ok = sf.test_form(site, config, {})  # still the FormChanged adapter -> not ok, but exercise the switch
    ok.matched, ok.error, ok.form_changed = "yahoo-careers@2", "", False
    sf.mark_validated(site, ok)
    assert site.options["search_form"]["version"] == "2"


def test_mark_validated_upgrades_legacy_actions_to_a_recipe(config):
    legacy = jc.SiteConfig(id="old", provider="html", name="Old", options={**jc.default_options("html"), "url": "https://x.example.com/",
                                                                            "actions": [{"fill": {"placeholder": "Key words"}, "value": "{keyword}"}], "form_values": {"keyword": "a"}})
    test = sf.FormTest(site=legacy, criteria={"keyword": "bi"}, jobs=[js.Job(title="BI")], matched="recipe:old@1", configured="recipe:old@1")
    sf.mark_validated(legacy, test)
    assert legacy.options["actions"] == [] and legacy.options["search_form"]["strategy"] == "recipe"
    assert legacy.options["search_form"]["steps"][0]["fill"] == {"placeholder": "Key words"} and legacy.options["search_form"]["criteria"] == {"keyword": "bi"}
    assert legacy.options["search_form"]["validated"]["jobs"] == 1
    (strategy,) = sf.candidates(legacy.options, "https://x.example.com/", "old")
    assert strategy.steps({"keyword": "sql"})[0]["value"] == "sql"


# --- detection (plain fetch) ----------------------------------------------------------


def test_detect_reads_the_live_page_statically(transport):
    transport({"/robots.txt": "User-agent: *\nAllow: /\n", "yahooinc.com/careers/search.html": LIVE})
    report = sf.detect(YAHOO_URL, render=False)
    assert report.known and [c["key"] for c in report.candidates] == ["yahoo-careers@2", "yahoo-careers@1"]
    assert report.ok and report.matched == "yahoo-careers@2" and not report.changed and not report.rendered
    assert report.live_options["brands"] == YAHOO_BRANDS and "matched yahoo-careers@2" in report.message
    assert report.to_dict()["host"] == "www.yahooinc.com"
    # a strategy chosen explicitly for another host (a mirror) is honoured
    transport({"/robots.txt": "User-agent: *\nAllow: /\n", "mirror.example.com": LANDING})
    report = sf.detect("https://mirror.example.com/careers/", options={"search_form": {"strategy": "yahoo-careers", "version": "2"}}, render=False)
    assert report.matched == "yahoo-careers@1" and report.changed and "changed" in report.message
    transport({"/robots.txt": "User-agent: *\nAllow: /\n", "mirror.example.com": REDESIGN})
    report = sf.detect("https://mirror.example.com/careers/", options={"search_form": {"strategy": "yahoo-careers"}}, render=False, learn=False)
    assert report.known and not report.ok and "no longer matches any known version" in report.message
    assert not sf.detect("https://nobody.example.com/jobs", render=False).known


def test_detect_respects_robots_and_refusals(transport):
    transport({"/robots.txt": "User-agent: *\nDisallow: /careers\n", "yahooinc.com": LIVE})
    report = sf.detect(YAHOO_URL, render=False)
    assert report.robots_allowed is False and "robots.txt disallows" in report.error and not report.ok
    robots.clear_cache()
    transport({"/robots.txt": "User-agent: *\nAllow: /\n", "yahooinc.com": js.FetchError("HTTP 403 from www.yahooinc.com", status=403, url=YAHOO_URL)})
    report = sf.detect(YAHOO_URL, render=False)
    assert report.denied and report.http_status == 403 and not report.ok
    row = jc.load_registry().lookup(YAHOO_URL)
    assert row is not None and not row.active and row.status == "forbidden"


# --- provider wiring --------------------------------------------------------------------


def test_form_sites_need_a_browser_and_explain_otherwise(config, transport, monkeypatch):
    from jobsearch_sources import browser

    transport({"/robots.txt": "User-agent: *\nAllow: /\n", "yahooinc.com": LIVE})
    site = yahoo_site(render="never")
    site.options["search_form"]["validated"] = {"at": "x", "jobs": 3, "strategy": "yahoo-careers@2"}
    site.enabled = True
    config.sites = [site]
    report = js.run_search(config, keyword="analyst")
    assert "driven in a browser" in report.errors[0]
    site.options["render"] = "auto"
    monkeypatch.setattr(browser, "available", lambda: (False, "Playwright is not installed."))
    report = js.run_search(config, keyword="analyst")
    assert "needs a browser: Playwright is not installed" in report.errors[0]


def test_cli_lists_strategies_and_reports_status(config, capsys):
    from jobsearch_sources.__main__ import main

    assert main(["forms"]) == 0
    out = capsys.readouterr().out
    assert "yahoo-careers@2" in out and "yahoo-careers@1" in out and "#collapseFilterJobs" in out
    assert main(["forms", "--json"]) == 0
    assert '"family": "yahoo-careers"' in capsys.readouterr().out
    site = yahoo_site()
    config.sites = [site]
    jc.save_config(config)
    assert main(["forms", "--site", "yahoo"]) == 0
    out = capsys.readouterr().out
    assert "Yahoo careers" in out and "Select job categories" in out and "not passed" in out


# --- investigate integration --------------------------------------------------------------


def test_investigate_reports_the_matching_strategy_and_suggests_a_form_site(transport):
    transport({"/robots.txt": "User-agent: *\nAllow: /\n", "yahooinc.com": LIVE})
    report = js.investigate(YAHOO_URL, render=False)
    assert report.form_strategies == ["yahoo-careers@2", "yahoo-careers@1"] and report.form_strategy_matched == "yahoo-careers@2"
    assert report.suggested_site["provider"] == "workday"  # the platform API stays the primary suggestion
    form = report.suggested_form_site
    assert form["id"] == "yahooinc-com-form" and form["enabled"] is False and form["options"]["search_form"]["strategy"] == "yahoo-careers"
    assert form["options"]["url"] == YAHOO_URL and form["options"]["render"] == "always"
    assert "matches this page" in report.summary and "Suggested search-form site config" in js.format_report(report)
    # a page of the same host where no version matches says so
    transport({"/robots.txt": "User-agent: *\nAllow: /\n", "yahooinc.com": "<html><body><p>Nothing here</p></body></html>"})
    report = js.investigate("https://www.yahooinc.com/careers/new/", render=False)
    assert report.form_strategy_matched == "" and report.suggested_form_site is None and "none matches this page" in report.summary


# --- empty search results must stay empty (regression: navigation links were turned into fake jobs) ---------

NO_RESULTS = (FIX / "live_no_results_page.html").read_text(encoding="utf-8")  # real capture of an empty Yahoo search


def test_yahoo_v2_recognises_an_empty_result_page():
    v2 = sf.get("yahoo-careers", "2")
    soup = _soup(NO_RESULTS)
    assert v2.matches(soup) and v2.owns_results
    assert v2.parse_results(soup, YAHOO_URL) == []
    assert v2.results_total(soup) == (0, 0)
    assert v2.no_results_message(soup) == "We currently do not have any jobs matching your criteria. Please modify the search and try again."
    assert v2.no_results_message(_soup(LIVE)) == "" and v2.results_total(_soup(LIVE)) == (20, 103)
    assert sf.get("yahoo-careers", "1").owns_results  # same result table on the landing page's results
    assert not sf.RecipeStrategy({"steps": [{"click": "b"}]}).owns_results
    assert sf.RecipeStrategy({"steps": [{"click": "b"}], "results": {"item_selector": "li", "empty_selector": ".empty"}}).owns_results
    recipe = sf.RecipeStrategy({"steps": [{"click": "b"}], "results": {"item_selector": "li", "empty_selector": ".empty"}})
    assert recipe.no_results_message(_soup('<p class="empty">Nothing found</p>')) == "Nothing found"


def test_page_navigation_links_are_not_job_links():
    from jobsearch_sources.htmlpages import candidate_links

    links = candidate_links(_soup(NO_RESULTS), YAHOO_URL)
    assert not any(link.rstrip("/").endswith("/careers") for link in links), links
    # a sibling or child job page still counts
    soup = _soup('<a href="/careers">Careers</a><a href="/careers/">Search</a><a href="/careers/jobs/123">Analyst</a><a href="/careers/view?job=9">X</a>')
    assert candidate_links(soup, YAHOO_URL) == ["https://www.yahooinc.com/careers/jobs/123", "https://www.yahooinc.com/careers/view?job=9"]


def test_empty_form_result_yields_no_jobs_even_with_generic_links(config, monkeypatch):
    """With the strategy owning the result list, an empty table means zero jobs — no fallback to page links."""
    from jobsearch_sources import browser, htmlpages

    class Page:
        status, html, error, final_url = 200, NO_RESULTS, "", YAHOO_URL
        initial_html, matched, steps_done, step_error = NO_RESULTS, "yahoo-careers@2", 9, ""
        snapshots = [NO_RESULTS]
        pages = [NO_RESULTS]
        denied = False

    rendered_urls: list[str] = []
    monkeypatch.setattr(browser, "available", lambda: (True, ""))
    monkeypatch.setattr(htmlpages._Fetcher, "rendered_with_plan", lambda self, url, plan: Page())
    monkeypatch.setattr(htmlpages._Fetcher, "rendered", lambda self, urls: rendered_urls.extend(urls) or {})
    monkeypatch.setattr(htmlpages.robots, "check", lambda url, settings=None: htmlpages.robots.Verdict(True, "", None))
    site = yahoo_site(follow_links="always")
    site.options["search_form"]["validated"] = {"at": "x", "jobs": 2, "strategy": "yahoo-careers@2"}
    site.enabled = True
    config.sites = [site]
    report = js.run_search(config, keyword="data analyst")
    assert report.results == [] and report.fetched == 0
    outcome = report.outcomes[0]
    assert outcome.empty and outcome.fetched == 0 and rendered_urls == []  # no page links were followed
    assert "no job listings came back" in outcome.error and "We currently do not have any jobs matching your criteria" in outcome.error
    assert "the site answered:" in outcome.note
    test = sf.test_form(site, config, {"keyword": "data analyst", "brands": ["Boundless"]})
    assert not test.ok and test.jobs == [] and "We currently do not have any jobs" in test.error


# --- learning a new version from the live page ------------------------------------------------


def test_learner_derives_a_version_from_the_real_landing_page():
    learned = sf.learn_form(_soup(LIVE_LANDING), "https://www.yahooinc.com/careers/", family="yahoo-careers", version="auto-1")
    assert learned is not None and learned.score >= 8
    spec = learned.spec
    assert spec["strategy"] == "recipe" and spec["family"] == "yahoo-careers" and spec["version"] == "auto-1" and spec["learned"]
    assert spec["fingerprint"] == ['form[action="/careers/search.html"]', "#search-keyword", "#JCDropdown", "#JLDropdown", "#JBDropdown", "#index-page-find-jobs"]
    strategy = sf.RecipeStrategy(spec, "yahoo")
    assert strategy.key == "yahoo-careers@auto-1" and strategy.learned and strategy.owns_results
    assert [(f.key, f.label, f.kind, len(f.options)) for f in strategy.fields()] == [
        ("keyword", "Key words", "text", 0), ("categories", "Select job categories", "multiselect", 18),
        ("locations", "Select countries", "multiselect", 20), ("brands", "Select brands", "multiselect", 8),
    ]
    assert strategy.matches(_soup(LIVE_LANDING)) and not strategy.matches(_soup(LIVE))
    steps = strategy.steps({"keyword": "analyst", "categories": ["Engineering"], "locations": ["United States"], "brands": []}, pages=1)
    assert steps[0] == {"fill": {"css": "#search-keyword"}, "value": "analyst", "force": True}
    checks = [x["check"]["css"] for x in steps if "check" in x]
    assert checks == ['input[type=checkbox][name="categories[]"][value="Engineering"]', 'input[type=checkbox][name="locations[]"][value="United States"]']
    assert {"click": {"css": "#index-page-find-jobs"}, "force": True} in steps
    assert not any("Load more" in json_dumps(x) for x in steps)  # pages=1 -> no load-more step
    # criteria entered for version 2's fields carry over to the learned fields (countries -> locations by label/options)
    mapped = sf.map_criteria({"keyword": "sql", "categories": ["Finance"], "countries": ["Japan"], "brands": ["Yahoo"], "experience": ["Management"]}, sf.get("yahoo-careers").fields(), strategy.fields())
    assert mapped == {"keyword": "sql", "categories": ["Finance"], "locations": ["Japan"], "brands": ["Yahoo"]}


def json_dumps(value):
    import json

    return json.dumps(value)


def test_learner_handles_unknown_layouts_and_gives_up_on_plain_pages():
    learned = sf.learn_form(_soup(REDESIGN), "https://x.example.com/jobs", family="acme", version="auto-3")
    assert learned is not None
    strategy = sf.RecipeStrategy(learned.spec, "acme")
    assert [(f.key, f.kind) for f in strategy.fields()] == [("keyword", "text"), ("loc", "multiselect"), ("team", "select")]
    assert strategy.field("team").options == ["Engineering", "Marketing", "Finance"] and strategy.field("loc").label == "Where"
    steps = strategy.steps({"keyword": "analyst", "team": "", "loc": []}, pages=3)
    assert [k for x in steps for k in ("fill", "check", "select", "click") if k in x] == ["fill", "click", "click"]  # blank select/checkboxes skipped
    assert steps[-1]["repeat"] == "2"
    assert sf.learn_form(_soup("<html><body><p>Nothing to search here</p><a href='/x'>x</a></body></html>"), "https://x.example.com/") is None
    assert sf.learn_form(_soup("<html><body><form><input type='email' name='e'><button type='submit'>Subscribe</button></form></body></html>"), "https://x.example.com/") is None


def test_learned_results_read_job_lists_but_never_menus():
    rows = sf.learned_results(_soup(LIVE), YAHOO_URL)
    assert len(rows) == 20 and rows[0]["title"] == "Senior Campaign Operations Analyst" and rows[0]["location"] == "India"
    assert rows[0]["link"].startswith("https://ouryahoo.wd5.myworkdayjobs.com/careers/job/")
    assert sf.learned_results(_soup(NO_RESULTS), YAHOO_URL) == []  # footer / header links are not jobs
    assert sf.learned_results(_soup(LIVE_LANDING), "https://www.yahooinc.com/careers/") == []
    page = '<nav><a href="/a">Alpha jobs</a><a href="/b">Beta jobs</a><a href="/c">Gamma jobs</a></nav><ul class="roleResults"><li><a href="/job/1">Analyst</a> <span>Remote</span></li><li><a href="/job/2">Engineer</a> <span>Dublin, Ireland</span></li></ul>'
    rows = sf.learned_results(_soup(page), "https://x.example.com/search")
    assert [(r["title"], r["location"]) for r in rows] == [("Analyst", "Remote"), ("Engineer", "Dublin, Ireland")]


def test_learned_versions_are_candidates_and_persist(config, monkeypatch):
    site = yahoo_site()
    spec = sf.learn_form(_soup(REDESIGN), YAHOO_URL, family="yahoo-careers", version=sf.next_learned_version(sf.versions_of("yahoo-careers"))).spec
    assert spec["version"] == "auto-1"
    # a test run that learned a version: saving keeps it and selects it
    test = sf.FormTest(site=site, criteria={"keyword": "analyst", "team": "Engineering", "loc": ["United States"]}, jobs=[js.Job(title="Analyst")],
                       configured="yahoo-careers@2", matched="yahoo-careers@auto-1", changed=True, learned=spec)
    sf.mark_validated(site, test)
    block = site.options["search_form"]
    assert block["strategy"] == "yahoo-careers" and block["version"] == "auto-1" and [l["version"] for l in block["learned"]] == ["auto-1"]
    assert block["criteria"] == {"keyword": "analyst", "loc": ["United States"], "team": "Engineering"} and block["validated"]["strategy"] == "yahoo-careers@auto-1"
    ordered = sf.candidates(site.options, YAHOO_URL, site.id)
    assert [c.key for c in ordered] == ["yahoo-careers@auto-1", "yahoo-careers@2", "yahoo-careers@1"]
    assert ordered[0].learned and ordered[0].matches(_soup(REDESIGN))
    assert sf.configured_strategy(site.options, site.id).key == "yahoo-careers@auto-1"
    assert sf.next_learned_version(ordered) == "auto-2"
    assert jc.search_form_status(site)[0] is True
    # the dashboard can run a test with a not-yet-saved learned version
    trial = sf.site_with_criteria(yahoo_site(), {"keyword": "x", "loc": ["Ireland"]}, learned=spec)
    assert trial.options["search_form"]["version"] == "auto-1" and trial.options["search_form"]["criteria"]["loc"] == ["Ireland"]
    assert sf.with_learned({"strategy": "yahoo-careers", "learned": [spec]}, {**spec, "label": "again"})["learned"][0]["label"] == "again"


def test_detect_learns_when_nothing_matches(transport):
    transport({"/robots.txt": "User-agent: *\nAllow: /\n", "mirror.example.com": REDESIGN})
    report = sf.detect("https://mirror.example.com/careers/", options={"search_form": {"strategy": "yahoo-careers"}}, render=False)
    assert report.ok and report.changed and report.matched == "yahoo-careers@auto-1" and report.learned["fingerprint"][0] == "form#jobSearchV3"
    assert "a new version (auto-1) was derived from it" in report.message and report.live_options["team"] == ["Engineering", "Marketing", "Finance"]


def test_form_changed_is_still_reported_when_learning_is_off_or_impossible(config, monkeypatch):
    from jobsearch_sources import browser, htmlpages

    class Page:
        status, html, error, final_url = 200, "<html><body><p>Nothing here</p></body></html>", "", YAHOO_URL
        initial_html, matched, steps_done, step_error = html, "", 0, ""
        snapshots, pages, denied = [html], [html], False

    monkeypatch.setattr(browser, "available", lambda install=None: (True, ""))
    monkeypatch.setattr(htmlpages._Fetcher, "rendered_with_plan", lambda self, url, plan: Page())
    monkeypatch.setattr(htmlpages.robots, "check", lambda url, settings=None: htmlpages.robots.Verdict(True, "", None))
    site = yahoo_site()
    site.options["search_form"]["validated"] = {"at": "x", "jobs": 2, "strategy": "yahoo-careers@2"}
    site.enabled = True
    config.sites = [site]
    report = js.run_search(config, keyword="analyst")
    assert report.outcomes[0].form_changed and "no longer matches any known version" in report.errors[0]


def test_browser_auto_install_runs_pip_and_playwright(monkeypatch):
    from jobsearch_sources import browser

    calls: list[list[str]] = []
    state = {"probe": [(False, "the 'playwright' package is not installed"), (False, "Chromium is not installed"), (True, "")]}

    def fake_probe():
        return state["probe"].pop(0) if len(state["probe"]) > 1 else state["probe"][0]

    monkeypatch.setattr(browser, "_probe", fake_probe)
    monkeypatch.setattr(browser, "_run", lambda cmd, timeout: calls.append(cmd) or (True, ""))
    monkeypatch.setattr(browser.importlib.util, "find_spec", lambda name: None)
    monkeypatch.setattr(browser, "_install_attempted", False)
    ok, reason = browser.ensure_installed(force=True)
    assert ok and reason == ""
    assert [c[-3:] for c in calls] == [["--disable-pip-version-check", "playwright>=1.45"][-3:] if False else c[-3:] for c in calls]
    assert any("pip" in c and "playwright>=1.45" in c for c in calls) and any("playwright" in c and "install" in c and "chromium" in c for c in calls)
    # disabled by environment: nothing is installed, the reason is reported
    monkeypatch.setenv(browser.AUTO_INSTALL_ENV, "0")
    monkeypatch.setattr(browser, "_probe", lambda: (False, "missing"))
    assert browser.available() == (False, "missing")
    calls.clear()
    monkeypatch.setattr(browser, "_run", lambda cmd, timeout: (False, "pip exploded"))
    monkeypatch.setattr(browser, "_install_attempted", False)
    ok, reason = browser.ensure_installed(force=True)
    assert not ok and "pip exploded" in reason and "python -m pip install playwright" in reason


# --- which keyword goes into the form (regression: the preferred titles silently replaced the saved keyword) ---


def test_form_keywords_follow_the_saved_criteria_unless_asked_otherwise(config):
    from jobsearch_sources.htmlpages import form_keywords
    from jobsearch_sources.providers import SearchContext

    site = yahoo_site()

    def ctx(keywords, explicit):
        return SearchContext(site=site, prefs=config.preferences, settings=config.search, options=site.options, keywords=keywords, keywords_explicit=explicit)

    titles = ["data analyst", "bi analyst"]
    # default: the saved keyword (or none) — the titles defaulted by the app are NOT pushed into the form
    assert form_keywords(ctx(titles, False), {}, {"keyword": ""}) == [""]
    assert form_keywords(ctx(titles, False), {"keyword_mode": "criteria"}, {"keyword": "sql"}) == ["sql"]
    # opted in: the titles, one submission each
    assert form_keywords(ctx(titles, False), {"keyword_mode": "titles"}, {"keyword": "sql"}) == titles
    assert form_keywords(ctx([], False), {"keyword_mode": "titles"}, {"keyword": "sql"}) == ["sql"]
    # an explicit request for this run (Research override / form test) always wins, including "no keyword"
    assert form_keywords(ctx(["engineer"], True), {}, {"keyword": "sql"}) == ["engineer"]
    assert form_keywords(ctx([], True), {"keyword_mode": "titles"}, {"keyword": "sql"}) == [""]
    site.options["search_form"]["keyword_mode"] = "maybe"
    config.sites = [site]
    assert any("'keyword_mode' must be" in str(i) for i in jc.validate(config, registry=False))


def test_search_site_marks_explicit_keywords(config, monkeypatch):
    from jobsearch_sources import search as search_mod

    seen: list[tuple[list[str], bool]] = []

    def adapter(ctx):
        seen.append((list(ctx.keywords), ctx.keywords_explicit))
        return []

    monkeypatch.setitem(search_mod.ADAPTERS, "html", adapter)
    site = yahoo_site()
    site.options["search_form"]["validated"] = {"at": "x", "jobs": 1, "strategy": "yahoo-careers@2"}
    site.enabled = True
    config.sites = [site]
    config.preferences.titles = ["data analyst"]
    js.run_search(config)  # defaulted from the titles
    js.run_search(config, keyword="engineer")  # Research-page override
    js.run_search(config, keyword="")  # explicitly no keyword
    sf.test_form(site, config, {"keyword": "", "categories": ["Finance"]})  # the panel as shown
    assert seen == [(["data analyst"], False), (["engineer"], True), ([], True), ([], True)]
