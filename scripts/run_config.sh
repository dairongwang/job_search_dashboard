#!/usr/bin/env bash
# Start the configuration dashboard. Usage: scripts/run_config.sh [port]
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f .env ] && set -a && . ./.env && set +a
PY="${PYTHON:-python}"
"$PY" -c "import streamlit, bs4" 2>/dev/null || "$PY" -m pip install -r requirements-config.txt
"$PY" -m jobsearch_sources setup-browser || echo "warning: headless browser not available; 'Find jobs' tests of web-form sites will not work until it is"
exec "$PY" -m streamlit run config_dashboard.py --server.port "${1:-8502}"
