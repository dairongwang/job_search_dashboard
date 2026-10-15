"""Command-line interface for the configuration.

Useful for deployment scripts, CI checks and headless servers where the
Streamlit configuration dashboard is not running::

    python -m jobsearch_config path
    python -m jobsearch_config init [--force]
    python -m jobsearch_config show
    python -m jobsearch_config validate
    python -m jobsearch_config sites
    python -m jobsearch_config enable remotive jobicy
    python -m jobsearch_config disable remoteok
    python -m jobsearch_config set-pref titles "data analyst, BI analyst"
    python -m jobsearch_config set-pref salary.minimum 80000
    python -m jobsearch_config import other.json
    python -m jobsearch_config export > backup.json
    python -m jobsearch_config web-search [on|off] [--admin-token T]   # administrator switch for web-page search
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import store
from .catalog import PROVIDERS
from .schema import JobPreferences, SalaryRange
from .validate import has_errors, validate


def _print_issues(issues) -> None:
    for issue in issues:
        print(str(issue))


def cmd_path(args: argparse.Namespace) -> int:
    print(store.config_path(args.config))
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    target = store.config_path(args.config)
    if target.exists() and not args.force:
        print(f"{target} already exists (use --force to overwrite).")
        return 1
    store.save_config(store.default_config(), target)
    print(f"Wrote defaults to {target}")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    config = store.load_config(args.config)
    print(store.dumps(config))
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    target = store.config_path(args.config)
    if not target.exists():
        print(f"No config at {target}; defaults would be used.")
    config = store.load_config(args.config)
    issues = validate(config)
    _print_issues(issues)
    if has_errors(issues):
        print("Configuration has errors.")
        return 2
    print(f"OK — {len(config.enabled_sites())} of {len(config.sites)} sites enabled, {len(issues)} warning(s).")
    return 0


def cmd_sites(args: argparse.Namespace) -> int:
    config = store.load_config(args.config)
    width = max([len(s.id) for s in config.sites] + [4])
    print(f"{'id'.ljust(width)}  on  provider    max  name")
    for site in config.sites:
        flag = "yes" if site.enabled else "no "
        print(f"{site.id.ljust(width)}  {flag} {site.provider.ljust(10)} {str(site.max_results).rjust(4)}  {site.name}")
    return 0


def _toggle(args: argparse.Namespace, enabled: bool) -> int:
    config = store.load_config(args.config)
    missing = [sid for sid in args.site_ids if config.get_site(sid) is None]
    if missing:
        print(f"Unknown site id(s): {', '.join(missing)}")
        return 1
    for sid in args.site_ids:
        config.get_site(sid).enabled = enabled
    store.save_config(config, args.config)
    print(f"{'Enabled' if enabled else 'Disabled'}: {', '.join(args.site_ids)}")
    return 0


def cmd_enable(args: argparse.Namespace) -> int:
    return _toggle(args, True)


def cmd_disable(args: argparse.Namespace) -> int:
    return _toggle(args, False)


def cmd_providers(args: argparse.Namespace) -> int:
    for spec in PROVIDERS.values():
        tag = "custom" if spec.custom else ("needs key" if spec.requires_key else "no key")
        print(f"{spec.key.ljust(10)} {spec.label.ljust(18)} [{tag}] {spec.description}")
    return 0


def cmd_web_search(args: argparse.Namespace) -> int:
    from . import admin

    config = store.load_config(args.config)
    if not args.state:
        allowed, why = admin.web_page_search_allowed(config)
        print(f"web-page search: {'ON' if allowed else 'OFF'} — {why}")
        print(f"administrator token configured in this process: {'yes' if admin.admin_configured() else 'no (set ' + admin.ENV_ADMIN_TOKEN + ')'}")
        return 0
    token = args.admin_token if args.admin_token is not None else admin.admin_token()
    try:
        admin.set_web_page_search(config, args.state == "on", token)
    except admin.AdminRequired as exc:
        print(f"Refused: {exc}")
        return 3
    store.save_config(config, args.config)
    print(f"web-page search switched {args.state.upper()} by the administrator ({config.search.web_page_search_changed_at}).")
    return 0


def cmd_set_pref(args: argparse.Namespace) -> int:
    config = store.load_config(args.config)
    prefs = config.preferences
    key, value = args.key, args.value
    try:
        if key.startswith("salary."):
            field = key.split(".", 1)[1]
            if field not in SalaryRange.__dataclass_fields__:
                raise KeyError(key)
            data = dict(prefs.salary.__dict__)
            data[field] = value if field in {"currency", "period"} else (value.lower() == "true" if field == "include_unlisted" else value)
            prefs.salary = SalaryRange.from_dict(data)
        elif key in JobPreferences.__dataclass_fields__:
            data = dict(prefs.__dict__)
            if isinstance(data[key], list):
                data[key] = value
            elif isinstance(data[key], bool):
                data[key] = value.lower() in {"1", "true", "yes", "on"}
            else:
                data[key] = value
            config.preferences = JobPreferences.from_dict(data)
        else:
            raise KeyError(key)
    except KeyError:
        print(f"Unknown preference '{key}'. Valid keys: {', '.join(JobPreferences.__dataclass_fields__)} or salary.<field>.")
        return 1
    issues = validate(config)
    _print_issues(issues)
    if has_errors(issues):
        return 2
    store.save_config(config, args.config)
    print(f"Set {key}.")
    return 0


def cmd_import(args: argparse.Namespace) -> int:
    text = Path(args.file).read_text(encoding="utf-8")
    config = store.loads(text)
    issues = validate(config)
    _print_issues(issues)
    if has_errors(issues) and not args.force:
        print("Refusing to import a configuration with errors (use --force).")
        return 2
    target = store.save_config(config, args.config)
    print(f"Imported into {target}")
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    print(store.dumps(store.load_config(args.config)))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m jobsearch_config", description="Manage the job search configuration.")
    parser.add_argument("--config", "-c", help=f"Config file path (default: ${store.ENV_PATH_VAR} or config/{store.DEFAULT_FILENAME}).")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("path", help="Print the resolved config path.").set_defaults(func=cmd_path)
    p = sub.add_parser("init", help="Write a default config file.")
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_init)
    sub.add_parser("show", help="Print the effective config as JSON.").set_defaults(func=cmd_show)
    sub.add_parser("validate", help="Validate the config; exit 2 on errors.").set_defaults(func=cmd_validate)
    sub.add_parser("sites", help="List configured sites.").set_defaults(func=cmd_sites)
    sub.add_parser("providers", help="List available provider adapters.").set_defaults(func=cmd_providers)
    p = sub.add_parser("enable", help="Enable site(s) by id.")
    p.add_argument("site_ids", nargs="+")
    p.set_defaults(func=cmd_enable)
    p = sub.add_parser("disable", help="Disable site(s) by id.")
    p.add_argument("site_ids", nargs="+")
    p.set_defaults(func=cmd_disable)
    p = sub.add_parser("set-pref", help="Set a preference (lists are comma separated).")
    p.add_argument("key")
    p.add_argument("value")
    p.set_defaults(func=cmd_set_pref)
    p = sub.add_parser("import", help="Replace the config with a JSON file.")
    p.add_argument("file")
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_import)
    sub.add_parser("export", help="Print the config JSON (for backups).").set_defaults(func=cmd_export)
    p = sub.add_parser("web-search", help="Show or change the administrator switch for web-page based search.")
    p.add_argument("state", nargs="?", choices=["on", "off"], help="Omit to show the current state.")
    p.add_argument("--admin-token", default=None, help="Administrator token (default: the JOB_SEARCH_ADMIN_TOKEN environment variable).")
    p.set_defaults(func=cmd_web_search)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
