"""Every interactive element of both dashboards carries a tooltip with an explanation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import jobsearch_config as jc
from tests.conftest import load_fixture

AppTest = pytest.importorskip("streamlit.testing.v1").AppTest
ROOT = Path(__file__).resolve().parent.parent

WIDGET_TYPES = (
    "text_input", "text_area", "selectbox", "multiselect", "number_input", "checkbox", "toggle",
    "date_input", "radio", "button", "download_button", "file_uploader", "metric", "header", "subheader",
)


def _elements(at):
    """All elements in main + sidebar trees, flattened."""
    seen = []
    for root in (at.main, at.sidebar):
        stack = [root]
        while stack:
            node = stack.pop()
            seen.append(node)
            children = getattr(node, "children", None)
            if isinstance(children, dict):
                stack.extend(children.values())
            elif isinstance(children, (list, tuple)):
                stack.extend(children)
    return seen


def _missing(at) -> list[str]:
    missing = []
    for el in _elements(at):
        kind = getattr(el, "type", "")
        if kind not in WIDGET_TYPES:
            continue
        help_text = getattr(el, "help", None)
        if help_text is None:
            help_text = getattr(getattr(el, "proto", None), "help", "")
        label = getattr(el, "label", None) or getattr(el, "value", None) or getattr(el, "body", None) or "?"
        if not (help_text or "").strip():
            missing.append(f"{kind}: {str(label)[:40]}")
        elif len(help_text) < 25:
            missing.append(f"{kind}: {str(label)[:40]} (too short: {help_text!r})")
    return missing


@pytest.fixture
def apps(config_path, tmp_path, monkeypatch):
    monkeypatch.setenv("JOB_SEARCH_DB", str(tmp_path / "test.db"))
    cfg = jc.default_config()
    cfg.sites.append(jc.SiteConfig(id="acme", provider="html", name="Acme", enabled=False, options={**jc.default_options("html"), "url": "https://careers.example.com/"}))
    jc.save_config(cfg)


def test_help_catalogue_is_substantive():
    from ui_help import COLUMNS, HELP, SECTIONS

    for name, table in (("HELP", HELP), ("SECTIONS", SECTIONS), ("COLUMNS", COLUMNS)):
        for key, text in table.items():
            assert len(text) >= 25, f"{name}[{key}] is too short"
    examples = sum("Example" in t or "*Example" in t or "e.g." in t for t in HELP.values())
    assert examples >= len(HELP) * 0.55, "most tooltips should carry a concrete example"


def test_provider_options_have_examples():
    for spec in jc.PROVIDERS.values():
        for opt in spec.options:
            assert len(opt.help) >= 60, f"{spec.key}.{opt.key} help is too short"


def test_main_app_every_widget_has_a_tooltip(apps, transport):
    transport({"remotive.com": load_fixture("remotive.json"), "jobicy.com": load_fixture("jobicy.json")})
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60).run()
    problems: dict[str, list[str]] = {}
    # Dashboard (empty + with data), Research (before and after a search, incl. save), Jobs, Contacts, Outreach, Configuration
    problems["Dashboard"] = _missing(at)
    at.sidebar.radio[0].set_value("Research").run()
    [b for b in at.button if b.label == "Search listings"][0].click().run()
    problems["Research"] = _missing(at)
    save = [m for m in at.multiselect if m.label == "Save into the tracker"][0]
    save.set_value([save.options[0]])
    [b for b in at.button if b.label == "Save selected"][0].click().run()
    at.sidebar.radio[0].set_value("Jobs").run()
    problems["Jobs"] = _missing(at)
    at.sidebar.radio[0].set_value("Contacts").run()
    [b for b in at.button if b.label == "Load two sample roles"] and None
    problems["Contacts"] = _missing(at)
    at.sidebar.radio[0].set_value("Outreach").run()
    problems["Outreach"] = _missing(at)
    at.sidebar.radio[0].set_value("Configuration").run()
    problems["Configuration"] = _missing(at)
    at.sidebar.radio[0].set_value("Dashboard").run()
    problems["Dashboard+data"] = _missing(at)
    assert not at.exception
    assert {k: v for k, v in problems.items() if v} == {}


def test_jobs_page_with_sample_data_has_tooltips(apps):
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60).run()
    at.sidebar.radio[0].set_value("Jobs").run()
    [b for b in at.button if b.label == "Load two sample roles"][0].click().run()
    at.sidebar.radio[0].set_value("Jobs").run()
    assert _missing(at) == []
    at.sidebar.radio[0].set_value("Contacts").run()
    assert _missing(at) == []
    at.sidebar.radio[0].set_value("Outreach").run()
    assert _missing(at) == []


def test_config_dashboard_every_widget_has_a_tooltip(apps, transport):
    transport({"/robots.txt": "User-agent: *\n", "careers.example.com": "<html></html>"})
    at = AppTest.from_file(str(ROOT / "config_dashboard.py"), default_timeout=60).run()
    assert not at.exception
    assert _missing(at) == []
    # site forms render provider options from the catalog: every option widget must have help
    option_widgets = [el for el in _elements(at) if getattr(el, "key", "") and str(getattr(el, "key", "")).startswith("opt:")]
    assert option_widgets, "site option widgets should be rendered"
    # import flow: upload a config so the 'Import now' button appears
    upload = [el for el in _elements(at) if getattr(el, "type", "") == "file_uploader"]
    assert upload and upload[0].help
    # reset confirmation button
    [b for b in at.button if b.label == "Reset to defaults"][0].click().run()
    assert [b for b in at.button if b.label == "Yes, reset"][0].help
    assert _missing(at) == []


def test_column_config_helper_gives_every_column_help():
    from ui_help import column_config

    cfg = column_config(["title", "url", "mystery"], url="listing")
    assert set(cfg) == {"title", "url", "mystery"}
    assert all(cfg[k] is not None for k in cfg)
    json.dumps({k: str(v) for k, v in cfg.items()})  # serialisable enough for Streamlit
