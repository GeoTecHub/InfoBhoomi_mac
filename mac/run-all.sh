#!/usr/bin/env bash
#
# run-all.sh — start backend, frontend and 3D Cadastre together.
# Ctrl-C stops all three. Logs are interleaved and prefixed.
#
set -uo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"
set +e

# Job control gives every background job its own process group, so a single
# kill on the negated group id takes down `ng serve`/`runserver` and the `sed`
# that prefixes their output — not just the sed at the end of the pipe.
set -m

PGIDS=""

cleanup() {
  trap - EXIT INT TERM
  printf '\n'
  step "Shutting down"
  for pgid in $PGIDS; do
    kill -TERM "-$pgid" 2>/dev/null
  done
  sleep 2
  for pgid in $PGIDS; do
    kill -KILL "-$pgid" 2>/dev/null
  done
  ok "All processes stopped"
  exit 0
}
trap cleanup EXIT INT TERM

launch() {
  local label="$1"; shift
  { "$@" 2>&1 | sed "s/^/[$label] /"; } &
  PGIDS="$PGIDS $!"          # with `set -m`, $! is also the new process group id
}

step "Starting the InfoBhoomi stack"
echo "  backend   http://localhost:8000"
echo "  frontend  http://localhost:4200"
echo "  3d        http://localhost:5175"
echo "  (Ctrl-C stops everything)"
echo

launch "backend " "$MAC_DIR/run-backend.sh"
sleep 3
launch "frontend" "$MAC_DIR/run-frontend.sh"
launch "3d      " "$MAC_DIR/run-3d.sh"

wait
