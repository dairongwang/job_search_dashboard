#!/usr/bin/env bash
# Start the configuration dashboard. Usage: scripts/run_config.sh [port]
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f .env ] && set -a && . ./.env && set +a
exec streamlit run config_dashboard.py --server.port "${1:-8502}"
