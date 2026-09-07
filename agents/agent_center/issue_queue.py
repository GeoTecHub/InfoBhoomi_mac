"""
Sequential issue queue (Decision #8).
=====================================
One issue at a time. New submissions append to ``pending``. The dashboard
exposes the queue and lets users cancel pending entries.

State file: ``.agent_state/issue_queue.json``
{
  "version": 1,
  "current": null | {queue_id, prompt, submitted_at, started_at, step},
  "pending": [{queue_id, prompt, submitted_at}, ...],
  "history": [{queue_id, prompt, submitted_at, started_at, completed_at,
               outcome, issue_id}, ...]   # capped at 100
}
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from config import AGENT_ISSUE_QUEUE_FILE, STATE_DIR
from agent_center._atomic import atomic_write_json, file_lock, read_json


VALID_STEPS = {
    "queued",
    "investigating",
    "reporter",
    "awaiting_resolve",
    "solution",
    "awaiting_apply",
    "applying",
    "verifying",
    "complete",
}

VALID_OUTCOMES = {"resolved", "dismissed", "cancelled", "failed"}


def _utc_now() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


@dataclass
class QueueEntry:
    queue_id:     str
    prompt:       str
    submitted_at: str
    started_at:   str | None = None
    step:         str = "queued"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class IssueQueue:
    """Sequential FIFO. Persistent. Cross-process safe via file_lock."""

    def __init__(self, path: Path = AGENT_ISSUE_QUEUE_FILE):
        self.path = Path(path)
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        self.data = self._load()

    # ── I/O ───────────────────────────────────────────────────────────────────

    def _load(self) -> dict[str, Any]:
        loaded = read_json(self.path, default=None)
        if isinstance(loaded, dict) and loaded:
            loaded.setdefault("version", 1)
            loaded.setdefault("current", None)
            loaded.setdefault("pending", [])
            loaded.setdefault("history", [])
            return loaded
        return {"version": 1, "current": None, "pending": [], "history": []}

    def save(self) -> None:
        with file_lock(self.path):
            atomic_write_json(self.path, self.data)

    # ── Public API ────────────────────────────────────────────────────────────

    def enqueue(self, prompt: str) -> dict[str, Any]:
        """Add a prompt to the queue. If nothing is current, promote it immediately."""
        if not prompt.strip():
            raise ValueError("Empty prompt cannot be queued.")
        entry = QueueEntry(
            queue_id=f"Q-{uuid.uuid4().hex[:10].upper()}",
            prompt=prompt.strip(),
            submitted_at=_utc_now(),
        ).to_dict()

        if self.data.get("current") is None:
            entry["started_at"] = _utc_now()
            entry["step"] = "investigating"
            self.data["current"] = entry
        else:
            self.data["pending"].append(entry)

        self.save()
        return entry

    def list_state(self) -> dict[str, Any]:
        return {
            "current": self.data.get("current"),
            "pending": list(self.data.get("pending", [])),
            "history": list(self.data.get("history", []))[:50],
        }

    def update_step(self, queue_id: str, step: str) -> dict[str, Any]:
        if step not in VALID_STEPS:
            raise ValueError(f"Unknown step '{step}'")
        current = self.data.get("current")
        if not current or current.get("queue_id") != queue_id:
            raise KeyError(f"{queue_id} is not the current entry")
        current["step"] = step
        self.save()
        return current

    def complete_current(
        self,
        outcome: str = "resolved",
        issue_id: str = "",
    ) -> dict[str, Any] | None:
        """Move ``current`` to history and promote the next pending entry."""
        if outcome not in VALID_OUTCOMES:
            raise ValueError(f"Unknown outcome '{outcome}'")
        current = self.data.get("current")
        if not current:
            return None
        completed = dict(current)
        completed["completed_at"] = _utc_now()
        completed["outcome"] = outcome
        completed["issue_id"] = issue_id
        history = self.data.setdefault("history", [])
        history.insert(0, completed)
        self.data["history"] = history[:100]

        # Promote the next pending entry, if any.
        pending = self.data.get("pending", [])
        if pending:
            next_entry = pending.pop(0)
            next_entry["started_at"] = _utc_now()
            next_entry["step"] = "investigating"
            self.data["current"] = next_entry
        else:
            self.data["current"] = None

        self.save()
        return completed

    def cancel_pending(self, queue_id: str) -> dict[str, Any]:
        """Remove a queued (not yet running) entry."""
        pending = self.data.get("pending", [])
        for i, entry in enumerate(pending):
            if entry.get("queue_id") == queue_id:
                cancelled = pending.pop(i)
                cancelled["completed_at"] = _utc_now()
                cancelled["outcome"] = "cancelled"
                self.data.setdefault("history", []).insert(0, cancelled)
                self.data["history"] = self.data["history"][:100]
                self.save()
                return cancelled
        raise KeyError(f"{queue_id} not in pending")

    def find(self, queue_id: str) -> dict[str, Any] | None:
        current = self.data.get("current")
        if current and current.get("queue_id") == queue_id:
            return current
        for entry in self.data.get("pending", []):
            if entry.get("queue_id") == queue_id:
                return entry
        for entry in self.data.get("history", []):
            if entry.get("queue_id") == queue_id:
                return entry
        return None
