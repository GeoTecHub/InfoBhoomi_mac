# InfoBhoomi on macOS

This project was developed on Windows. Everything needed to run it from a Mac
terminal now lives in the `mac/` folder. Source code is unchanged apart from
`infobhoomi/settings.py`, which now finds GDAL/GEOS on all three platforms.

---

## TL;DR

```bash
# 1. From the USB drive — copy to the internal disk (skip if already copied)
cd /Volumes/USB321FD/InfoBhoomi
bash mac/bootstrap-mac.sh             # -> ~/Projects/InfoBhoomi
#    ^ use `bash mac/...` here, not `./mac/...`: exFAT cannot store the
#      executable bit, so `./` gives "permission denied" on the USB drive.
#      After the copy, `./mac/...` works everywhere else.

# 2. Install everything
cd ~/Projects/InfoBhoomi
./mac/fetch-deps.sh          # optional: pre-download bottles on a flaky connection
./mac/setup-mac.sh

# 3. Create the database and restore a dump
./mac/setup-db.sh

# 4. Run
./mac/run-all.sh
```

| Service      | URL                     | Script              |
|--------------|-------------------------|---------------------|
| Django API   | http://localhost:8000   | `./mac/run-backend.sh`  |
| Frontend     | http://localhost:4200   | `./mac/run-frontend.sh` |
| 3D Cadastre  | http://localhost:5175   | `./mac/run-3d.sh`       |

---

## Why the copy step matters

USB sticks are formatted exFAT. exFAT has no symlinks and no executable
permission bit. npm needs symlinks for `node_modules/.bin` (that is how the
`ng` command becomes runnable), and a Python venv needs the exec bit on
`venv/bin/python`. Running the project directly from the USB drive fails in
ways that look like unrelated npm or Python bugs.

`bootstrap-mac.sh` rsyncs the project to `~/Projects/InfoBhoomi`, skipping
everything Windows-built or regenerable: `venv/`, `node_modules/`, `.angular/`,
`dist/`, `__pycache__/`, `venv.zip`, the `.whl`, and old `*.log` files. It then
resets permissions (exFAT reports meaningless ones) and parks the Windows
Claude Code allowlists.

Want it somewhere else? `bash mac/bootstrap-mac.sh ~/code/InfoBhoomi`.

The script works with both rsync implementations. macOS ships Apple's rsync
(2.6.9 / openrsync), which does not understand `--info=progress2`; GNU rsync 3.x
from `brew install rsync` does. The flags are chosen at runtime, and the copy is
verified afterwards rather than assumed.

---

## What changed in the source

### `InfoBhoomi_Backend_dev2/infobhoomi/settings.py`

Django's GIS backend loads the GDAL and GEOS **C libraries** by file path. The
old code only handled Windows:

```python
if os.name == 'nt':
    GDAL_LIBRARY_PATH = .../osgeo/gdal.dll
    GEOS_LIBRARY_PATH = .../osgeo/geos_c.dll
```

There is now a `darwin` branch that probes Homebrew on both Apple Silicon
(`/opt/homebrew`) and Intel (`/usr/local`) for `libgdal.dylib` and
`libgeos_c.dylib`, sets `PROJ_LIB`, and prints an actionable warning if the
libraries are missing. A Linux branch was added too. The Windows branch is
untouched, so the project still runs on the old machine.

Overrides win over auto-detection — put these in `.env` if your libraries live
somewhere unusual:

```ini
GDAL_LIBRARY_PATH=/opt/homebrew/lib/libgdal.dylib
GEOS_LIBRARY_PATH=/opt/homebrew/lib/libgeos_c.dylib
```

The original file is kept as `settings.py.win.bak`.

### `InfoBhoomi_Backend_dev2/requirements.txt`

The old file was stale — it pinned `numpy==1.24.4` and `psycopg2==2.9.9` while
the working Windows venv actually held numpy 2.4.4 and psycopg2-binary 2.9.12,
plus shapely and requests which were not listed at all. It has been rewritten
from the real venv contents, with two macOS-specific choices:

- **`psycopg2-binary`** instead of `psycopg2` — ships prebuilt wheels, so there
  is no libpq/`pg_config` build step.
- **No `gdal` pip wheel.** No application code imports `osgeo`; only
  `django.contrib.gis` touches GDAL, and it loads the shared library by path.
  Installing the GDAL Python bindings on macOS is the single most painful part
  of this stack, and it turns out to be unnecessary here.

`ifcopenshell` moved to `requirements-ifc.txt` and installs as a separate,
non-fatal step — its wheels lag new Python releases, and only the IFC → CityJSON
import endpoints depend on it. Original kept as `requirements.txt.win.bak`.

### `3D-Cadastre/proxy.conf.local.json` (new)

The committed `proxy.conf.json` proxies `/api` to the production server. The new
file proxies to `http://localhost:8000` instead, and `run-3d.sh` uses it by
default. Pass `--remote` to use the production proxy.

### `InfoBhoomi_Backend_dev2/.env`

Added `http://localhost:5175` and `http://127.0.0.1:5175` to
`CORS_ALLOWED_ORIGINS` so the 3D app can also reach the backend directly, not
only through the dev-server proxy.

---

## What `setup-mac.sh` installs

| Package             | Why |
|---------------------|-----|
| `geos`, `proj`, `gdal` | The C libraries `django.contrib.gis` loads |
| `postgresql@15`     | The dumps were taken from PostgreSQL 15.3 |
| `postgis`           | Every spatial table depends on it |
| `node`              | Angular 21 needs Node 20.19+ / 22.12+ / 24+ |
| `python@3.12`       | Only if no `python3.12`/`3.13`/`3.11` is present |

Python 3.12 is preferred over 3.13/3.14: Django 5.1 supports up to 3.13, and
3.12 has the widest arm64 wheel coverage for numpy, shapely and ifcopenshell.
The Windows venv used 3.14, which no longer applies here.

The script also deletes any `node_modules` carried over from Windows before
running `npm ci`. Those directories contain win32 esbuild and rollup binaries
that abort immediately on macOS — reinstalling is not optional.

Flags: `--skip-db`, `--skip-node`, `--skip-python`.

---

## Database notes

`setup-db.sh` starts `postgresql@15`, creates a `postgres` superuser role
(Homebrew initialises the cluster with a superuser named after your macOS
account, not `postgres`, which is what `.env` expects), creates
`infobhoomi_dev`, enables `postgis`, `uuid-ossp` and `postgis_topology`, then
offers a menu of the dumps it finds.

Two things about those dumps are worth knowing:

1. **`.sql` does not mean plain SQL here.** `backup_01.sql`, `backup_v3.sql`,
   `infobhoomi_dev_backup_20260314.sql` and `InfoBhoomi_dev.dump` all begin with
   the bytes `PGDMP` — they are pg_dump *custom* format and need `pg_restore`.
   Only `infobhoomi_dev_backup_20260313.sql` is genuine plain SQL.
   The script sniffs the magic bytes and picks the right tool.

2. **They carry a Windows locale.** The custom-format dumps embed
   `LOCALE = 'English_United States.1252'`, which does not exist on macOS. That
   is why the script creates the database itself with `TEMPLATE template0` and
   restores *into* it, rather than letting the dump run its own
   `CREATE DATABASE`. Ownership and grant errors during restore are expected and
   suppressed — `--no-owner --no-privileges` handles them.

Newest data at time of writing: `InfoBhoomi_Backend_dev2/backup_v3.sql`.
The largest (includes GND geometry): `infobhoomi_dev_backup_20260313.sql`.

```bash
./mac/setup-db.sh                                          # interactive menu
./mac/setup-db.sh --restore InfoBhoomi_Backend_dev2/backup_v3.sql
./mac/setup-db.sh --no-restore                             # schema only
./mac/setup-db.sh --force --restore <file>                 # drop & recreate first
```

Django migrations run at the end automatically.

---

## Manual equivalents

If you would rather not use the scripts:

```bash
# system libs
brew install geos proj gdal postgresql@15 postgis node python@3.12
brew services start postgresql@15
export PATH="$(brew --prefix)/opt/postgresql@15/bin:$PATH"

# backend
cd ~/Projects/InfoBhoomi/InfoBhoomi_Backend_dev2
python3.12 -m venv venv
source venv/bin/activate            # not venv\Scripts\activate
pip install -r requirements.txt
pip install -r requirements-ifc.txt # optional
python manage.py migrate
python manage.py runserver 8000

# frontend
cd ~/Projects/InfoBhoomi/infoBhoomi-frontedend-div2
npm ci
npx ng serve --no-hmr --port 4200

# 3d cadastre
cd ~/Projects/InfoBhoomi/3D-Cadastre
npm ci
npx ng serve --port 5175 --proxy-config proxy.conf.local.json
```

The Windows habit `venv\Scripts\activate` becomes `source venv/bin/activate`,
and `venv\Scripts\python.exe manage.py ...` becomes `venv/bin/python manage.py ...`.

---

## Troubleshooting

**`django.core.exceptions.ImproperlyConfigured: Could not find the GDAL library`**
Homebrew is either missing GDAL or installed somewhere unexpected.
```bash
brew install gdal geos proj
ls -l "$(brew --prefix)/lib/libgdal.dylib" "$(brew --prefix)/lib/libgeos_c.dylib"
```
If they exist but Django still cannot see them, pin the paths in `.env` as shown
above. This also happens if you run the backend with a system Python instead of
`venv/bin/python`.

**`Error: Failed to download resource "proj"` / `curl: (92) ... PROTOCOL_ERROR`**
A flaky download, not a broken setup. Homebrew's `proj` bottle is about 800 MB —
it now bundles the full PROJ grid dataset — and ghcr.io intermittently drops
HTTP/2 connections on large transfers. Homebrew caches what it already fetched,
so just run `./mac/setup-mac.sh` again and it resumes from where it stopped.

The script retries three times on its own and forces HTTP/1.1 from the second
attempt (via `mac/.homebrew-curlrc`), which usually clears it.

On a connection that drops mid-transfer, run the dedicated downloader first and
leave it going — it retries up to 40 times per package, resuming each time, and
installs nothing:

```bash
./mac/fetch-deps.sh          # or: ./mac/fetch-deps.sh 100
./mac/setup-mac.sh           # then this runs from cache, near-instantly
```

Check how much is already cached at any point:

```bash
ls -lh "$(brew --cache)/downloads" | grep proj
```

If it still fails in the same spot, make the HTTP/1.1 setting permanent and open
a new Terminal:

```bash
echo '--http1.1' >> ~/.curlrc
echo 'export HOMEBREW_CURLRC=1' >> ~/.zshrc
```

Already-installed packages are detected and skipped, so re-running costs nothing.

**`psql: command not found`**
Homebrew does not link versioned PostgreSQL formulae onto `PATH`. Add it to
your shell profile:
```bash
echo 'export PATH="$(brew --prefix)/opt/postgresql@15/bin:$PATH"' >> ~/.zshrc
```

**`FATAL: role "postgres" does not exist`**
Run `./mac/setup-db.sh` — creating that role is its first job.

**`connection to server at "localhost" failed`**
```bash
brew services list                      # is postgresql@15 started?
brew services restart postgresql@15
tail -50 "$(brew --prefix)/var/log/postgresql@15.log"
```

**npm errors mentioning `esbuild`, `@rollup/rollup-win32-x64-msvc`, or `.node` files**
Windows `node_modules` leaked through. Delete and reinstall:
```bash
rm -rf node_modules .angular package-lock.json.bak && npm ci
```

**`ng: command not found`**
Angular CLI is local, not global. Use `npx ng ...` or `npm start`.

**Port already in use**
```bash
lsof -ti :8000 | xargs kill        # or :4200, :5175
```
Or pass a port: `./mac/run-backend.sh 8001`.

**`EACCES` / `EPERM` / `operation not supported` during npm install**
You are still on the USB drive. Run `./mac/bootstrap-mac.sh`.

**`zsh: no such file or directory: ./mac/setup-mac.sh`**
The copy in step 1 did not finish, so `~/Projects/InfoBhoomi` is empty or partial.
Re-run `bash mac/bootstrap-mac.sh` from the USB drive and read its output — it now
verifies that the backend, both Angular apps and `mac/` all arrived.

**`rsync: unrecognized option '--info=progress2'`**
Fixed — the script now detects Apple's rsync and drops the GNU-only flags. If you
still hit it, you are running an older copy of the script from the USB drive.

**`permission denied: ./mac/bootstrap-mac.sh`**
You are on the USB drive, where exFAT cannot store the exec bit. Run
`bash mac/bootstrap-mac.sh` instead.

**Gatekeeper blocks a script**
```bash
chmod +x mac/*.sh
xattr -d com.apple.quarantine mac/*.sh 2>/dev/null || true
```

---

## Things deliberately left alone

- `agents/` still has its Windows venv. It is a separate tool; rebuild it the
  same way when you need it:
  `cd agents && python3.12 -m venv venv && venv/bin/pip install -r requirements.txt`
  (`ifcopenshell` there has the same wheel caveat.)
- The `.git` directories, all `.sql`/`.dump` files, `GDAL-*.whl` and `venv.zip`
  stay on the USB drive — the wheel and zip are Windows-only, the dumps are
  copied.
- Application logic, migrations and the Angular source are untouched. Nothing in
  them was Windows-specific: paths go through `os.path.join` / `pathlib`, and
  there are no `.bat` or PowerShell scripts anywhere in the tree.
