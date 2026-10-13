"""CLI: python -m jobsearch_sources investigate <url> [--render] [--json]"""

from __future__ import annotations

import argparse
import json
import sys

from jobsearch_config import load_config

from .investigate import format_report, investigate


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m jobsearch_sources")
    sub = parser.add_subparsers(dest="command", required=True)
    inv = sub.add_parser("investigate", help="Check robots.txt, platform and search form of a careers URL.")
    inv.add_argument("url")
    inv.add_argument("--render", action="store_true", help="Also load the page in headless Chromium (needs Playwright).")
    inv.add_argument("--json", action="store_true", help="Print the report as JSON.")
    inv.add_argument("--no-record", action="store_true", help="Do not write the outcome to the site registry.")
    args = parser.parse_args(argv)
    report = investigate(args.url, load_config().search, render=args.render, record=not args.no_record)
    print(json.dumps(report.to_dict(), indent=2) if args.json else format_report(report))
    return 0 if report.verdict == "crawlable" else 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
