"""Apply job preferences to normalised listings: hard filters + relevance score.

Every site returns a slightly different subset of fields, so the rules are
deliberately forgiving: unknown values pass (configurable for job type and
salary) and only affect ranking.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from jobsearch_config.schema import JobPreferences

from .model import Job

# Hours/days/months in a working year, for rough period conversion.
_PERIOD_TO_YEAR = {"hour": 2080, "day": 260, "month": 12, "year": 1}

_GLOBAL_LOCATIONS = {"", "worldwide", "anywhere", "global", "remote", "international", "anywhere in the world", "everywhere"}

# Loose synonyms so "United States" matches "USA" / "US" and so on.
_LOCATION_SYNONYMS: dict[str, tuple[str, ...]] = {
    "united states": ("usa", "us", "u.s.", "u.s.a", "us only", "us-based", "united states", "america", "north america"),
    "usa": ("usa", "u.s.", "united states", "us only", "us-based", "north america"),
    "us": ("usa", "u.s.", "united states", "us only", "us-based"),
    "united kingdom": ("uk", "u.k.", "united kingdom", "england", "scotland", "wales", "london", "britain"),
    "uk": ("uk", "u.k.", "united kingdom", "england", "scotland", "wales", "britain"),
    "europe": ("europe", "eu", "emea", "european"),
    "eu": ("europe", "eu", "european"),
    "canada": ("canada", "canadian", "north america"),
    "germany": ("germany", "deutschland", "berlin", "munich", "münchen", "hamburg", "frankfurt"),
    "australia": ("australia", "australian", "apac", "sydney", "melbourne"),
    "india": ("india", "bangalore", "bengaluru", "hyderabad", "pune", "mumbai", "delhi", "apac"),
    "latin america": ("latam", "latin america", "south america"),
    "asia": ("asia", "apac"),
}

_US_STATES = {
    "al", "ak", "az", "ar", "ca", "co", "ct", "de", "fl", "ga", "hi", "id", "il", "in", "ia", "ks", "ky", "la", "me", "md", "ma",
    "mi", "mn", "ms", "mo", "mt", "ne", "nv", "nh", "nj", "nm", "ny", "nc", "nd", "oh", "ok", "or", "pa", "ri", "sc", "sd", "tn",
    "tx", "ut", "vt", "va", "wa", "wv", "wi", "wy", "dc",
}


@dataclass
class Match:
    score: int = 0
    passed: bool = True
    reasons: list[str] = field(default_factory=list)  # failed hard filters, with detail
    kinds: list[str] = field(default_factory=list)  # failed hard filters, by category (for summaries)
    matched_skills: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)  # soft signals, for the UI

    def fail(self, reason: str, kind: str = "") -> None:
        self.passed = False
        self.reasons.append(reason)
        self.kinds.append(kind or reason)


def _word_in(needle: str, haystack: str) -> bool:
    """Whole-word, case-insensitive containment. Short tokens like 'C', 'R', 'Go' need boundaries."""
    pattern = r"(?<![a-z0-9+#])" + re.escape(needle.lower()) + r"(?![a-z0-9+#])"
    return re.search(pattern, haystack) is not None


def location_tokens(pref_location: str) -> list[str]:
    """Expand a preferred location into lowercase search tokens.

    'Philadelphia, PA' -> ['philadelphia', 'pa']  (state code kept as a token; matched as a word)
    'United States'    -> ['united states', 'usa', 'u.s.', ...]
    """
    text = pref_location.strip().lower()
    if not text:
        return []
    tokens: list[str] = []
    for part in re.split(r"[,/;]| - | — ", text):
        part = part.strip()
        if not part:
            continue
        tokens.append(part)
        tokens.extend(_LOCATION_SYNONYMS.get(part, ()))
    return list(dict.fromkeys(tokens))


def _matches_location(job_location: str, pref_location: str) -> bool:
    hay = job_location.lower()
    if not hay:
        return False
    for token in location_tokens(pref_location):
        if token in _US_STATES:
            if re.search(r"(?<![a-z])" + token + r"(?![a-z])", hay):
                return True
        elif len(token) <= 3:
            if _word_in(token, hay):
                return True
        elif token in hay:
            return True
    return False


_US_CITIES = {
    "new york", "nyc", "los angeles", "chicago", "houston", "phoenix", "philadelphia", "philly", "san antonio", "san diego",
    "dallas", "san jose", "austin", "jacksonville", "san francisco", "columbus", "charlotte", "indianapolis", "seattle",
    "denver", "washington dc", "boston", "nashville", "detroit", "portland", "las vegas", "baltimore", "milwaukee",
    "atlanta", "miami", "minneapolis", "pittsburgh", "raleigh", "salt lake city", "st. louis", "kansas city", "cleveland",
}
_COUNTRY_SYNONYMS_FOR_IMPLIED = {
    "united states": _LOCATION_SYNONYMS["united states"],
    "united kingdom": _LOCATION_SYNONYMS["united kingdom"],
    "canada": _LOCATION_SYNONYMS["canada"],
}
_UK_HINTS = {"london", "manchester", "birmingham", "edinburgh", "glasgow", "leeds", "bristol", "england", "scotland", "wales"}
_CA_PROVINCES = {"on", "bc", "ab", "qc", "mb", "sk", "ns", "nb", "nl", "pe", "ontario", "british columbia", "alberta", "quebec"}


def implied_countries(pref_location: str) -> list[str]:
    """Countries implied by a city/state, e.g. 'Philadelphia, PA' -> ['united states'].

    Used so that remote roles restricted to a country still match someone who
    only listed a city in that country.
    """
    tokens = set(location_tokens(pref_location))
    parts = {p.strip() for p in re.split(r"[,/;]", pref_location.lower())}
    countries: list[str] = []
    if tokens & _US_STATES or parts & _US_CITIES:
        countries.append("united states")
    if parts & _UK_HINTS:
        countries.append("united kingdom")
    if parts & _CA_PROVINCES:
        countries.append("canada")
    return countries


def _matches_implied_country(job_location: str, pref_location: str) -> bool:
    hay = job_location.lower()
    for country in implied_countries(pref_location):
        for token in _COUNTRY_SYNONYMS_FOR_IMPLIED[country]:
            if (len(token) <= 3 and _word_in(token, hay)) or (len(token) > 3 and token in hay):
                return True
    return False


def _wants_any_remote(prefs: JobPreferences) -> bool:
    return any(loc.strip().lower() in {"remote", "anywhere", "worldwide", "global"} for loc in prefs.locations)


def check_location(job: Job, prefs: JobPreferences) -> tuple[bool, bool]:
    """Return ``(passes, explicit_match)``."""
    if not prefs.locations:
        return True, False
    if any(_matches_location(job.location, loc) for loc in prefs.locations):
        return True, True
    if job.workplace == "remote" and "remote" in prefs.workplaces:
        loc = job.location.lower().strip()
        if loc in _GLOBAL_LOCATIONS or _wants_any_remote(prefs):
            return True, False
        if any(_matches_implied_country(job.location, pref) for pref in prefs.locations):
            return True, False  # remote role open to the country the user's city is in
    if not job.location:
        return True, False  # unknown location: keep, let the user judge
    return False, False


def salary_per_year(amount: int | None, period: str) -> int | None:
    if amount is None:
        return None
    return int(amount * _PERIOD_TO_YEAR.get(period or "year", 1))


def check_salary(job: Job, prefs: JobPreferences) -> tuple[bool, str]:
    """Return ``(passes, note)``. Note is '' / 'unlisted' / 'currency' / 'in range' / 'out of range'."""
    target = prefs.salary
    if not target.is_set:
        return True, ""
    if job.salary_min is None and job.salary_max is None:
        return target.include_unlisted, "unlisted"
    if job.salary_currency and job.salary_currency.upper() != target.currency.upper():
        return target.include_unlisted, "currency"
    job_period = job.salary_period or target.period
    low = salary_per_year(job.salary_min, job_period)
    high = salary_per_year(job.salary_max, job_period)
    low = low if low is not None else high
    high = high if high is not None else low
    want_low = salary_per_year(target.minimum, target.period) if target.minimum is not None else 0
    want_high = salary_per_year(target.maximum, target.period) if target.maximum is not None else 10**12
    # Pass if the ranges overlap: the job's top end reaches the minimum wanted and its bottom end is under the maximum.
    if high is not None and high < want_low:
        return False, "out of range"
    if low is not None and low > want_high:
        return False, "out of range"
    return True, "in range"


def evaluate(job: Job, prefs: JobPreferences, today: date | None = None) -> Match:
    match = Match()
    text = job.searchable_text
    title = job.title.lower()

    # --- hard filters -------------------------------------------------------
    for word in prefs.exclude_keywords:
        if _word_in(word, text):
            match.fail(f"excluded keyword '{word}'", "excluded keyword")
            break

    if job.job_type:
        if job.job_type not in prefs.job_types:
            match.fail(f"job type {job.job_type}", "job type")
    elif not prefs.include_unknown_job_type:
        match.fail("job type unknown", "job type unknown")
    if job.schedule and job.schedule not in prefs.schedules:
        match.fail(f"schedule {job.schedule}", "schedule")

    if job.workplace and job.workplace not in prefs.workplaces:
        match.fail(f"workplace {job.workplace}", "workplace")

    loc_ok, loc_explicit = check_location(job, prefs)
    if not loc_ok:
        match.fail(f"location '{job.location}'", "location")

    sal_ok, sal_note = check_salary(job, prefs)
    if not sal_ok:
        match.fail("salary " + sal_note, "salary " + sal_note)
    if sal_note:
        match.notes.append(f"salary {sal_note}")

    age = job.age_days(today)
    if prefs.posted_within_days and age is not None and age > prefs.posted_within_days:
        match.fail(f"posted {age} days ago", "posted too long ago")

    matched = [skill for skill in prefs.skills if _word_in(skill, text)]
    match.matched_skills = matched
    if prefs.min_skill_matches and len(matched) < prefs.min_skill_matches:
        match.fail(f"only {len(matched)} of {prefs.min_skill_matches} required skills", "too few skills")

    # --- score ----------------------------------------------------------------
    score = 0
    for phrase in prefs.titles:
        phrase_l = phrase.lower()
        if phrase_l and phrase_l in title:
            score += 40
            break
        words = [w for w in re.split(r"\W+", phrase_l) if len(w) > 2]
        if words and all(_word_in(w, title) for w in words):
            score += 30
            break
        if words and any(_word_in(w, title) for w in words):
            score += 12
            break
    else:
        if prefs.titles and any(p.lower() in text for p in prefs.titles):
            score += 6
    score += min(50, 10 * len(matched))
    for industry in prefs.industries:
        tokens = [t.strip().lower() for t in industry.split("/") if t.strip()]
        if any(t in (job.industry or "").lower() or _word_in(t, text) for t in tokens):
            score += 10
            break
    if sal_note == "in range":
        score += 10
    if loc_explicit:
        score += 10
    if job.workplace and job.workplace == prefs.workplaces[0]:
        score += 5
    if age is not None:
        if age <= 7:
            score += 10
        elif age <= 14:
            score += 5
    match.score = score
    return match


def apply(jobs: list[Job], prefs: JobPreferences, *, strict: bool = True, today: date | None = None) -> list[tuple[Job, Match]]:
    """Evaluate and sort listings; drop failures when ``strict``."""
    scored = [(job, evaluate(job, prefs, today)) for job in jobs]
    if strict:
        scored = [(job, m) for job, m in scored if m.passed]
    scored.sort(key=lambda pair: (pair[1].passed, pair[1].score, pair[0].published), reverse=True)
    return scored
