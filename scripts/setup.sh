#!/usr/bin/env bash
# One-time setup: Python packages for both dashboards + the headless Chromium used for web-form sites.
# Usage: scripts/setup.sh            (re-run any time; it is idempotent)
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PYTHON:-python}"
"$PY" -m pip install --upgrade pip >/dev/null
"$PY" -m pip install -r requirements.txt -r requirements-config.txt
"$PY" -m jobsearch_sources setup-browser
echo "Setup complete. Start with scripts/run_app.sh and scripts/run_config.sh"
