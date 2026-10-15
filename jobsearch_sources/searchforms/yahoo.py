"""Yahoo careers (yahooinc.com/careers) — search-form strategies.

Two layouts of the same site's form are kept; the registry tries them in
order and uses the one whose fingerprint matches the live page:

* **version 2** (observed 2026-02, ``careers/search.html``): the *Filter jobs*
  form ``<form id="collapseFilterJobs" method="POST">`` — keyword input
  ``name="keyword"``, checkbox dropdowns *Select job categories*
  (``#JCDropdown``), *Select countries* (``#JLDropdown``), *Select brands*
  (``#JBDropdown``), *Select experience* (``#JEDropdown``) and the submit
  button ``<button id="search-page-find-jobs-mobile" type="submit">Find jobs</button>``.
* **version 1** (observed 2026-02, ``careers/`` landing page): the search bar
  ``<form action="/careers/search.html" method="POST">`` — keyword input
  ``#search-keyword`` (``name="keyword"``, label *Key words*), the same three
  checkbox dropdowns (``name="categories[]" / "locations[]" / "brands[]"``)
  and ``<button id="index-page-find-jobs" type="submit">Find jobs</button>``;
  submitting navigates to the results page.

Both render results into ``<tbody id="tableJobListing">`` as
``<tr class="jobTitle">`` rows (title link → Workday job page, brand,
location) with a *Load more* button, or an ``.errorMsg`` when nothing matches.
A page matching neither is handled by the automatic form learner
(``learn.py``), which derives a new version from the live page.

The form is driven inside the headless browser exactly as a person would use
it: fill the keyword, tick the checkboxes, press *Find jobs*, wait for the
result table to change, press *Load more*. Steps carry ``"force": true`` so
that a control hidden by the responsive layout (the filter form is collapsed
and only shown on tablet/mobile widths) is still operated, through a
JavaScript click/fill on the same element.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin

from .base import FormField, SearchFormStrategy, css_string

YAHOO_CATEGORIES = [
    "Administration", "Business Development", "Business Operations", "Content", "Customer Experience", "Design",
    "eCommerce Operations", "Engineering", "Finance", "Human Resources", "Information Systems", "Internship", "Legal",
    "Marketing", "Operations", "Research", "Sales", "Software Development",
]
YAHOO_COUNTRIES = [
    "Australia", "Brazil", "Canada", "Denmark", "France", "Germany", "Hong Kong", "India", "Ireland", "Israel", "Italy",
    "Japan", "New Zealand", "Norway", "Singapore", "Spain", "Sweden", "Taiwan", "United Kingdom", "United States",
]
YAHOO_BRANDS = ["Boundless", "Yahoo", "Yahoo Engineering", "Yahoo Finance", "Yahoo Mail", "Yahoo News", "Yahoo Search", "Yahoo Sports"]
YAHOO_EXPERIENCE = ["Developmental Programs", "Early Career", "Individual Contributor", "Management", "Sr Management", "Executive Leadership"]

_RESULTS_TOTAL = re.compile(r"showing\s+(\d+)\s+results?\s+of\s+(\d+)", re.IGNORECASE)


class _YahooResultsMixin:
    """Result table shared by every layout: ``#tableJobListing tr.jobTitle`` or an ``.errorMsg``."""

    def parse_results(self, soup: Any, base_url: str) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        for tr in soup.select("#tableJobListing tr.jobTitle"):
            link = tr.select_one("td[data-title=Title] a[href], .innerJobTitle a[href], a[href]")
            if link is None:
                continue
            title = link.get_text(" ", strip=True)
            if not title:
                continue
            brand = tr.select_one("td.tableBrand")
            location = tr.select_one("td.tableLocation .tableLocPrimary, td.tableLocation")
            rows.append(
                {
                    "title": title,
                    "link": urljoin(base_url, link["href"]),
                    "company": (brand.get_text(" ", strip=True) if brand else "") or "Yahoo",
                    "location": location.get_text(" ", strip=True) if location else "",
                    "salary": "",
                    "date": "",
                    "description": "",
                    "job_type": "",
                }
            )
        return rows

    @property
    def owns_results(self) -> bool:
        return True

    def results_total(self, soup: Any) -> tuple[int | None, int | None]:
        node = soup.select_one(".resultsTotal")
        match = _RESULTS_TOTAL.search(node.get_text(" ", strip=True)) if node else None
        if match:
            return int(match.group(1)), int(match.group(2))
        if self.no_results_message(soup):
            return 0, 0
        return None, None

    def no_results_message(self, soup: Any) -> str:
        """Yahoo renders '<div id="messageBox" class="errorMsg">We currently do not have any jobs matching …' into the table body."""
        node = soup.select_one("#tableJobListing .errorMsg, #tableJobListing #messageBox, #searchResults .errorMsg")
        if node is not None and node.get_text(strip=True):
            return node.get_text(" ", strip=True)
        total = soup.select_one(".resultsTotal")
        text = total.get_text(" ", strip=True) if total else ""
        if text and not _RESULTS_TOTAL.search(text) and not soup.select("#tableJobListing tr.jobTitle"):
            return text  # e.g. "Please 'Clear' the search and try again"
        return ""


class YahooCareersFormV2(_YahooResultsMixin, SearchFormStrategy):
    """The ``#collapseFilterJobs`` filter form on yahooinc.com/careers/search.html (2026 layout)."""

    family = "yahoo-careers"
    version = "2"
    since = "2026-02"
    label = "Yahoo careers — Filter jobs form (#collapseFilterJobs)"
    hosts = ("yahooinc.com",)
    form_hint = 'form#collapseFilterJobs (method="POST") → button#search-page-find-jobs-mobile "Find jobs"'
    start_url = "https://www.yahooinc.com/careers/search.html"
    viewport = {"width": 820, "height": 1180}  # tablet width: the filter form is inside a .mobileTabletOnly container
    notes = (
        "Keyword + job categories, countries, brands and experience checkboxes; results in #tableJobListing with a "
        "Load more button. Job links point at Workday job pages (ouryahoo.wd5.myworkdayjobs.com), which carry JobPosting data."
    )

    # checkbox dropdown id per field
    DROPDOWNS = {"categories": "JCDropdown", "countries": "JLDropdown", "brands": "JBDropdown", "experience": "JEDropdown"}
    TOGGLES = {"categories": "jobCategories", "countries": "jobLocations", "brands": "jobBrands", "experience": "jobExperience"}

    def fields(self) -> list[FormField]:
        return [
            FormField("keyword", "Search by keywords", "text", placeholder="Search by keywords", binds="keyword",
                      help="Typed into the keyword box. Searches submit exactly this saved keyword (blank = none) unless the site is set to use your preferred titles; a Research-page keyword replaces it for that run."),
            FormField("categories", "Select job categories", "multiselect", YAHOO_CATEGORIES, help="Job category checkboxes (#JCDropdown)."),
            FormField("countries", "Select countries", "multiselect", YAHOO_COUNTRIES, help="Country checkboxes (#JLDropdown)."),
            FormField("brands", "Select brands", "multiselect", YAHOO_BRANDS, help="Brand checkboxes (#JBDropdown)."),
            FormField("experience", "Select experience", "multiselect", YAHOO_EXPERIENCE, help="Experience-level checkboxes (#JEDropdown)."),
        ]

    def fingerprint(self) -> list[str]:
        return [
            "form#collapseFilterJobs",
            "form#collapseFilterJobs input[name=keyword]",
            "#JCDropdown",
            "#JLDropdown",
            "#JBDropdown",
            "button#search-page-find-jobs-mobile",
        ]

    def live_options(self, soup: Any) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for key, dropdown in self.DROPDOWNS.items():
            values = [str(node.get("value") or "").strip() for node in soup.select(f"#{dropdown} input[type=checkbox]")]
            values = [v for v in values if v]
            if values:
                out[key] = values
        return out

    def steps(self, criteria: dict[str, Any], pages: int = 1) -> list[dict[str, Any]]:
        crit = self.normalise_criteria(criteria)
        form = "form#collapseFilterJobs"
        steps: list[dict[str, Any]] = [
            # the form is a Bootstrap collapse; the sticky header's "Filter jobs" link expands it (absent on some widths)
            {"click": {"css": "a[data-target='#collapseFilterJobs']"}, "optional": True, "force": True, "timeout_ms": 2000},
            {"remember": {"css": "#tableJobListing"}, "optional": True},
            {"fill": {"css": f"{form} input[name=keyword]"}, "value": crit.get("keyword", ""), "force": True},
        ]
        for key, dropdown in self.DROPDOWNS.items():
            chosen = crit.get(key) or []
            if not chosen:
                continue
            toggle = {"css": f"{form} button.{self.TOGGLES[key]}"}
            steps.append({"click": toggle, "optional": True, "force": True, "timeout_ms": 2000})  # open the dropdown
            for value in chosen:
                steps.append({"check": {"css": f"#{dropdown} input[type=checkbox][value={css_string(value)}]"}, "force": True})
            steps.append({"click": toggle, "optional": True, "force": True, "timeout_ms": 2000})  # close it again
        steps += [
            {"click": {"css": f"{form} button#search-page-find-jobs-mobile"}, "force": True},
            {"wait": "networkidle", "optional": True},
            {"wait_change": {"css": "#tableJobListing"}, "optional": True, "timeout_ms": 8000},
            {"wait": {"css": "#tableJobListing"}, "optional": True, "timeout_ms": 5000, "settle_ms": 500},
        ]
        if pages > 1:
            steps.append({"click": {"css": "button.loadMore"}, "repeat": pages - 1, "optional": True, "force": True, "snapshot": True, "settle_ms": 800})
        return steps



class YahooCareersFormV1(_YahooResultsMixin, SearchFormStrategy):
    """The search bar on the careers landing page (/careers/): posts to /careers/search.html."""

    family = "yahoo-careers"
    version = "1"
    since = "2026-02"
    label = "Yahoo careers — landing page search bar (form → /careers/search.html)"
    hosts = ("yahooinc.com",)
    form_hint = 'form[action="/careers/search.html"] (method="POST") → button#index-page-find-jobs "Find jobs"'
    start_url = "https://www.yahooinc.com/careers/"
    notes = (
        "Keyword + job categories, countries and brands (no experience filter on this page); submitting navigates to the results "
        "page, whose #tableJobListing is read like version 2."
    )

    FORM = 'form[action$="search.html"]'  # action="/careers/search.html"
    DROPDOWNS = {"categories": "JCDropdown", "countries": "JLDropdown", "brands": "JBDropdown"}
    TOGGLES = {"categories": "jobCategories", "countries": "jobLocations", "brands": "jobBrands"}

    def fields(self) -> list[FormField]:
        return [
            FormField("keyword", "Key words", "text", placeholder="Search by keywords", binds="keyword",
                      help="Typed into the keyword box (#search-keyword). Searches submit exactly this saved keyword (blank = none) unless the site is set to use your preferred titles; a Research-page keyword replaces it for that run."),
            FormField("categories", "Select job categories", "multiselect", YAHOO_CATEGORIES, help="Job category checkboxes (#JCDropdown, name=categories[])."),
            FormField("countries", "Select countries", "multiselect", YAHOO_COUNTRIES, help="Country checkboxes (#JLDropdown, name=locations[])."),
            FormField("brands", "Select brands", "multiselect", YAHOO_BRANDS, help="Brand checkboxes (#JBDropdown, name=brands[])."),
        ]

    def fingerprint(self) -> list[str]:
        return [self.FORM, f"{self.FORM} input[name=keyword]", "#JCDropdown", "#JLDropdown", "#JBDropdown", "button#index-page-find-jobs"]

    def absent(self) -> list[str]:
        return ["form#collapseFilterJobs"]

    def live_options(self, soup: Any) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for key, dropdown in self.DROPDOWNS.items():
            values = [str(node.get("value") or "").strip() for node in soup.select(f"#{dropdown} input[type=checkbox]")]
            values = [v for v in values if v]
            if values:
                out[key] = values
        return out

    def steps(self, criteria: dict[str, Any], pages: int = 1) -> list[dict[str, Any]]:
        crit = self.normalise_criteria(criteria)
        form = self.FORM
        steps: list[dict[str, Any]] = [{"fill": {"css": f"{form} input[name=keyword]"}, "value": crit.get("keyword", ""), "force": True}]
        for key, dropdown in self.DROPDOWNS.items():
            chosen = crit.get(key) or []
            if not chosen:
                continue
            toggle = {"css": f"{form} button.{self.TOGGLES[key]}"}
            steps.append({"click": toggle, "optional": True, "force": True, "timeout_ms": 2000})
            for value in chosen:
                steps.append({"check": {"css": f"#{dropdown} input[type=checkbox][value={css_string(value)}]"}, "force": True})
            steps.append({"click": toggle, "optional": True, "force": True, "timeout_ms": 2000})
        steps += [
            {"click": {"css": f"{form} button#index-page-find-jobs"}, "force": True},  # submits: navigates to /careers/search.html
            {"wait": "load", "optional": True},
            {"wait": "networkidle", "optional": True},
            {"wait": {"css": "#tableJobListing"}, "optional": True, "timeout_ms": 10000, "settle_ms": 500},
        ]
        if pages > 1:
            steps.append({"click": {"css": "button.loadMore"}, "repeat": pages - 1, "optional": True, "force": True, "snapshot": True, "settle_ms": 800})
        return steps


STRATEGIES = (YahooCareersFormV2(), YahooCareersFormV1())
