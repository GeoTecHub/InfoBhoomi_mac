#!/usr/bin/env bash
#
# fetch-deps.sh — download every Homebrew bottle this project needs, retrying
# until each one completes. Nothing is installed; this only fills Homebrew's
# download cache so `setup-mac.sh` afterwards runs offline-fast.
#
# Written for connections that drop mid-transfer. `proj` alone is ~800 MB
# (it bundles the full PROJ coordinate-grid dataset), and every retry resumes
# from where the last attempt stopped rather than starting over.
#
#   Usage:  ./mac/fetch-deps.sh [max-attempts-per-package]   (default 40)
#
# Safe to interrupt with Ctrl-C and re-run — progress is kept in the cache.
#
set -uo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"
set +e

require_macos
load_brew

MAX_ATTEMPTS="${1:-40}"
FORMULAE="geos proj gdal postgresql@15 postgis node"

step "Pre-downloading Homebrew bottles"
echo "  cache      : $(brew --cache)"
echo "  packages   : $FORMULAE"
echo "  attempts   : up to $MAX_ATTEMPTS each, resuming every time"
echo "  (Ctrl-C is safe — re-running continues where it stopped)"

# Force HTTP/1.1: ghcr.io's HTTP/2 is what produces the PROTOCOL_ERROR drops.
brew_force_http1
export HOMEBREW_CURL_RETRIES=10
export HOMEBREW_NO_AUTO_UPDATE=1

FAILED=""
for formula in $FORMULAE; do
  if brew_has "$formula"; then
    ok "$formula already installed — nothing to fetch"
    continue
  fi

  step "Fetching $formula"
  attempt=1
  # Log to a file rather than piping into `tail`: a pipeline's exit status is
  # the last command's, so `brew fetch | tail` would report tail's success even
  # when the download failed (pipefail would fix it, but this is unambiguous).
  # An explicit XXXXXX template works with both BSD and GNU mktemp;
  # `mktemp -t prefix` does not (GNU wants the X's in the template).
  FETCH_LOG="$(mktemp "${TMPDIR:-/tmp}/infobhoomi-fetch.XXXXXX")"
  while [ "$attempt" -le "$MAX_ATTEMPTS" ]; do
    if brew fetch --formula --retry "$formula" >"$FETCH_LOG" 2>&1; then
      ok "$formula downloaded"
      rm -f "$FETCH_LOG"
      break
    fi
    tail -3 "$FETCH_LOG" | sed 's/^/     /'
    printf '%s  attempt %d/%d failed — resuming in 5s%s\n' \
      "$C_YELLOW" "$attempt" "$MAX_ATTEMPTS" "$C_RESET"
    sleep 5
    attempt=$((attempt+1))
  done

  if [ "$attempt" -gt "$MAX_ATTEMPTS" ]; then
    warn "$formula gave up after $MAX_ATTEMPTS attempts"
    FAILED="$FAILED $formula"
    rm -f "$FETCH_LOG"
  fi
done

echo
if [ -n "$FAILED" ]; then
  warn "Not fully downloaded:$FAILED"
  warn "Re-run this script — it resumes. Or try again on a steadier connection."
  exit 1
fi

cat <<NEXT

$C_BOLD All bottles downloaded. $C_RESET  Now run the installer — it will use the
cache and should finish quickly without touching the network:

    ./mac/setup-mac.sh

NEXT
