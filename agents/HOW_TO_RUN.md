# InfoBhoomi Agent System — How to Run

This document covers **two separate agent systems** that coexist in this folder:

| System | Driver | Purpose |
|---|---|---|
| **Self-Healing Pipeline (recommended)** | `python run_agent_dashboard.py` | Investigate → Solve → Apply → Verify, with no-repeat-fix memory across rounds. Browser-based. |
| **Legacy CLI loop** | `python orchestrator.py` | Original 10-phase QA + Claude Research Agent loop. Runs in the terminal. |

The two are independent; they do not share state files. Pick the one that fits, or use both.

---

## 1. Install dependencies

```bash
cd InfoBhoomi/agents
pip install -r requirements.txt
```

---

## 2. Configure credentials

Copy `.env.example` → `.env` and fill in the values you need:

```ini
# ── InfoBhoomi Django API ───────────────────────────────────────
IB_BASE_URL    = https://infobhoomiback.geoinfobox.com/api/user
IB_TOKEN       = your_drf_token         # preferred
IB_USERNAME    = your_username          # fallback if no token
IB_PASSWORD    = your_password
IB_LAYER_ID    = 0                       # 0 = auto-detect

# ── LLM keys ────────────────────────────────────────────────────
ANTHROPIC_API_KEY = sk-ant-...           # Claude (legacy CLI + new pipeline)
GEMINI_API_KEY    = AIza...              # Gemini (new pipeline)
GEMINI_MODEL      = gemini-2.5-flash
CLAUDE_MODEL      = claude-sonnet-4-6
IB_AGENT_DEFAULT_LLM = gemini            # fallback when picker dismissed

# ── Self-healing pipeline ───────────────────────────────────────
IB_AGENT_ENVIRONMENT       = development # development | staging | production
IB_AGENT_ALLOW_DESTRUCTIVE = false
IB_AGENT_TEST_TAG          = [AGENT-QA]
IB_AGENT_DASHBOARD_HOST    = 127.0.0.1
IB_AGENT_DASHBOARD_PORT    = 8765
IB_AGENT_FE_ROOT           =             # default = ../infoBhoomi-frontedend-div2
IB_AGENT_BE_ROOT           =             # default = ../InfoBhoomi_Backend_dev2
IB_AGENT_EVIDENCE_MAX_BYTES = 4096

# ── Optional read-only DB verification ─────────────────────────
IB_DATABASE_URL =
IB_DB_HOST = ;  IB_DB_PORT = 5432
IB_DB_NAME = ;  IB_DB_USER = ;  IB_DB_PASSWORD =
```

---

## Land parcel data seeding

Use this when you want an agent to put generated attribute data into existing
land parcel records and save it through the InfoBhoomi API.

Preview one land parcel without writing:

```bash
cd InfoBhoomi/agents
python seed_data.py --land-only --su-id 12505 --dry-run
```

Save generated data into one land parcel:

```bash
cd InfoBhoomi/agents
python seed_data.py --land-only --su-id 12505
```

Overwrite existing attribute data for one land parcel:

```bash
cd InfoBhoomi/agents
python seed_data.py --land-only --su-id 12505 --force
```

Seed the first 20 land parcels:

```bash
cd InfoBhoomi/agents
python seed_data.py --land-only --limit 20
```

If your land parcel layer is `6` instead of `1`, use `--layer 6` instead of
`--land-only`.

---

## 3. Run the Self-Healing Dashboard (recommended)

```bash
cd InfoBhoomi/agents
python run_agent_dashboard.py
```

The first lines of output look like this:

```
════════════════════════════════════════════════════════════════
  InfoBhoomi Agent QA & Debug Control Center
  Listening on  http://127.0.0.1:8765
  Auth token    aB7c-XYZ123...
  (also saved → .agent_state/dashboard_token.txt)
════════════════════════════════════════════════════════════════
  Paste the token in the dashboard login screen.
  Press Ctrl+C to stop.
```

Open <http://127.0.0.1:8765> in your browser, paste the auth token (also stored at `.agent_state/dashboard_token.txt`), and you land on the **Investigate** tab.

### 3.1 The full debugging round

| Step | What happens | Where |
|---|---|---|
| 1. Submit | You type the symptom (e.g. *"RRR owner is not showing for parcel"*) | Investigate tab |
| 2. Investigate | Architect routes via DebugRouter → ComponentMap → dispatches FE / BE / DB Investigators in parallel | auto |
| 3. Plain-language report | LLM picker (Gemini / Claude); cheap call summarises evidence per layer | modal |
| 4. Resolve | Click "Resolve this issue" | button |
| 5. Solution plan | LLM picker (Gemini / Claude); per-layer fix items, each editable in textareas | modal |
| 6. Save edits | "Save my edits" persists your amendments | button |
| 7. Apply → Stage | Approve items per checkbox; **Stage approved** writes backups + staging files; diff preview | Apply card |
| 8. Apply → Commit | **Commit staged** replaces real source files; ChangeMemory rows written | button |
| 9. Migrations | If a migration item committed: **Apply migration now (dev only)** OR **Show me the command** | mig panel |
| 10. Verify | **Run verification** kicks off `ng build --configuration development` (FE) + `manage.py check` (BE) + DB key-field probe + registry rerun | Verify card |
| 11. Auto-complete | If `overall=ok`, queue auto-promotes the next pending issue | auto |
| 12. Round again | Otherwise, **Run another debugging round** enqueues a new entry whose prompt includes prior verification context — Solution Architect is told what already failed | button |

### 3.2 Tabs

- **Investigate** — primary debugging flow described above
- **History** — every committed edit, filterable by file / agent / outcome / queue id; per-edit Rollback button
- **Function QA** — legacy registry-driven function tests (auth, layers, RRR, etc.)
- **Issue Memory** — raw issues / runs / fix proposals from `qa_debug_memory.json`

### 3.3 Useful endpoints (you don't need them for normal use)

```
POST /api/queue                     enqueue an issue
GET  /api/queue                     current + pending + history
DELETE /api/queue/{id}              cancel a pending entry
POST /api/queue/{id}/abandon        abandon current entry, promote next

POST /api/investigate/run           run Architect + Investigators
POST /api/report                    generate plain-language report (LLM)

POST /api/solve                     generate Solution Plan (LLM)
POST /api/solve/save                persist user-amended plan
GET  /api/solve/{id}                fetch cached plan

POST /api/apply/preview             diff + scope check (no writes)
POST /api/apply/stage               write backups + staging files
POST /api/apply/commit              commit staged files
POST /api/apply/rollback            restore an edit from its backup
POST /api/apply/migrate             dev-only manage.py migrate
GET  /api/apply/migrate/command     manual command to copy-paste

POST /api/verify                    start verification (background)
GET  /api/verify/{id}?log_offset=N  poll status + new log lines
POST /api/verify/{id}/cancel        kill in-flight subprocess

POST /api/round                     enqueue a follow-up round

GET  /api/history?file=&agent=&outcome=&queue_id=
GET  /api/cost?queue_id=            tokens + USD per round
GET  /api/llm/status                provider availability
```

All `/api/*` calls require `X-Agent-Token` header.

### 3.4 Safety guarantees

- Nothing modifies source until you click **Commit**.
- Backups are timestamped; rollback is one click.
- Implementers refuse paths outside their declared root (FE / BE / migrations).
- DB migrations: file is generated, but `manage.py migrate` only runs on explicit click in `IB_AGENT_ENVIRONMENT=development`.
- `IB_AGENT_ALLOW_DESTRUCTIVE` from the request body is ignored — env var is the only source.
- Concurrent dashboard requests are safe (atomic JSON writes + cross-process file lock).
- Every committed edit lands in `.agent_state/change_ledger.json` with before/after sha256, diff, backup path, queue id, LLM used, and verification outcome.

### 3.5 Round memory (no-repeat fixes)

Each `SolutionItem` carries a fine-grained fingerprint:
```
function_id | layer | endpoint | METHOD | status_code | missing_field
```
When the next round runs, the Architect pulls every prior failed edit on the routed components from `change_ledger.json` and the Solution Architect prompt receives them under **"ALREADY-TRIED STRATEGIES THAT FAILED — DO NOT REPROPOSE THESE"**. Rolled-back edits are excluded so you can intentionally retry a strategy.

### 3.6 Cost ledger

Every Reporter and Solution Architect LLM call is recorded to `.agent_state/llm_cost_ledger.json` with provider, model, input/output tokens, and a USD estimate. Defaults cover Gemini Flash/Pro and Claude Haiku/Sonnet/Opus; override any model rate via env, e.g.:
```bash
IB_AGENT_LLM_RATE_CLAUDE_SONNET_4_6=2.5,12   # input,output USD per 1M tokens
```
View aggregates at `GET /api/cost?queue_id=Q-...` (or per-call without the param).

---

## 4. Run the Legacy CLI Loop

```bash
python orchestrator.py
```

Runs: GIS perf test → 10-phase QA → (with permission) Research Agent (Claude) → you Y/N each fix → re-test until clean.

Other entry points:

| Command | What |
|---|---|
| `python orchestrator.py --qa-only` | QA tests only — no perf, no research |
| `python orchestrator.py --perf-only` | API performance test only |
| `python orchestrator.py --memory` | Print full cycle history |
| `python orchestrator.py --resume` | Resume from last checkpoint |
| `python orchestrator.py --approve` | Go straight to change approval |
| `python orchestrator.py --show` | Show pending changes from last run |
| `python orchestrator.py --clear` | Wipe session state and start fresh |

The legacy loop writes to `.agent_state/findings.json`, `pending_changes.json`, `qa_report.json`, `memory.json`, `session_state.json`, `token_log.json`. These are independent of the new pipeline's state files.

### 4.1 What the legacy QA Agent tests (10 phases)

| Phase | What | Key checks |
|---|---|---|
| A | Draw & save POINT | Save response, retrieval, timing |
| B | Draw & save LINE | Save response, geometry type in DB |
| C | Draw & save POLYGON | Response fields, ring closed, timing |
| D | Land parcel + ALL attributes | Admin / overview / zoning / phys-env / tax / utility — each PUT timed |
| E | DB verification | Re-fetch all 6 attribute tables |
| F | Split simulation | Child polygon + parent_uuid + history |
| G | Delete + history | Delete polygon, geom-edit-history, attrib history |
| H | Query builder | Basic query, layer filter, search endpoint |
| I | Export (shapefile) | GET export-shp/, verify file returned |
| J | Cleanup | Bulk-delete all `[QA-AGENT-TEST]` parcels |

Slow responses (>1 s) are warnings; very slow (>3 s) are failures fed to the Research Agent.

---

## 5. State files (`.agent_state/`)

### Self-Healing Pipeline (new)
| File | Contents |
|---|---|
| `dashboard_token.txt` | Per-startup auth token (printed to console too) |
| `qa_debug_memory.json` | Issues, runs, fix proposals (StructuredMemory) |
| `qa_reports/<RUN-...>.json` | Per-run function QA reports |
| `change_ledger.json` | Every edit ever applied (before/after hash, diff, backup path, outcome) |
| `issue_queue.json` | Sequential queue: current + pending + history |
| `solution_plans.json` | Cached Solution Plans (survive server restart) |
| `llm_cost_ledger.json` | Per-LLM-call usage + USD estimate |
| `backups/<ISO-Z>/...` | Pre-edit copies of every file the Implementer touched |
| `staging/<rel-path>` | Proposed file content awaiting commit |

### Legacy CLI Loop
| File | Contents |
|---|---|
| `session_state.json` | Current progress + auth checkpoint |
| `findings.json` | Performance + QA issue report (input to Research Agent) |
| `pending_changes.json` | Proposed code changes awaiting your approval |
| `token_log.json` | Claude API token usage history |
| `qa_report.json` | Last QA run — all 35+ check results with timings |
| `memory.json` | Full history of all run cycles |
| `review/` | Approved snippets when target file wasn't found |

---

## 6. Tests

```bash
cd InfoBhoomi/agents
python -m unittest discover tests
```

The full self-healing pipeline has **137 tests** covering: atomic write + lock, redaction, dashboard auth, component map drift, change ledger queries, issue queue, FE/BE/DB Investigators, Architect, Reporter (fallback + stub LLM), Solution Architect (fallback + stub LLM), implementers (scope, drift, backup, stage, commit, rollback), Applier dispatch, DB Migration dev-only gate, Verification QA Agent, background Verify Runner, round controller, history filter, cost ledger, and an end-to-end happy-path.

To enforce that every component-map path actually exists on disk:
```bash
IB_RUN_DRIFT_CHECK=true python -m unittest tests.test_component_map
```

---

## 7. Self-healing flow at a glance

```
┌─────────────────────────────────────────────────────────────┐
│  1. User submits prompt → IssueQueue.enqueue()              │
└──────────────────────┬──────────────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────────────┐
│  2. Architect (no LLM): DebugRouter + ComponentMap          │
│     + ChangeMemory anti-suggestions                         │
└──────────────────────┬──────────────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────────────┐
│  3. Investigators run in parallel: FE / BE / DB             │
└──────────────────────┬──────────────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────────────┐
│  4. Plain-language Reporter (LLM picker #1)                 │
└──────────────────────┬──────────────────────────────────────┘
                       ▼ user clicks Resolve
┌─────────────────────────────────────────────────────────────┐
│  5. Solution Architect (LLM picker #2) — receives anti-     │
│     suggestions from prior failed rounds                    │
└──────────────────────┬──────────────────────────────────────┘
                       ▼ user amends + saves
┌─────────────────────────────────────────────────────────────┐
│  6. Apply: per-item approve → Stage (backup + diff) → Commit│
│     Per-layer Implementers enforce scope + drift checks     │
└──────────────────────┬──────────────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────────────┐
│  7. Verify: ng build + manage.py check + py_compile +       │
│     DB key-field probe + registry rerun                     │
└──────────────────────┬──────────────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────────────┐
│  8. ChangeMemory: every edit's verification_outcome stored  │
│     for the next round's anti-suggestion list               │
└──────────────────────┬──────────────────────────────────────┘
                       ▼
            ┌────────────────────────┐
            │ overall == ok ?         │
            │  YES → queue auto-     │
            │        promotes next    │
            │  NO  → user clicks      │
            │        "Run another     │
            │        debugging round" │
            └────────────────────────┘
```

---

## 8. Troubleshooting

- **`Workspace still starting`** — wait a few seconds and retry; the bash sandbox boots in the background.
- **Dashboard returns 401** — the token printed at startup is one-shot; refresh the browser, paste again.
- **`ng build` not found** — install Angular CLI (`npm i -g @angular/cli`) or rely on the package.json build script. The Verify agent skips FE smoke gracefully when neither is present.
- **`manage.py` not found** — set `IB_AGENT_BE_ROOT` if your backend lives outside `InfoBhoomi_Backend_dev2/`.
- **DB checks always skipped** — set `IB_DATABASE_URL` (or `IB_DB_*`) and `pip install psycopg2-binary`.
- **Token limit critical** — close out a session; the legacy orchestrator's token monitor saves checkpoint state automatically.

---

## 9. Authoring & extending

| Want to… | Edit |
|---|---|
| Add a new function/category | `agent_center/function_registry.py` |
| Map an existing function's FE/BE/DB sub-components | `agent_center/component_map.py` (then run drift check) |
| Add a new Investigator (e.g. linting agent) | `agent_center/investigators/<name>.py` + register in `__init__.py` |
| Support a new LLM provider | new file under `agent_center/ai_provider/` + register in `router.py` |
| Add LLM rate for cost estimation | `agent_center/cost_ledger.py` `_DEFAULT_RATES` |
| Extend the dashboard UI | `agent_center/dashboard_server.py` (HTML/JS lives in the same file) |

Plug-in points are designed to be small and additive; existing agents stay isolated.

---

## 10. Pipeline guarantees recap

- **Sequential queue** — one issue at a time; new submissions wait, are visible, and can be cancelled.
- **Two LLM picker steps** — Reporter and Solution Architect each ask which model to use.
- **Editable plans** — every Solution Architect item is editable before staging.
- **Two-step apply** — stage (writes backup + staging) is separate from commit (replaces real file).
- **Drift detection** — if the file changed between stage and commit, the commit aborts.
- **Open rollback** — anyone with dashboard access can roll back any edit in one click.
- **Real verification** — `ng build --configuration development` and `manage.py check` run as subprocesses with a streamed log.
- **No repeat fixes** — fingerprinted ChangeMemory feeds the Solution Architect anti-suggestions on every round.
- **Cost visibility** — per-round and global token/USD totals available at `/api/cost`.
