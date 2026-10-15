#!/usr/bin/env bash
# Start the main (operation) dashboard. Usage: scripts/run_app.sh [port]
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f .env ] && set -a && . ./.env && set +a
PY="${PYTHON:-python}"
"$PY" -c "import streamlit, pandas, bs4" 2>/dev/null || "$PY" -m pip install -r requirements.txt
"$PY" -m jobsearch_sources setup-browser || echo "warning: headless browser not available; web-form sites will not work until it is"
exec "$PY" -m streamlit run app.py --server.port "${1:-8501}"
