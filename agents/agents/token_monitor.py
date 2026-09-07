"""
InfoBhoomi — Token Monitor + Session Memory Agent
===================================================
Tracks cumulative token usage across all Claude API calls made by the
agent system, warns before the context limit is reached, and persists
session state so work can resume in the next Cowork session.

Usage:
    monitor = TokenMonitor()
    monitor.load()                         # load previous session state
    monitor.record(input_tokens=500, output_tokens=200, step="research")
    monitor.check_and_warn()               # prints warning if near limit
    monitor.save(checkpoint_data={...})    # persist progress
"""

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from config import (
    TOKEN_WARN_FRACTION,
    TOKEN_CRITICAL_FRACTION,
    CLAUDE_MODEL_TOKEN_LIMIT,
    SESSION_STATE_FILE,
    TOKEN_LOG_FILE,
    STATE_DIR,
)

GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

WARN_LIMIT     = int(CLAUDE_MODEL_TOKEN_LIMIT * TOKEN_WARN_FRACTION)
CRITICAL_LIMIT = int(CLAUDE_MODEL_TOKEN_LIMIT * TOKEN_CRITICAL_FRACTION)


class TokenMonitor:
    """
    Tracks token usage and manages persistent session state.

    State file layout (session_state.json):
    {
        "session_id": "...",
        "started_at": "...",
        "last_updated": "...",
        "total_input_tokens": 0,
        "total_output_tokens": 0,
        "total_tokens": 0,
        "steps_completed": [],
        "checkpoint": {}           ← arbitrary data the orchestrator saves
    }
    """

    def __init__(self):
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        self.session_id: str = ""
        self.started_at: str = ""
        self.total_input: int = 0
        self.total_output: int = 0
        self.steps_completed: list[str] = []
        self.checkpoint: dict[str, Any] = {}
        self._token_log: list[dict] = []

    # ── Persistence ───────────────────────────────────────────────────────────

    def load(self) -> bool:
        """
        Load previous session state.
        Returns True if a previous session was found, False if starting fresh.
        """
        if SESSION_STATE_FILE.exists():
            try:
                with open(SESSION_STATE_FILE) as f:
                    data = json.load(f)
                self.session_id      = data.get("session_id", "")
                self.started_at      = data.get("started_at", "")
                self.total_input     = data.get("total_input_tokens", 0)
                self.total_output    = data.get("total_output_tokens", 0)
                self.steps_completed = data.get("steps_completed", [])
                self.checkpoint      = data.get("checkpoint", {})
                print(f"\n{CYAN}[TOKEN MONITOR]{RESET} Resuming session {self.session_id}")
                print(f"  Started:   {self.started_at}")
                print(f"  Tokens so far: {self.total_tokens:,} / {CLAUDE_MODEL_TOKEN_LIMIT:,}")
                print(f"  Steps done: {', '.join(self.steps_completed) or 'none'}")
                self._print_bar()
                return True
            except Exception as e:
                print(f"{YELLOW}[TOKEN MONITOR] Could not load session state: {e}{RESET}")

        # Fresh session — reset ALL state so a cleared session starts clean
        self.session_id      = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        self.started_at      = datetime.utcnow().isoformat() + "Z"
        self.total_input     = 0
        self.total_output    = 0
        self.steps_completed = []
        self.checkpoint      = {}
        self._token_log      = []
        print(f"\n{CYAN}[TOKEN MONITOR]{RESET} New session started: {self.session_id}")
        return False

    def save(self, checkpoint_data: Optional[dict] = None):
        """Persist current state to disk."""
        if checkpoint_data is not None:
            self.checkpoint.update(checkpoint_data)

        STATE_DIR.mkdir(parents=True, exist_ok=True)
        state = {
            "session_id": self.session_id,
            "started_at": self.started_at,
            "last_updated": datetime.utcnow().isoformat() + "Z",
            "total_input_tokens": self.total_input,
            "total_output_tokens": self.total_output,
            "total_tokens": self.total_tokens,
            "steps_completed": self.steps_completed,
            "checkpoint": self.checkpoint,
        }
        with open(SESSION_STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)

        # Append to token log
        self._token_log.append({
            "saved_at": state["last_updated"],
            "total_tokens": self.total_tokens,
        })
        with open(TOKEN_LOG_FILE, "w") as f:
            json.dump(self._token_log, f, indent=2)

        print(f"  {GREEN}[TOKEN MONITOR]{RESET} State saved → {SESSION_STATE_FILE.name}")

    def clear(self):
        """Remove session state (call after a clean run completes)."""
        if SESSION_STATE_FILE.exists():
            SESSION_STATE_FILE.unlink()
        if TOKEN_LOG_FILE.exists():
            TOKEN_LOG_FILE.unlink()
        print(f"  {CYAN}[TOKEN MONITOR]{RESET} Session state cleared.")

    # ── Token tracking ────────────────────────────────────────────────────────

    @property
    def total_tokens(self) -> int:
        return self.total_input + self.total_output

    @property
    def fraction_used(self) -> float:
        return self.total_tokens / CLAUDE_MODEL_TOKEN_LIMIT

    @property
    def remaining_tokens(self) -> int:
        return max(0, CLAUDE_MODEL_TOKEN_LIMIT - self.total_tokens)

    def record(self, input_tokens: int, output_tokens: int, step: str = ""):
        """Record token usage from one Claude API response."""
        self.total_input  += input_tokens
        self.total_output += output_tokens
        if step and step not in self.steps_completed:
            self.steps_completed.append(step)
        pct = self.fraction_used * 100
        color = GREEN if pct < 60 else YELLOW if pct < TOKEN_WARN_FRACTION * 100 else RED
        print(
            f"  {CYAN}[TOKEN MONITOR]{RESET} +{input_tokens + output_tokens:,} tokens "
            f"(step: {step or '?'})  "
            f"total: {color}{self.total_tokens:,}{RESET} / {CLAUDE_MODEL_TOKEN_LIMIT:,} "
            f"({color}{pct:.1f}%{RESET})"
        )

    def mark_step_done(self, step: str):
        """Mark a named step as completed (useful for resuming mid-run)."""
        if step not in self.steps_completed:
            self.steps_completed.append(step)

    def is_step_done(self, step: str) -> bool:
        return step in self.steps_completed

    # ── Warning logic ─────────────────────────────────────────────────────────

    def check_and_warn(self) -> str:
        """
        Checks token usage and prints a warning if needed.
        Returns: "ok" | "warn" | "critical"
        """
        if self.total_tokens >= CRITICAL_LIMIT:
            self._alert_critical()
            return "critical"
        elif self.total_tokens >= WARN_LIMIT:
            self._alert_warn()
            return "warn"
        return "ok"

    def _alert_warn(self):
        pct = self.fraction_used * 100
        print(f"\n{YELLOW}{BOLD}{'='*60}")
        print(f"  ⚠  TOKEN WARNING — {pct:.1f}% used")
        print(f"  Tokens used:      {self.total_tokens:,}")
        print(f"  Tokens remaining: {self.remaining_tokens:,}")
        print(f"  Threshold:        {WARN_LIMIT:,} ({TOKEN_WARN_FRACTION*100:.0f}%)")
        print(f"  Action: Save state now in case session ends soon.")
        print(f"{'='*60}{RESET}\n")

    def _alert_critical(self):
        pct = self.fraction_used * 100
        print(f"\n{RED}{BOLD}{'='*60}")
        print(f"  ⛔  TOKEN CRITICAL — {pct:.1f}% used")
        print(f"  Tokens used:      {self.total_tokens:,}")
        print(f"  Tokens remaining: {self.remaining_tokens:,}")
        print(f"  Session state has been saved automatically.")
        print(f"  ➜  Start a new session — the orchestrator will resume from checkpoint.")
        print(f"{'='*60}{RESET}\n")

    def _print_bar(self, width: int = 40):
        filled = int(self.fraction_used * width)
        bar = "█" * filled + "░" * (width - filled)
        pct = self.fraction_used * 100
        color = GREEN if pct < 60 else YELLOW if pct < 85 else RED
        print(f"  Token usage: [{color}{bar}{RESET}] {color}{pct:.1f}%{RESET}")

    def status_line(self) -> str:
        return (
            f"Tokens: {self.total_tokens:,}/{CLAUDE_MODEL_TOKEN_LIMIT:,} "
            f"({self.fraction_used*100:.1f}%)  "
            f"Steps done: {len(self.steps_completed)}"
        )
