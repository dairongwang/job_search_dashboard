"""Load / save the configuration file.

The configuration is a single JSON document. Where it lives is decided by, in
order of precedence:

1. an explicit ``path`` argument,
2. the ``JOB_SEARCH_CONFIG`` environment variable,
3. ``<project>/config/job_search_config.json``.

This makes the same file editable by the configuration dashboard, by hand,
by the CLI, or provisioned at deployment time (e.g. mounted into a container).
Writes are atomic (temp file + rename) and keep one ``.bak`` copy.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

from .defaults import default_config
from .schema import AppConfig

ENV_PATH_VAR = "JOB_SEARCH_CONFIG"
DEFAULT_FILENAME = "job_search_config.json"
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DIR = PROJECT_ROOT / "config"

_ENV_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def config_path(path: str | os.PathLike[str] | None = None) -> Path:
    """Resolve the configuration file path (see module docstring)."""
    if path:
        return Path(path).expanduser().resolve()
    env = os.environ.get(ENV_PATH_VAR)
    if env:
        return Path(env).expanduser().resolve()
    return (DEFAULT_DIR / DEFAULT_FILENAME).resolve()


def exists(path: str | os.PathLike[str] | None = None) -> bool:
    return config_path(path).is_file()


def load_config(path: str | os.PathLike[str] | None = None, *, create: bool = False) -> AppConfig:
    """Read the config file; fall back to defaults if it does not exist.

    ``create=True`` writes the defaults to disk when the file is missing, so a
    fresh deployment self-initialises on first launch.
    """
    target = config_path(path)
    if not target.is_file():
        config = default_config()
        if create:
            save_config(config, target)
        return config
    with target.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)
    if not isinstance(raw, dict):
        raise ValueError(f"{target} does not contain a JSON object.")
    return AppConfig.from_dict(raw)


def save_config(config: AppConfig, path: str | os.PathLike[str] | None = None) -> Path:
    """Atomically write the config; returns the path written."""
    target = config_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    config.touch()
    payload = json.dumps(config.to_dict(), indent=2, ensure_ascii=False) + "\n"
    if target.exists():
        shutil.copyfile(target, target.with_suffix(target.suffix + ".bak"))
    fd, tmp_name = tempfile.mkstemp(prefix=".tmp-", suffix=".json", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
        os.replace(tmp_name, target)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
    return target


def mtime(path: str | os.PathLike[str] | None = None) -> float:
    """Modification time of the config file (0 if missing). Used for hot reload."""
    target = config_path(path)
    try:
        return target.stat().st_mtime
    except FileNotFoundError:
        return 0.0


def dumps(config: AppConfig) -> str:
    return json.dumps(config.to_dict(), indent=2, ensure_ascii=False)


def loads(text: str) -> AppConfig:
    raw = json.loads(text)
    if not isinstance(raw, dict):
        raise ValueError("Configuration must be a JSON object.")
    return AppConfig.from_dict(raw)


# ---------------------------------------------------------------------------
# Secrets
# ---------------------------------------------------------------------------


def resolve_secret(value: Any) -> str:
    """Expand ``${ENV_NAME}`` references using the process environment.

    Non-string values are returned as strings. Unset variables expand to "".
    Keeps secrets out of the JSON file so it can be committed or shared.
    """
    if value is None:
        return ""
    text = str(value)
    return _ENV_REF.sub(lambda m: os.environ.get(m.group(1), ""), text)


def resolve_options(options: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of ``options`` with ``${ENV}`` references expanded in strings (recursively)."""

    def walk(value: Any) -> Any:
        if isinstance(value, str):
            return resolve_secret(value)
        if isinstance(value, dict):
            return {k: walk(v) for k, v in value.items()}
        if isinstance(value, list):
            return [walk(v) for v in value]
        return value

    return walk(dict(options or {}))
