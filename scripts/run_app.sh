#!/usr/bin/env bash
# Start the main (operation) dashboard. Usage: scripts/run_app.sh [port]
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f .env ] && set -a && . ./.env && set +a
exec streamlit run app.py --server.port "${1:-8501}"
