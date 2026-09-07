#!/usr/bin/env bash
#
# bootstrap-mac.sh — copy InfoBhoomi off the USB drive onto the Mac's internal
# disk, leaving behind everything that is Windows-built or regenerable.
#
# Why copy at all: USB sticks are almost always exFAT, which has no symlinks,
# no executable permission bit and no case sensitivity. npm needs symlinks for
# node_modules/.bin, and Python venvs need the exec bit. Both break on exFAT.
#
#   Usage:  ./mac/bootstrap-mac.sh [destination]
#   Default destination: ~/Projects/InfoBhoomi
#
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

require_macos

DEST="${1:-$HOME/Projects/InfoBhoomi}"

step "Copying project"
echo "  from: $PROJECT_ROOT"
echo "  to:   $DEST"
echo

if [ "$PROJECT_ROOT" = "$DEST" ]; then
  die "Source and destination are the same directory."
fi

if [ -e "$DEST" ] && [ -n "$(ls -A "$DEST" 2>/dev/null)" ]; then
  warn "$DEST already exists and is not empty."
  read -r -p "  Sync into it anyway (existing files may be overwritten)? [y/N] " reply
  case "$reply" in [Yy]*) ;; *) die "Aborted." ;; esac
fi

mkdir -p "$DEST"

# Excluded on purpose:
#   venv/, node_modules/, .angular/, dist/  -> Windows binaries, rebuilt by setup-mac.sh
#   __pycache__/, *.pyc                     -> Windows bytecode
#   .DS_Store, Thumbs.db, ~$*               -> OS/Office junk
#   venv.zip, *.whl                         -> Windows GDAL wheel and venv archive
#   repomix-output*.xml                     -> generated context dumps
#   *.log                                   -> old Windows run logs
command -v rsync >/dev/null 2>&1 || die "rsync not found on PATH."

# macOS ships Apple's rsync 2.6.9 / openrsync, neither of which understands
# --info=progress2 or --human-readable. Only ask for those on GNU rsync 3.x
# (which you get from `brew install rsync`).
RSYNC_FLAGS="-a"
if rsync --version 2>/dev/null | head -1 | grep -q 'version 3'; then
  RSYNC_FLAGS="$RSYNC_FLAGS --info=progress2 --human-readable"
  ok "GNU rsync 3.x detected"
else
  RSYNC_FLAGS="$RSYNC_FLAGS --progress"
  ok "Apple rsync detected — using portable flags"
fi

# --exclude=pattern (with '=') is the form every rsync variant accepts.
# shellcheck disable=SC2086
rsync $RSYNC_FLAGS \
  --exclude='venv/' \
  --exclude='node_modules/' \
  --exclude='.angular/' \
  --exclude='dist/' \
  --exclude='__pycache__/' \
  --exclude='*.pyc' \
  --exclude='*.pyo' \
  --exclude='.DS_Store' \
  --exclude='Thumbs.db' \
  --exclude='~$*' \
  --exclude='venv.zip' \
  --exclude='*.whl' \
  --exclude='repomix-output*.xml' \
  --exclude='*.log' \
  --exclude='.perf_fix_backup_*/' \
  "$PROJECT_ROOT"/ "$DEST"/

ok "Files copied."

# Apple's rsync is a different implementation from GNU's, so verify rather than
# assume: confirm the pieces we need arrived and that the Windows build output
# really was excluded.
step "Verifying the copy"
for required in mac/setup-mac.sh InfoBhoomi_Backend_dev2/manage.py \
                infoBhoomi-frontedend-div2/package.json 3D-Cadastre/package.json; do
  [ -e "$DEST/$required" ] || die "Copy incomplete — $required is missing from $DEST"
done
ok "Backend, frontend, 3D and mac/ all present"

_leaked=0
for junk in InfoBhoomi_Backend_dev2/venv infoBhoomi-frontedend-div2/node_modules \
            3D-Cadastre/node_modules; do
  if [ -e "$DEST/$junk" ]; then
    warn "Windows build output slipped through: $junk — removing"
    rm -rf "${DEST:?}/$junk"
    _leaked=1
  fi
done
[ "$_leaked" -eq 0 ] && ok "No Windows build output copied"

# rsync preserves the source's permission bits, which on exFAT are all 777 or
# all 700 and meaningless. Reset them to something sane.
step "Fixing permissions"
find "$DEST" -type d -exec chmod 755 {} + 2>/dev/null || true
find "$DEST" -type f -exec chmod 644 {} + 2>/dev/null || true
chmod +x "$DEST"/mac/*.sh
ok "Permissions normalised, mac/*.sh made executable."

# The Windows Claude Code allowlists are full of C:\ paths and venv/Scripts
# entries that mean nothing on macOS. Park them rather than delete.
step "Parking Windows-only tool config"
_parked=0
for cfg in "$DEST/.claude/settings.local.json" \
           "$DEST/InfoBhoomi_Backend_dev2/.claude/settings.local.json" \
           "$DEST/infoBhoomi-frontedend-div2/.claude/settings.local.json"; do
  if [ -f "$cfg" ]; then
    mv "$cfg" "$cfg.windows.bak"
    ok "Parked ${cfg#$DEST/}"
    _parked=$((_parked+1))
  fi
done
[ "$_parked" -gt 0 ] || ok "Nothing to park"

cat <<NEXT

$C_BOLD Done. $C_RESET Project now lives at:

    $DEST

Next:

    cd "$DEST"
    ./mac/setup-mac.sh

NEXT
