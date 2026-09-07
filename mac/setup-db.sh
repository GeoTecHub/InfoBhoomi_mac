#!/usr/bin/env bash
#
# setup-db.sh — start PostgreSQL 15, create the `postgres` superuser role and
# the infobhoomi_dev database with PostGIS, then optionally restore a dump.
#
#   Usage:  ./mac/setup-db.sh [--restore <dump-file>] [--no-restore] [--force]
#
# Notes on the dumps that ship with this project:
#   * Files starting with the bytes "PGDMP" are pg_dump *custom* format and
#     must be restored with pg_restore, regardless of their .sql extension.
#   * They were taken on Windows with LOCALE 'English_United States.1252',
#     which does not exist on macOS. That is why this script creates the
#     database itself and restores *into* it rather than letting the dump
#     issue its own CREATE DATABASE.
#
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

require_macos
load_brew
add_pg_to_path

RESTORE_FILE=""
DO_RESTORE="ask"
FORCE=0
while [ $# -gt 0 ]; do
  case "$1" in
    --restore)    RESTORE_FILE="${2:-}"; DO_RESTORE="yes"; shift 2 ;;
    --no-restore) DO_RESTORE="no"; shift ;;
    --force)      FORCE=1; shift ;;
    -h|--help)    sed -n '2,17p' "$0"; exit 0 ;;
    *)            die "Unknown option: $1" ;;
  esac
done

DB_NAME="$(env_get DB_NAME infobhoomi_dev)"
DB_USER="$(env_get DB_USER postgres)"
DB_PASSWORD="$(env_get DB_PASSWORD '')"
DB_HOST="$(env_get DB_HOST localhost)"
DB_PORT="$(env_get DB_PORT 5432)"

step "Target database"
echo "  name : $DB_NAME"
echo "  user : $DB_USER"
echo "  host : $DB_HOST:$DB_PORT"

command -v psql >/dev/null 2>&1 || die "psql not on PATH. Run ./mac/setup-mac.sh first."
ok "psql $(psql --version | awk '{print $3}')"

# ---------------------------------------------------------------------------
# 1. Service
# ---------------------------------------------------------------------------
step "Starting $PG_FORMULA"
if brew services list | grep -qE "^${PG_FORMULA}[[:space:]]+started"; then
  ok "Already running"
else
  brew services start "$PG_FORMULA"
  ok "Service started"
fi

printf '  waiting for the server to accept connections'
for _ in $(seq 1 30); do
  if pg_isready -h "$DB_HOST" -p "$DB_PORT" >/dev/null 2>&1; then break; fi
  printf '.'; sleep 1
done
printf '\n'
pg_isready -h "$DB_HOST" -p "$DB_PORT" >/dev/null 2>&1 \
  || die "PostgreSQL is not accepting connections on $DB_HOST:$DB_PORT.
Check the log: tail -50 $BREW_PREFIX/var/log/${PG_FORMULA}.log"
ok "Server is up"

# Homebrew initialises the cluster with a superuser named after the macOS
# account, not `postgres`. The project's .env expects `postgres`, so create it.
ADMIN_DB="postgres"
psql_admin() { psql -h "$DB_HOST" -p "$DB_PORT" -d "$ADMIN_DB" -v ON_ERROR_STOP=1 "$@"; }

step "Ensuring role '$DB_USER'"
if psql_admin -tAc "SELECT 1 FROM pg_roles WHERE rolname='$DB_USER'" | grep -q 1; then
  ok "Role exists"
  if [ -n "$DB_PASSWORD" ]; then
    psql_admin -c "ALTER ROLE \"$DB_USER\" WITH LOGIN SUPERUSER PASSWORD '$DB_PASSWORD';" >/dev/null
    ok "Password synced with .env"
  fi
else
  if [ -n "$DB_PASSWORD" ]; then
    psql_admin -c "CREATE ROLE \"$DB_USER\" WITH LOGIN SUPERUSER PASSWORD '$DB_PASSWORD';" >/dev/null
  else
    psql_admin -c "CREATE ROLE \"$DB_USER\" WITH LOGIN SUPERUSER;" >/dev/null
  fi
  ok "Role created"
fi

# ---------------------------------------------------------------------------
# 2. Database + extensions
# ---------------------------------------------------------------------------
DB_EXISTS=0
psql_admin -tAc "SELECT 1 FROM pg_database WHERE datname='$DB_NAME'" | grep -q 1 && DB_EXISTS=1

step "Ensuring database '$DB_NAME'"
if [ "$DB_EXISTS" -eq 1 ]; then
  if [ "$FORCE" -eq 1 ]; then
    warn "--force given: dropping and recreating $DB_NAME"
    psql_admin -c "DROP DATABASE \"$DB_NAME\";" >/dev/null
    DB_EXISTS=0
  else
    ok "Database already exists (pass --force to recreate)"
  fi
fi

if [ "$DB_EXISTS" -eq 0 ]; then
  # LOCALE_PROVIDER/LOCALE are deliberately left at the cluster default —
  # the Windows dumps' 'English_United States.1252' is not valid on macOS.
  psql_admin -c "CREATE DATABASE \"$DB_NAME\" OWNER \"$DB_USER\" ENCODING 'UTF8' TEMPLATE template0;" >/dev/null
  ok "Database created"
fi

step "Enabling extensions"
for ext in postgis "uuid-ossp" postgis_topology; do
  if psql -h "$DB_HOST" -p "$DB_PORT" -d "$DB_NAME" -v ON_ERROR_STOP=1 \
        -c "CREATE EXTENSION IF NOT EXISTS \"$ext\";" >/dev/null 2>&1; then
    ok "$ext"
  else
    warn "$ext could not be enabled (may be optional)"
  fi
done
psql -h "$DB_HOST" -p "$DB_PORT" -d "$DB_NAME" -tAc "SELECT postgis_version();" \
  | sed 's/^/  PostGIS: /'

# ---------------------------------------------------------------------------
# 3. Restore
# ---------------------------------------------------------------------------
find_dumps() {
  # Newest first. BSD xargs runs its command even on empty input (there is no
  # -r flag), so `ls -t` would list the cwd instead of nothing. Sort by mtime.
  find "$PROJECT_ROOT" -maxdepth 2 \
    \( -name '*.sql' -o -name '*.dump' \) \
    -size +100k \
    -not -path '*/venv/*' -not -path '*/node_modules/*' \
    -print0 2>/dev/null \
  | while IFS= read -r -d '' f; do stat -f '%m %N' "$f" 2>/dev/null; done \
  | sort -rn | cut -d' ' -f2-
}

if [ "$DO_RESTORE" = "ask" ]; then
  echo
  step "Available dumps (newest first)"
  # `mapfile` is bash 4+; macOS ships bash 3.2, so read the list the long way.
  DUMPS=()
  while IFS= read -r _line; do
    [ -n "$_line" ] && DUMPS+=("$_line")
  done < <(find_dumps)
  if [ "${#DUMPS[@]}" -eq 0 ]; then
    warn "No dump files found."
    DO_RESTORE="no"
  else
    i=1
    for d in "${DUMPS[@]}"; do
      printf '  %2d) %-55s %s\n' "$i" "${d#$PROJECT_ROOT/}" "$(du -h "$d" | cut -f1)"
      i=$((i+1))
    done
    echo "   0) skip restore"
    echo
    read -r -p "  Restore which? [0] " choice
    choice="${choice:-0}"
    if [ "$choice" != "0" ] && [ "$choice" -ge 1 ] 2>/dev/null && [ "$choice" -le "${#DUMPS[@]}" ]; then
      RESTORE_FILE="${DUMPS[$((choice-1))]}"
      DO_RESTORE="yes"
    else
      DO_RESTORE="no"
    fi
  fi
fi

if [ "$DO_RESTORE" = "yes" ]; then
  [ -f "$RESTORE_FILE" ] || die "Dump not found: $RESTORE_FILE"
  step "Restoring $(basename "$RESTORE_FILE")"

  export PGPASSWORD="$DB_PASSWORD"
  MAGIC="$(head -c 5 "$RESTORE_FILE" 2>/dev/null || true)"

  if [ "$MAGIC" = "PGDMP" ]; then
    ok "Detected pg_dump custom format -> using pg_restore"
    # --no-owner / --no-privileges: the dump's grants reference Windows-side
    # roles that do not exist here. Errors are expected and non-fatal, hence
    # the deliberate lack of --exit-on-error.
    pg_restore -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" \
      --no-owner --no-privileges --clean --if-exists --verbose \
      "$RESTORE_FILE" 2> >(grep -vE 'does not exist|already exists' >&2) || true
  else
    ok "Detected plain SQL -> using psql"
    psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" \
      -v ON_ERROR_STOP=0 -f "$RESTORE_FILE" \
      2> >(grep -vE 'does not exist|already exists' >&2) >/dev/null || true
  fi
  unset PGPASSWORD

  TABLES="$(psql -h "$DB_HOST" -p "$DB_PORT" -d "$DB_NAME" -tAc \
    "SELECT count(*) FROM information_schema.tables WHERE table_schema='public';")"
  ok "Restore finished — $TABLES tables in schema public"
fi

# ---------------------------------------------------------------------------
# 4. Migrations
# ---------------------------------------------------------------------------
if [ -x "$VENV_PY" ]; then
  step "Applying Django migrations"
  if (cd "$BACKEND_DIR" && "$VENV_PY" manage.py migrate); then
    ok "Migrations applied"
  else
    warn "Migrations failed. Inspect with:"
    warn "  cd $BACKEND_DIR && venv/bin/python manage.py showmigrations user | tail -20"
  fi
else
  warn "Backend venv not built yet — run ./mac/setup-mac.sh, then:"
  warn "  cd $BACKEND_DIR && venv/bin/python manage.py migrate"
fi

cat <<NEXT

$C_BOLD Database ready. $C_RESET  Start the stack with:

    ./mac/run-all.sh

NEXT
