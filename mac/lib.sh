#!/usr/bin/env bash
# Shared helpers for the InfoBhoomi macOS scripts.
# Sourced, not executed.

set -euo pipefail

# ---- pretty output ---------------------------------------------------------
if [ -t 1 ]; then
  C_RESET=$'\033[0m'; C_BOLD=$'\033[1m'; C_RED=$'\033[31m'
  C_GREEN=$'\033[32m'; C_YELLOW=$'\033[33m'; C_BLUE=$'\033[34m'
else
  C_RESET=""; C_BOLD=""; C_RED=""; C_GREEN=""; C_YELLOW=""; C_BLUE=""
fi

step() { printf '\n%s==> %s%s\n' "$C_BOLD$C_BLUE" "$*" "$C_RESET"; }
ok()   { printf '%s  ok%s %s\n' "$C_GREEN" "$C_RESET" "$*"; }
warn() { printf '%s  !!%s %s\n' "$C_YELLOW" "$C_RESET" "$*"; }
die()  { printf '\n%s  xx  %s%s\n\n' "$C_RED$C_BOLD" "$*" "$C_RESET" >&2; exit 1; }

# ---- project layout --------------------------------------------------------
# All scripts live in <project>/mac, so the project root is one level up.
MAC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$MAC_DIR/.." && pwd)"

BACKEND_DIR="$PROJECT_ROOT/InfoBhoomi_Backend_dev2"
FRONTEND_DIR="$PROJECT_ROOT/infoBhoomi-frontedend-div2"
CADASTRE_DIR="$PROJECT_ROOT/3D-Cadastre"
AGENTS_DIR="$PROJECT_ROOT/agents"

VENV_DIR="$BACKEND_DIR/venv"
VENV_PY="$VENV_DIR/bin/python"
VENV_PIP="$VENV_DIR/bin/pip"

# ---- platform sanity -------------------------------------------------------
require_macos() {
  [ "$(uname -s)" = "Darwin" ] || die "These scripts are for macOS. Detected: $(uname -s)"
}

# Homebrew is installed under /opt/homebrew on Apple Silicon and /usr/local on
# Intel. Put it on PATH for this shell if the user's profile has not.
load_brew() {
  if ! command -v brew >/dev/null 2>&1; then
    for candidate in /opt/homebrew/bin/brew /usr/local/bin/brew; do
      [ -x "$candidate" ] && eval "$("$candidate" shellenv)" && break
    done
  fi
  command -v brew >/dev/null 2>&1 || die \
"Homebrew is not installed. Install it first:

  /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\"

then re-run this script."
  BREW_PREFIX="$(brew --prefix)"
  export BREW_PREFIX

  # More curl retries than the default 3, and skip the auto-update that would
  # otherwise re-run on every retry attempt.
  export HOMEBREW_CURL_RETRIES="${HOMEBREW_CURL_RETRIES:-5}"
  export HOMEBREW_NO_AUTO_UPDATE=1
  export HOMEBREW_NO_ENV_HINTS=1
}

brew_has() { brew list --formula "$1" >/dev/null 2>&1; }

# ghcr.io (where Homebrew hosts its bottles) intermittently kills HTTP/2
# connections mid-transfer:
#   curl: (92) HTTP/2 stream 1 was not closed cleanly: PROTOCOL_ERROR
# It bites hardest on the big bottles — `proj` alone is ~800 MB because it now
# bundles the full PROJ grid dataset. Homebrew caches partial downloads and
# resumes them, so retrying is usually all that is needed. On the second
# attempt we also force HTTP/1.1, which sidesteps the protocol error entirely.
BREW_HTTP1_CURLRC="$MAC_DIR/.homebrew-curlrc"

brew_force_http1() {
  printf -- '--http1.1\n' > "$BREW_HTTP1_CURLRC"
  export HOMEBREW_CURLRC="$BREW_HTTP1_CURLRC"
}

brew_ensure() {
  local formula="$1"
  if brew_has "$formula"; then
    ok "$formula already installed"
    return 0
  fi

  local attempt
  for attempt in 1 2 3; do
    if [ "$attempt" -eq 1 ]; then
      step "Installing $formula"
    else
      warn "Download failed — retrying ($attempt/3). Homebrew resumes from where it stopped."
      [ "$attempt" -eq 2 ] && brew_force_http1 && warn "Forcing HTTP/1.1 for this and later downloads"
      sleep 3
    fi

    if brew install "$formula"; then
      ok "$formula installed"
      return 0
    fi

    # A formula that landed despite a non-zero exit is still a success.
    if brew_has "$formula"; then
      ok "$formula installed"
      return 0
    fi
  done

  die "Could not install $formula after 3 attempts.

This is almost always a flaky download, not a broken setup. Try:

  1. Run the setup script again — Homebrew resumes partial downloads:
       ./mac/setup-mac.sh

  2. If it keeps failing at the same point, force HTTP/1.1 for all of Homebrew
     by adding this to ~/.zshrc, then opening a new Terminal:
       echo '--http1.1' >> ~/.curlrc
       echo 'export HOMEBREW_CURLRC=1' >> ~/.zshrc

  3. Or install just this one package by hand and re-run the script:
       brew install $formula"
}

# ---- PostgreSQL ------------------------------------------------------------
# The dumps in this project were produced by PostgreSQL 15, but Homebrew's
# `postgis` bottle no longer ships modules built against postgresql@15 (only
# @17/@18 as of postgis 3.6.4), so CREATE EXTENSION postgis fails on 15.
# Pinned to 17 instead; pg_restore reads the older dumps fine.
PG_FORMULA="postgresql@17"
pg_bin_dir() { echo "$BREW_PREFIX/opt/$PG_FORMULA/bin"; }
add_pg_to_path() { export PATH="$(pg_bin_dir):$PATH"; }

# ---- .env helpers ----------------------------------------------------------
# Read a KEY=value out of the backend .env without sourcing it (values may
# contain characters bash would choke on).
env_get() {
  local key="$1" default="${2:-}" file="$BACKEND_DIR/.env"
  [ -f "$file" ] || { echo "$default"; return; }
  local line
  line="$(grep -E "^[[:space:]]*${key}[[:space:]]*=" "$file" | tail -1 || true)"
  [ -n "$line" ] || { echo "$default"; return; }
  line="${line#*=}"
  line="$(printf '%s' "$line" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' -e "s/^'//" -e "s/'$//" -e 's/^"//' -e 's/"$//')"
  printf '%s' "$line"
}
