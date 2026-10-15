"""CLI for the search engine.

    python -m jobsearch_sources investigate <url> [--render] [--json]
    python -m jobsearch_sources forms [--site SITE_ID] [--json]        # search-form strategies / a site's form & status
    python -m jobsearch_sources test-form SITE_ID [--keyword K] [--set FIELD=VALUE ...] [--save] [--json]
    python -m jobsearch_sources setup-browser                          # install Playwright + Chromium if missing (idempotent)
    python -m jobsearch_sources compliance-scan [--no-disable] [--json]  # daily access-policy check of the configured sites
"""

from __future__ import annotations

import argparse
import json
import sys

from jobsearch_config import load_config, save_config

from .investigate import format_report, investigate


def _print_fields(strategy, criteria: dict | None = None) -> None:
    criteria = criteria or {}
    for field in strategy.fields():
        chosen = criteria.get(field.key)
        chosen_text = ", ".join(chosen) if isinstance(chosen, list) else (chosen or "")
        options = f" options: {', '.join(field.options[:10])}{'…' if len(field.options) > 10 else ''}" if field.options else ""
        print(f"  - {field.kind:11} {field.label!r:32} [{field.key}]{' = ' + chosen_text if chosen_text else ''}{options}")


def cmd_forms(args: argparse.Namespace) -> int:
    from . import searchforms as sf

    if args.site:
        config = load_config()
        site = config.get_site(args.site)
        if site is None:
            print(f"No site with id {args.site!r}.")
            return 1
        strategy = sf.configured_strategy(site.options, site.id)
        known = sf.for_url(str(site.options.get("url") or ""))
        if strategy is None and not known:
            print(f"{site.id}: no search-form strategy configured or known for {site.options.get('url')}.")
            return 2
        strategy = strategy or known[0]
        passed, status = sf.validation_status(site)
        if args.json:
            print(json.dumps({"site": site.id, "strategy": strategy.to_dict(), "validated": passed, "status": status, "criteria": (site.options.get("search_form") or {}).get("criteria")}, indent=2))
            return 0
        print(f"{site.id}: {strategy.label} ({strategy.key}, since {strategy.since or 'undated'})")
        print(f"  form: {strategy.form_hint or '-'}")
        print(f"  status: {'validated' if passed else 'not passed'} — {status}")
        print("  fields:")
        _print_fields(strategy, (site.options.get("search_form") or {}).get("criteria") or site.options.get("form_values"))
        return 0
    strategies = sf.all_strategies()
    if args.json:
        print(json.dumps([s.to_dict() for s in strategies], indent=2))
        return 0
    for family, versions in sf.families().items():
        print(f"{family}: {versions[0].label}  hosts: {', '.join(versions[0].hosts) or '-'}")
        for strategy in versions:
            print(f"  {strategy.key:24} since {strategy.since or 'undated':8} {strategy.form_hint}")
        print("  fields:")
        _print_fields(versions[0])
    return 0


def cmd_test_form(args: argparse.Namespace) -> int:
    from . import searchforms as sf

    config = load_config()
    site = config.get_site(args.site)
    if site is None:
        print(f"No site with id {args.site!r}.")
        return 1
    strategy = sf.configured_strategy(site.options, site.id)
    if strategy is None:
        known = sf.for_url(str(site.options.get("url") or ""))
        if not known:
            print(f"{site.id}: no search-form strategy configured or known for its URL.")
            return 2
        strategy = known[0]
        site.options = sf.form_site_options(strategy, str(site.options.get("url") or ""))
    block = site.options.get("search_form") if isinstance(site.options.get("search_form"), dict) else {}
    criteria = dict(block.get("criteria") or site.options.get("form_values") or {})
    if args.keyword is not None:
        criteria["keyword"] = args.keyword
    for item in args.set or []:
        key, _, value = item.partition("=")
        field = strategy.field(key.strip())
        if field is None:
            print(f"Unknown field {key!r}; fields: {', '.join(f.key for f in strategy.fields())}")
            return 1
        criteria[key.strip()] = [v.strip() for v in value.split(",") if v.strip()] if field.kind == "multiselect" else value.strip()
    test = sf.test_form(site, config, criteria)
    if args.json:
        print(json.dumps({"ok": test.ok, "matched": test.matched, "changed": test.changed, "error": test.error, "total": test.total,
                          "unknown_choices": test.unknown_choices, "criteria": test.criteria, "jobs": [j.to_dict() for j in test.jobs]}, indent=2))
    else:
        print(f"{site.id}: {'PASSED' if test.ok else 'FAILED'} — {test.summary()}")
        if test.changed:
            print(f"  note: the live form matched {test.matched}, not the configured {test.configured}")
        for problem in test.unknown_choices:
            print(f"  warning: {problem}")
        if test.notes:
            print(f"  {test.notes}")
        for job in test.jobs[:20]:
            print(f"  - {job.title} | {job.organization} | {job.location} | {job.url}")
    if args.save:
        if not test.ok:
            print("Not saved: a search-form site is only enabled after a test returns jobs.")
            return 2
        sf.mark_validated(site, test)
        site.enabled = True
        config.upsert_site(site)
        save_config(config)
        print(f"Saved criteria and validation for {site.id}; the site is enabled.")
    return 0 if test.ok else 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m jobsearch_sources")
    sub = parser.add_subparsers(dest="command", required=True)
    inv = sub.add_parser("investigate", help="Check robots.txt, platform and search form of a careers URL.")
    inv.add_argument("url")
    inv.add_argument("--render", action="store_true", help="Also load the page in headless Chromium (needs Playwright).")
    inv.add_argument("--json", action="store_true", help="Print the report as JSON.")
    inv.add_argument("--no-record", action="store_true", help="Do not write the outcome to the site registry.")
    forms = sub.add_parser("forms", help="List the search-form strategies (or a site's form, criteria and validation status).")
    forms.add_argument("--site", help="Site id from the configuration.")
    forms.add_argument("--json", action="store_true")
    test = sub.add_parser("test-form", help="Fill in a site's search form live and list the jobs it returns.")
    test.add_argument("site", help="Site id from the configuration.")
    test.add_argument("--keyword", help="Keyword to type (default: the saved criteria's keyword).")
    test.add_argument("--set", action="append", metavar="FIELD=VALUE", help="Set a field, e.g. --set countries='United States,Canada'.")
    test.add_argument("--save", action="store_true", help="On success, save the criteria + validation and enable the site.")
    test.add_argument("--json", action="store_true")
    sub.add_parser("setup-browser", help="Install the 'playwright' package and its Chromium build if they are missing (idempotent).")
    scan = sub.add_parser("compliance-scan", help="Re-check every custom/platform site against robots.txt, HTTP access and the registry policy; disable offenders.")
    scan.add_argument("--no-disable", action="store_true", help="Report only; do not disable non-compliant sites.")
    scan.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "compliance-scan":
        from .compliance import scan as run_scan

        report = run_scan(load_config(), disable=not args.no_disable)
        if args.json:
            print(json.dumps(report.to_dict(), indent=2))
        else:
            print(f"Compliance scan {report.checked_at}: {report.summary()}")
            for result in report.results:
                state = "ok" if result.compliant else ("NON-COMPLIANT" if result.compliant is False else "unknown")
                print(f"  - {result.site_id:24} {state:14} {result.message}" + (" [disabled]" if result.disabled else ""))
        return 0 if not report.non_compliant else 2
    if args.command == "setup-browser":
        from .browser import ensure_installed

        ok, reason = ensure_installed(log=print, force=True)
        print("Headless browser ready." if ok else f"Headless browser NOT ready: {reason}")
        return 0 if ok else 1
    if args.command == "forms":
        return cmd_forms(args)
    if args.command == "test-form":
        return cmd_test_form(args)
    report = investigate(args.url, load_config().search, render=args.render, record=not args.no_record)
    print(json.dumps(report.to_dict(), indent=2) if args.json else format_report(report))
    return 0 if report.verdict == "crawlable" else 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
