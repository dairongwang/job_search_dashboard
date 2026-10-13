"""Normalisation helpers and the preference filter / ranking."""

from __future__ import annotations

from datetime import date

import jobsearch_config as jc
from jobsearch_sources.filters import check_location, check_salary, evaluate, location_tokens
from jobsearch_sources.model import Job, normalise_job_type, normalise_workplace, parse_date, parse_salary_text

TODAY = date(2026, 10, 12)


def test_job_type_aliases():
    assert normalise_job_type("full_time") == ("permanent", "full_time")
    assert normalise_job_type(["Part-time", "Contract"]) == ("contract", "part_time")
    assert normalise_job_type("Temp") == ("temporary", "")
    assert normalise_job_type("Full-Time Employee") == ("permanent", "full_time")
    assert normalise_job_type(None, "") == ("", "")
    assert normalise_job_type("Working Student") == ("internship", "part_time")


def test_workplace_and_dates():
    assert normalise_workplace("Remote - USA") == "remote"
    assert normalise_workplace("Hybrid (Philadelphia)") == "hybrid"
    assert normalise_workplace("New York, NY", "onsite") == "onsite"
    assert parse_date("2026-10-10T09:00:00") == "2026-10-10"
    assert parse_date("Sat, 10 Oct 2026 09:00:00 GMT") == "2026-10-10"
    assert parse_date(1791000000)  # epoch
    assert parse_date("garbage") == ""


def test_salary_text_parsing():
    assert parse_salary_text("$90k - $120k / year") == (90000, 120000, "USD", "year")
    assert parse_salary_text("£45,000 per annum") == (45000, 45000, "GBP", "year")
    assert parse_salary_text("$45/hour") == (45, 45, "USD", "hour")
    assert parse_salary_text("") == (None, None, "", "")
    job = Job(title="x", salary_text="€60.000 - €70.000")
    assert (job.salary_min, job.salary_max, job.salary_currency) == (60000, 70000, "EUR")


def test_location_tokens_and_matching():
    assert "usa" in location_tokens("United States")
    assert location_tokens("Philadelphia, PA") == ["philadelphia", "pa"]
    prefs = jc.JobPreferences(locations=["United States", "Philadelphia, PA"])
    assert check_location(Job(title="t", location="USA", workplace="remote"), prefs) == (True, True)
    assert check_location(Job(title="t", location="Philadelphia, Pennsylvania"), prefs) == (True, True)
    assert check_location(Job(title="t", location="Worldwide", workplace="remote"), prefs) == (True, False)
    assert check_location(Job(title="t", location="Europe", workplace="remote"), prefs) == (False, False)
    assert check_location(Job(title="t", location="Paris, France", workplace="onsite"), prefs) == (False, False)
    # 'pa' must not match inside words like 'Spain'
    assert check_location(Job(title="t", location="Spain"), prefs) == (False, False)
    # Adding 'Remote' accepts remote roles from any region
    prefs_any = jc.JobPreferences(locations=["Remote", "Philadelphia, PA"])
    assert check_location(Job(title="t", location="Europe", workplace="remote"), prefs_any) == (True, False)
    # No location preference = everything passes
    assert check_location(Job(title="t", location="Mars"), jc.JobPreferences()) == (True, False)


def test_salary_checks_and_period_conversion():
    prefs = jc.JobPreferences(salary=jc.SalaryRange(minimum=80000, maximum=120000, currency="USD", include_unlisted=False))
    assert check_salary(Job(title="t", salary_min=90000, salary_max=100000, salary_currency="USD", salary_period="year"), prefs) == (True, "in range")
    assert check_salary(Job(title="t", salary_min=60000, salary_max=70000, salary_currency="USD", salary_period="year"), prefs) == (False, "out of range")
    assert check_salary(Job(title="t", salary_min=70000, salary_max=90000, salary_currency="USD", salary_period="year"), prefs) == (True, "in range")
    assert check_salary(Job(title="t"), prefs) == (False, "unlisted")
    assert check_salary(Job(title="t", salary_min=50, salary_currency="USD", salary_period="hour"), prefs) == (True, "in range")  # 104k/yr
    assert check_salary(Job(title="t", salary_min=90000, salary_currency="GBP", salary_period="year"), prefs) == (False, "currency")
    prefs.salary.include_unlisted = True
    assert check_salary(Job(title="t"), prefs) == (True, "unlisted")
    assert check_salary(Job(title="t", salary_min=90000, salary_currency="GBP", salary_period="year"), prefs) == (True, "currency")


def _prefs(**overrides) -> jc.JobPreferences:
    base = dict(
        titles=["data analyst"],
        skills=["SQL", "Python", "Tableau", "R"],
        locations=["United States", "Philadelphia, PA"],
        job_types=["permanent", "contract"],
        schedules=["full_time"],
        exclude_keywords=["clearance"],
        salary=jc.SalaryRange(minimum=80000, currency="USD"),
        posted_within_days=30,
    )
    base.update(overrides)
    return jc.JobPreferences(**base)


def test_evaluate_good_match_scores_high():
    job = Job(title="Senior Data Analyst", location="USA", workplace="remote", description="SQL and Python, Tableau dashboards. R optional.",
              salary_min=90000, salary_max=110000, salary_currency="USD", salary_period="year", job_type="permanent", schedule="full_time", published="2026-10-10")
    m = evaluate(job, _prefs(), TODAY)
    assert m.passed and m.reasons == []
    assert m.matched_skills == ["SQL", "Python", "Tableau", "R"]
    assert m.score >= 100


def test_evaluate_hard_filters():
    p = _prefs()
    assert "job type internship" in evaluate(Job(title="Data Analyst Intern", job_type="internship", location="USA"), p, TODAY).reasons
    assert "schedule part_time" in evaluate(Job(title="Data Analyst", schedule="part_time", location="USA"), p, TODAY).reasons
    assert "workplace onsite" in evaluate(Job(title="Data Analyst", workplace="onsite", location="USA"), _prefs(workplaces=["remote"]), TODAY).reasons
    assert any(r.startswith("location") for r in evaluate(Job(title="Data Analyst", location="Berlin", workplace="onsite"), p, TODAY).reasons)
    assert "salary out of range" in evaluate(Job(title="Data Analyst", location="USA", salary_min=50000, salary_max=60000, salary_currency="USD"), p, TODAY).reasons
    assert "posted 60 days ago" in evaluate(Job(title="Data Analyst", location="USA", published="2026-08-13"), p, TODAY).reasons
    assert "excluded keyword 'clearance'" in evaluate(Job(title="Data Analyst", location="USA", description="Active clearance required"), p, TODAY).reasons
    assert "job type unknown" in evaluate(Job(title="Data Analyst", location="USA"), _prefs(include_unknown_job_type=False), TODAY).reasons
    m = evaluate(Job(title="Data Analyst", location="USA", description="Excel only"), _prefs(min_skill_matches=2), TODAY)
    assert "only 0 of 2 required skills" in m.reasons


def test_skill_matching_is_whole_word():
    # "R" should not match "Tableau" or "developer"; "C" should not match "Scala"
    job = Job(title="Data Analyst", description="Tableau developer using Scala")
    m = evaluate(job, _prefs(skills=["R", "C", "Tableau"], locations=[]), TODAY)
    assert m.matched_skills == ["Tableau"]


def test_unknowns_pass_by_default():
    job = Job(title="Data Analyst")  # no location, no type, no salary, no date
    m = evaluate(job, _prefs(), TODAY)
    assert m.passed
