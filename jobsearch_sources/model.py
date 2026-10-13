"""Normalised job listing produced by every provider adapter."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")

# Map of the many strings feeds use for employment type -> (job_type, schedule)
_JOB_TYPE_ALIASES: dict[str, tuple[str, str]] = {
    "full_time": ("permanent", "full_time"),
    "full-time": ("permanent", "full_time"),
    "fulltime": ("permanent", "full_time"),
    "full time": ("permanent", "full_time"),
    "permanent": ("permanent", ""),
    "regular": ("permanent", ""),
    "employee": ("permanent", ""),
    "part_time": ("", "part_time"),
    "part-time": ("", "part_time"),
    "parttime": ("", "part_time"),
    "part time": ("", "part_time"),
    "contract": ("contract", ""),
    "contractor": ("contract", ""),
    "contract_to_hire": ("contract", ""),
    "fixed term": ("contract", ""),
    "fixed-term": ("contract", ""),
    "temporary": ("temporary", ""),
    "temp": ("temporary", ""),
    "seasonal": ("temporary", ""),
    "freelance": ("freelance", ""),
    "freelancer": ("freelance", ""),
    "internship": ("internship", ""),
    "intern": ("internship", ""),
    "apprenticeship": ("internship", ""),
    "trainee": ("internship", ""),
    "working student": ("internship", "part_time"),
}


def plain_text(value: Any, limit: int = 2000) -> str:
    """Strip HTML tags and collapse whitespace."""
    text = _TAG_RE.sub(" ", str(value or ""))
    text = text.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    text = _WS_RE.sub(" ", text)
    text = re.sub(r"\s+([,.;:!?)])", r"\1", text)  # "SQL </b>," -> "SQL,"
    return text.strip()[:limit]


def normalise_job_type(*values: Any) -> tuple[str, str]:
    """Return ``(job_type, schedule)`` from one or more raw employment-type strings.

    Unknown values yield empty strings; callers treat "" as unknown.
    """
    job_type = ""
    schedule = ""
    for value in values:
        if not value:
            continue
        items = value if isinstance(value, (list, tuple, set)) else [value]
        for item in items:
            key = str(item).strip().lower().replace("_", "_")
            match = _JOB_TYPE_ALIASES.get(key)
            if match is None:
                # try loose contains, e.g. "Full-Time Employee"
                for alias, pair in _JOB_TYPE_ALIASES.items():
                    if alias in key:
                        match = pair
                        break
            if match:
                job_type = job_type or match[0]
                schedule = schedule or match[1]
    return job_type, schedule


def normalise_workplace(value: Any, default: str = "") -> str:
    text = str(value or "").strip().lower()
    if not text:
        return default
    if "hybrid" in text:
        return "hybrid"
    if "remote" in text or "anywhere" in text or "work from home" in text or "wfh" in text:
        return "remote"
    if "on-site" in text or "onsite" in text or "on site" in text or "in office" in text or "in-office" in text:
        return "onsite"
    return default


def parse_date(value: Any) -> str:
    """Best-effort ISO date (YYYY-MM-DD) from timestamps, RFC 2822 or ISO strings."""
    if value in (None, ""):
        return ""
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value)).date().isoformat()
        except (OverflowError, OSError, ValueError):
            return ""
    text = str(value).strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}", text):
        return text[:10]
    try:
        from email.utils import parsedate_to_datetime

        return parsedate_to_datetime(text).date().isoformat()
    except (TypeError, ValueError, IndexError):
        pass
    for fmt in ("%d/%m/%Y", "%m/%d/%Y", "%Y/%m/%d", "%d %b %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(text[:len(fmt) + 4], fmt).date().isoformat()
        except ValueError:
            continue
    return ""


_MONEY_RE = re.compile(r"(\d[\d,\.]*)\s*([kK])?")


def parse_salary_text(text: str) -> tuple[int | None, int | None, str, str]:
    """Pull (min, max, currency, period) out of strings like '$85k–$105k / year'."""
    if not text:
        return None, None, "", ""
    raw = str(text)
    lowered = raw.lower()
    currency = ""
    for symbol, code in (("$", "USD"), ("€", "EUR"), ("£", "GBP"), ("₹", "INR")):
        if symbol in raw:
            currency = code
            break
    for code in ("USD", "EUR", "GBP", "CAD", "AUD", "INR", "CHF", "SGD", "JPY"):
        if code.lower() in lowered.split() or code in raw:
            currency = code
            break
    period = ""
    if any(w in lowered for w in ("hour", "/hr", "hourly", "p/h", "per h")):
        period = "hour"
    elif any(w in lowered for w in ("day", "daily", "/d")):
        period = "day"
    elif any(w in lowered for w in ("month", "/mo", "monthly")):
        period = "month"
    elif any(w in lowered for w in ("year", "annum", "/yr", "annual", "pa", "k")):
        period = "year"
    numbers: list[int] = []
    for amount, k in _MONEY_RE.findall(raw):
        cleaned = amount.replace(",", "")
        if re.fullmatch(r"\d{1,3}(\.\d{3})+", cleaned):
            cleaned = cleaned.replace(".", "")  # "60.000" (EU thousands separator)
        try:
            number = float(cleaned.rstrip("."))
        except ValueError:
            continue
        if k:
            number *= 1000
        if number >= 10:
            numbers.append(int(number))
    if not numbers:
        return None, None, currency, period
    numbers = numbers[:2]
    low, high = min(numbers), max(numbers)
    return low, high, currency, period


@dataclass
class Job:
    title: str
    organization: str = ""
    location: str = ""
    workplace: str = ""  # remote | hybrid | onsite | ""
    url: str = ""
    source: str = ""  # site name (as configured)
    site_id: str = ""
    description: str = ""
    salary_text: str = ""
    salary_min: int | None = None
    salary_max: int | None = None
    salary_currency: str = ""
    salary_period: str = ""
    job_type: str = ""  # permanent | contract | temporary | freelance | internship | ""
    schedule: str = ""  # full_time | part_time | ""
    industry: str = ""
    tags: list[str] = field(default_factory=list)
    published: str = ""  # YYYY-MM-DD
    external_id: str = ""

    def __post_init__(self) -> None:
        self.title = plain_text(self.title, 300) or "Untitled role"
        self.organization = plain_text(self.organization, 200)
        self.location = plain_text(self.location, 200)
        self.description = plain_text(self.description)
        self.tags = [str(t).strip() for t in (self.tags or []) if str(t).strip()]
        if (self.salary_min is None and self.salary_max is None) and self.salary_text:
            low, high, currency, period = parse_salary_text(self.salary_text)
            self.salary_min, self.salary_max = low, high
            self.salary_currency = self.salary_currency or currency
            self.salary_period = self.salary_period or period
        if not self.salary_text and (self.salary_min or self.salary_max):
            low = f"{self.salary_min:,}" if self.salary_min else ""
            high = f"{self.salary_max:,}" if self.salary_max else ""
            self.salary_text = f"{low}–{high} {self.salary_currency}".strip("– ").strip()
            if self.salary_period:
                self.salary_text += f" / {self.salary_period}"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def searchable_text(self) -> str:
        return " ".join([self.title, self.organization, self.description, " ".join(self.tags), self.industry]).lower()

    def age_days(self, today: date | None = None) -> int | None:
        if not self.published:
            return None
        try:
            return ((today or date.today()) - date.fromisoformat(self.published)).days
        except ValueError:
            return None
