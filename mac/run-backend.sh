#!/usr/bin/env bash
#
# run-backend.sh — Django dev server.
#   Usage: ./mac/run-backend.sh [port]     (default 8000)
#
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

PORT="${1:-8000}"

[ -x "$VENV_PY" ] || die "Backend venv missing. Run ./mac/setup-mac.sh first."

load_brew
add_pg_to_path

cd "$BACKEND_DIR"
step "Django dev server on http://localhost:$PORT"
echo "  settings : infobhoomi.settings"
echo "  python   : $("$VENV_PY" -V)"
echo
exec "$VENV_PY" manage.py runserver "0.0.0.0:$PORT"
