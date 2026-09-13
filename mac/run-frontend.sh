#!/usr/bin/env bash
#
# run-frontend.sh — Angular 21 main app (infoBhoomi-frontedend-div2).
#   Usage: ./mac/run-frontend.sh [port]    (default 4200)
#
# The app talks to the backend directly via environments/environment.ts
# (API_URL = http://localhost:8000/api/user/), so no dev proxy is required.
#
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

PORT="${1:-4200}"

[ -d "$FRONTEND_DIR/node_modules" ] || die "node_modules missing. Run ./mac/setup-mac.sh first."

load_brew
cd "$FRONTEND_DIR"
step "Angular dev server on http://localhost:$PORT"
exec npx ng serve --no-hmr --port "$PORT"
