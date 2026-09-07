"""
InfoBhoomi Agent System — Configuration
========================================
Credentials are loaded exclusively from the .env file in this folder.
Never hardcode passwords or API keys here.
"""

import os
import pathlib
from dotenv import load_dotenv

_env_file = pathlib.Path(__file__).parent / ".env"
load_dotenv(dotenv_path=_env_file)

# ── InfoBhoomi Django API ────────────────────────────────────────────────────
BASE_URL      = os.environ.get("IB_BASE_URL", "https://infobhoomiback.geoinfobox.com/api/user")
TOKEN         = os.environ.get("IB_TOKEN", "")
USERNAME      = os.environ.get("IB_USERNAME", "")
PASSWORD      = os.environ.get("IB_PASSWORD", "")

TEST_LAYER_ID = int(os.environ.get("IB_LAYER_ID", "0"))

TEST_POLYGON_COORDS = [
    [
        [81.0649, 6.9973],
        [81.0659, 6.9973],
        [81.0659, 6.9983],
        [81.0649, 6.9983],
        [81.0649, 6.9973],
    ]
]
TEST_POINT_COORDS = [81.0654, 6.9978]
TEST_LINE_COORDS  = [[81.0649, 6.9973], [81.0659, 6.9983]]

# ── LLM APIs ─────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL      = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")
GEMINI_API_KEY    = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL      = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
AGENT_AI_PROVIDER = os.environ.get("AGENT_AI_PROVIDER", "local").lower()

# ── Token monitor thresholds ─────────────────────────────────────────────────
TOKEN_WARN_FRACTION      = 0.70
TOKEN_CRITICAL_FRACTION  = 0.85
CLAUDE_MODEL_TOKEN_LIMIT = 200_000

# ── Performance thresholds (ms) ──────────────────────────────────────────────
PERF_WARN_MS     = 1_000
PERF_SLOW_MS     = 3_000
PERF_CRITICAL_MS = 8_000

# ── Session state files ──────────────────────────────────────────────────────
AGENTS_DIR           = pathlib.Path(__file__).parent
STATE_DIR            = AGENTS_DIR / ".agent_state"
SESSION_STATE_FILE   = STATE_DIR / "session_state.json"
FINDINGS_FILE        = STATE_DIR / "findings.json"
PENDING_CHANGES_FILE = STATE_DIR / "pending_changes.json"
TOKEN_LOG_FILE       = STATE_DIR / "token_log.json"
QA_REPORT_FILE       = STATE_DIR / "qa_report.json"
MEMORY_FILE          = STATE_DIR / "memory.json"

# ── Agent QA & Debug Control Center ──────────────────────────────────────────
AGENT_ENVIRONMENT = os.environ.get("IB_AGENT_ENVIRONMENT", "development").lower()
AGENT_ALLOW_DESTRUCTIVE = os.environ.get("IB_AGENT_ALLOW_DESTRUCTIVE", "false").lower() in (
    "1", "true", "yes",
)
AGENT_TEST_TAG       = os.environ.get("IB_AGENT_TEST_TAG", "[AGENT-QA]")
AGENT_DASHBOARD_HOST = os.environ.get("IB_AGENT_DASHBOARD_HOST", "127.0.0.1")
AGENT_DASHBOARD_PORT = int(os.environ.get("IB_AGENT_DASHBOARD_PORT", "8765"))

AGENT_MEMORY_FILE         = STATE_DIR / "qa_debug_memory.json"
AGENT_RUN_REPORTS_DIR     = STATE_DIR / "qa_reports"
AGENT_FIX_PROPOSALS_FILE  = STATE_DIR / "fix_proposals.json"

# ── Self-Healing Pipeline (P0/P1) ────────────────────────────────────────────
AGENT_DASHBOARD_TOKEN_FILE = STATE_DIR / "dashboard_token.txt"
AGENT_CHANGE_LEDGER_FILE   = STATE_DIR / "change_ledger.json"
AGENT_ISSUE_QUEUE_FILE     = STATE_DIR / "issue_queue.json"
AGENT_BACKUPS_DIR          = STATE_DIR / "backups"
AGENT_STAGING_DIR          = STATE_DIR / "staging"
AGENT_SOLUTION_PLANS_FILE  = STATE_DIR / "solution_plans.json"
AGENT_LLM_COST_FILE        = STATE_DIR / "llm_cost_ledger.json"

PROJECT_ROOT  = AGENTS_DIR.parent
AGENT_FE_ROOT = pathlib.Path(
    os.environ.get("IB_AGENT_FE_ROOT", str(PROJECT_ROOT / "infoBhoomi-frontedend-div2"))
)
AGENT_BE_ROOT = pathlib.Path(
    os.environ.get("IB_AGENT_BE_ROOT", str(PROJECT_ROOT / "InfoBhoomi_Backend_dev2"))
)

AGENT_EVIDENCE_MAX_BYTES = int(os.environ.get("IB_AGENT_EVIDENCE_MAX_BYTES", "4096"))
AGENT_DEFAULT_LLM        = os.environ.get("IB_AGENT_DEFAULT_LLM", "gemini").lower()

# ── Optional read-only DB verification ───────────────────────────────────────
IB_DATABASE_URL = os.environ.get("IB_DATABASE_URL", "")
IB_DB_HOST      = os.environ.get("IB_DB_HOST", "")
IB_DB_PORT      = os.environ.get("IB_DB_PORT", "5432")
IB_DB_NAME      = os.environ.get("IB_DB_NAME", "")
IB_DB_USER      = os.environ.get("IB_DB_USER", "")
IB_DB_PASSWORD  = os.environ.get("IB_DB_PASSWORD", "")
