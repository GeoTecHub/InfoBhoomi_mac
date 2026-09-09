#!/usr/bin/env bash
#
# run-3d.sh — 3D Cadastre Angular app.
#   Usage: ./mac/run-3d.sh [port] [--remote]     (default port 5175)
#
# The app calls relative '/api/...' URLs and relies on the dev-server proxy to
# reach the backend. By default this script proxies to your LOCAL Django server
# (proxy.conf.local.json). Pass --remote to proxy to infobhoomiback.geoinfobox.com
# instead (the committed proxy.conf.json).
#
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

PORT="5175"
PROXY="proxy.conf.local.json"
for arg in "$@"; do
  case "$arg" in
    --remote) PROXY="proxy.conf.json" ;;
    *[!0-9]*) die "Unknown option: $arg" ;;
    *)        PORT="$arg" ;;
  esac
done

[ -d "$CADASTRE_DIR/node_modules" ] || die "node_modules missing. Run ./mac/setup-mac.sh first."

load_brew
cd "$CADASTRE_DIR"
[ -f "$PROXY" ] || die "Proxy config not found: $CADASTRE_DIR/$PROXY"

step "3D Cadastre on http://localhost:$PORT"
echo "  proxy: $PROXY -> $(python3 -c "import json,sys;print(json.load(open('$PROXY'))['/api']['target'])" 2>/dev/null || echo '?')"
echo
exec npx ng serve --port "$PORT" --proxy-config "$PROXY"
