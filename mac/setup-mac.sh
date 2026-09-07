#!/usr/bin/env bash
#
# setup-mac.sh — install everything InfoBhoomi needs on macOS and build the
# backend virtualenv plus both Angular apps' node_modules.
#
#   Usage:  ./mac/setup-mac.sh [--skip-db] [--skip-node] [--skip-python]
#
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

SKIP_DB=0; SKIP_NODE=0; SKIP_PYTHON=0
for arg in "$@"; do
  case "$arg" in
    --skip-db)     SKIP_DB=1 ;;
    --skip-node)   SKIP_NODE=1 ;;
    --skip-python) SKIP_PYTHON=1 ;;
    -h|--help)     sed -n '2,9p' "$0"; exit 0 ;;
    *)             die "Unknown option: $arg" ;;
  esac
done

require_macos
load_brew

step "Environment"
echo "  macOS      : $(sw_vers -productVersion)"
echo "  Chip       : $(uname -m)   ($([ "$(uname -m)" = arm64 ] && echo 'Apple Silicon' || echo 'Intel'))"
echo "  Homebrew   : $BREW_PREFIX"
echo "  Project    : $PROJECT_ROOT"

# A venv or node_modules on exFAT (typical for USB sticks) fails in confusing
# ways: npm cannot create node_modules/.bin symlinks and venv binaries lose the
# exec bit. Rather than guess from the filesystem name, probe for both directly.
step "Checking filesystem capabilities"
_probe="$PROJECT_ROOT/.mac-setup-probe.$$"
_fs_ok=1
if ln -s /tmp "$_probe.link" 2>/dev/null; then
  rm -f "$_probe.link"
else
  _fs_ok=0
  warn "This volume does not support symlinks (npm needs them for node_modules/.bin)."
fi
if : > "$_probe.exe" 2>/dev/null; then
  chmod +x "$_probe.exe" 2>/dev/null || true
  [ -x "$_probe.exe" ] || { _fs_ok=0; warn "This volume does not support the executable bit (Python venvs need it)."; }
  rm -f "$_probe.exe"
fi
if [ "$_fs_ok" -eq 0 ]; then
  warn "Looks like exFAT/FAT — probably a USB drive. Copy to the internal disk first:"
  warn "    ./mac/bootstrap-mac.sh"
  read -r -p "  Continue anyway? [y/N] " reply
  case "$reply" in [Yy]*) ;; *) exit 1 ;; esac
else
  ok "Symlinks and exec bit both work here"
fi

# ---------------------------------------------------------------------------
# 1. System libraries
# ---------------------------------------------------------------------------
step "Homebrew packages"
brew_ensure geos
brew_ensure proj
brew_ensure gdal
[ "$SKIP_DB" -eq 1 ] || brew_ensure "$PG_FORMULA"
[ "$SKIP_DB" -eq 1 ] || brew_ensure postgis
brew_ensure node

add_pg_to_path

# Confirm Django will be able to find the libraries settings.py looks for.
step "Verifying GDAL / GEOS"
GDAL_LIB="$(ls "$BREW_PREFIX"/lib/libgdal.dylib "$BREW_PREFIX"/lib/libgdal.*.dylib 2>/dev/null | head -1 || true)"
GEOS_LIB="$(ls "$BREW_PREFIX"/lib/libgeos_c.dylib "$BREW_PREFIX"/lib/libgeos_c.*.dylib 2>/dev/null | head -1 || true)"
[ -n "$GDAL_LIB" ] || die "libgdal.dylib not found under $BREW_PREFIX/lib — try: brew reinstall gdal"
[ -n "$GEOS_LIB" ] || die "libgeos_c.dylib not found under $BREW_PREFIX/lib — try: brew reinstall geos"
ok "GDAL: $GDAL_LIB"
ok "GEOS: $GEOS_LIB"

# ---------------------------------------------------------------------------
# 2. Python virtualenv
# ---------------------------------------------------------------------------
if [ "$SKIP_PYTHON" -eq 0 ]; then
  step "Python virtualenv"

  # Django 5.1 supports 3.10–3.13. Prefer 3.12: widest wheel coverage for
  # numpy/shapely/ifcopenshell on arm64.
  PYTHON_BIN=""
  for candidate in python3.12 python3.13 python3.11; do
    if command -v "$candidate" >/dev/null 2>&1; then PYTHON_BIN="$candidate"; break; fi
  done
  if [ -z "$PYTHON_BIN" ]; then
    brew_ensure python@3.12
    PYTHON_BIN="$BREW_PREFIX/opt/python@3.12/bin/python3.12"
  fi
  ok "Using $($PYTHON_BIN -V) at $(command -v "$PYTHON_BIN" || echo "$PYTHON_BIN")"

  # A venv copied from Windows has Scripts/ instead of bin/ and .exe shims.
  if [ -d "$VENV_DIR" ] && [ ! -x "$VENV_PY" ]; then
    warn "Existing venv is not a macOS venv (no bin/python). Replacing it."
    mv "$VENV_DIR" "$VENV_DIR.windows.bak.$(date +%s)"
  fi

  if [ ! -x "$VENV_PY" ]; then
    "$PYTHON_BIN" -m venv "$VENV_DIR"
    ok "Created $VENV_DIR"
  else
    ok "Reusing existing venv"
  fi

  "$VENV_PY" -m pip install --upgrade pip wheel setuptools >/dev/null
  step "Installing backend requirements"
  "$VENV_PIP" install -r "$BACKEND_DIR/requirements.txt"
  ok "Backend requirements installed"

  # ifcopenshell is kept separate: its wheels lag new Python versions, and a
  # failure there should not take the whole backend down with it.
  step "Installing optional IFC support"
  if "$VENV_PIP" install -r "$BACKEND_DIR/requirements-ifc.txt"; then
    ok "ifcopenshell installed — IFC import endpoints available"
  else
    warn "ifcopenshell could not be installed on $($VENV_PY -V)."
    warn "Everything except the IFC -> CityJSON import will still work."
  fi

  step "Django system check"
  if (cd "$BACKEND_DIR" && "$VENV_PY" manage.py check); then
    ok "Django check passed"
  else
    warn "Django check failed — usually the database is not up yet."
    warn "Run ./mac/setup-db.sh, then re-run this check."
  fi
fi

# ---------------------------------------------------------------------------
# 3. Node dependencies
# ---------------------------------------------------------------------------
if [ "$SKIP_NODE" -eq 0 ]; then
  step "Node.js"
  NODE_MAJOR="$(node -p 'process.versions.node.split(".")[0]')"
  ok "node $(node -v), npm $(npm -v)"
  if [ "$NODE_MAJOR" -lt 20 ]; then
    die "Angular 21 needs Node 20.19+, 22.12+ or 24+. Upgrade with: brew upgrade node"
  fi

  install_node_app() {
    local dir="$1" label="$2"
    [ -d "$dir" ] || { warn "$label not found at $dir — skipping"; return; }
    step "npm install — $label"
    # node_modules carried over from Windows contains win32 esbuild/rollup
    # binaries that abort on macOS. Always start clean.
    if [ -d "$dir/node_modules" ]; then
      rm -rf "$dir/node_modules"
      ok "Removed stale node_modules"
    fi
    rm -rf "$dir/.angular"
    if [ -f "$dir/package-lock.json" ]; then
      (cd "$dir" && npm ci) || (cd "$dir" && npm install)
    else
      (cd "$dir" && npm install)
    fi
    ok "$label dependencies installed"
  }

  install_node_app "$FRONTEND_DIR" "Frontend (infoBhoomi-frontedend-div2)"
  install_node_app "$CADASTRE_DIR" "3D Cadastre"
fi

# ---------------------------------------------------------------------------
# 4. Database
# ---------------------------------------------------------------------------
if [ "$SKIP_DB" -eq 0 ]; then
  step "Database"
  echo "  Homebrew's $PG_FORMULA and postgis are installed."
  echo "  Creating the role, database and extensions is a separate step:"
  echo
  echo "      ./mac/setup-db.sh"
  echo
fi

cat <<NEXT

$C_BOLD Setup complete. $C_RESET

  1. Database (once):   ./mac/setup-db.sh
  2. Backend:           ./mac/run-backend.sh     -> http://localhost:8000
  3. Frontend:          ./mac/run-frontend.sh    -> http://localhost:4200
  4. 3D Cadastre:       ./mac/run-3d.sh          -> http://localhost:5175

  Or all three at once: ./mac/run-all.sh

NEXT
