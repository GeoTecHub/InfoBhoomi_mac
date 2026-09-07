"""
Change Memory — per-edit ledger.
================================
Records every modification an Implementer makes so the Architect /
Solution Architect can answer:

    "Have we ever tried to fix this exact symptom on this file?
     What did we try, what was the outcome?"

This is the cornerstone of the no-repeat-fix loop.

State file: ``.agent_state/change_ledger.json``
Schema:
{
  "version": 1,
  "edits": [
    {
      "edit_id": "EDIT-...",
      "linked_issue_id": "ISS-..." | "",
      "linked_run_id":   "RUN-..." | "",
      "agent": "FrontendImplementer" | "BackendImplementer" | "DBMigrationImplementer",
      "llm": "gemini-2.5-flash" | "claude-sonnet-4-6" | "",
      "component": "rrr.views.py::link_ba_unit",
      "file_path": "InfoBhoomi_Backend_dev2/user/views/rrr.py",
      "before_hash": "sha256:...",
      "after_hash":  "sha256:...",
      "diff": "...",
      "backup_path": ".agent_state/backups/2026-05-05T03-12-09Z/...",
      "applied_at": "ISO-Z",
      "verification_outcome": "passed" | "failed" | "partial" | "pending",
      "verification_evidence": {...},
      "symptom_fingerprint": "rrr.lifecycle|backend|/rrr_data_get/|GET|200|owner",
      "fingerprint_hash":    "abcd1234ef56",
      "rolled_back": false,
      "rolled_back_at": null
    },
    ...
  ]
}
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from config import AGENT_CHANGE_LEDGER_FILE, STATE_DIR
from agent_center._atomic import atomic_write_json, file_lock, read_json
from agent_center.symptom_fingerprint import fingerprint_hash


VERIFICATION_OUTCOMES = {"passed", "failed", "partial", "pending"}


def _utc_now() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def hash_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


class ChangeMemory:
    """Per-edit ledger with file lock + atomic write."""

    def __init__(self, path: Path = AGENT_CHANGE_LEDGER_FILE):
        self.path = Path(path)
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        self.data = self._load()

    # ── I/O ───────────────────────────────────────────────────────────────────

    def _load(self) -> dict[str, Any]:
        loaded = read_json(self.path, default=None)
        if isinstance(loaded, dict) and loaded:
            loaded.setdefault("version", 1)
            loaded.setdefault("edits", [])
            return loaded
        return {"version": 1, "edits": []}

    def save(self) -> None:
        with file_lock(self.path):
            atomic_write_json(self.path, self.data)

    # ── Recording ─────────────────────────────────────────────────────────────

    def record_edit(
        self,
        *,
        agent: str,
        component: str,
        file_path: str,
        before_text: str,
        after_text: str,
        diff: str = "",
        backup_path: str = "",
        symptom_fingerprint: str = "",
        linked_issue_id: str = "",
        linked_run_id: str = "",
        llm: str = "",
        verification_outcome: str = "pending",
        verification_evidence: dict | None = None,
    ) -> dict[str, Any]:
        if verification_outcome not in VERIFICATION_OUTCOMES:
            verification_outcome = "pending"
        edit = {
            "edit_id": f"EDIT-{uuid.uuid4().hex[:10].upper()}",
            "linked_issue_id": linked_issue_id,
            "linked_run_id":   linked_run_id,
            "agent":           agent,
            "llm":             llm,
            "component":       component,
            "file_path":       file_path,
            "before_hash":     hash_text(before_text),
            "after_hash":      hash_text(after_text),
            "diff":            diff,
            "backup_path":     backup_path,
            "applied_at":      _utc_now(),
            "verification_outcome":  verification_outcome,
            "verification_evidence": verification_evidence or {},
            "symptom_fingerprint":   symptom_fingerprint,
            "fingerprint_hash":      fingerprint_hash(symptom_fingerprint) if symptom_fingerprint else "",
            "rolled_back":     False,
            "rolled_back_at":  None,
        }
        self.data.setdefault("edits", []).insert(0, edit)
        # Keep ledger size sane.
        self.data["edits"] = self.data["edits"][:5000]
        self.save()
        return edit

    def update_verification(
        self,
        edit_id: str,
        outcome: str,
        evidence: dict | None = None,
    ) -> dict[str, Any]:
        if outcome not in VERIFICATION_OUTCOMES:
            raise ValueError(f"Unknown outcome '{outcome}'")
        for edit in self.data.get("edits", []):
            if edit.get("edit_id") == edit_id:
                edit["verification_outcome"] = outcome
                edit["verification_evidence"] = evidence or {}
                edit["verified_at"] = _utc_now()
                self.save()
                return edit
        raise KeyError(edit_id)

    def mark_rolled_back(self, edit_id: str) -> dict[str, Any]:
        for edit in self.data.get("edits", []):
            if edit.get("edit_id") == edit_id:
                edit["rolled_back"] = True
                edit["rolled_back_at"] = _utc_now()
                self.save()
                return edit
        raise KeyError(edit_id)

    # ── Queries (the whole point of this ledger) ──────────────────────────────

    def all_edits(self) -> list[dict[str, Any]]:
        return list(self.data.get("edits", []))

    def edits_for_file(self, file_path: str) -> list[dict[str, Any]]:
        return [e for e in self.data.get("edits", []) if e.get("file_path") == file_path]

    def was_attempted(
        self,
        symptom_fingerprint: str,
        file_path: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Return the list of prior edits with the same fingerprint, optionally
        constrained to a file. Solution Architect feeds these back to the LLM
        as anti-suggestions.
        """
        fp = symptom_fingerprint
        return [
            e for e in self.data.get("edits", [])
            if e.get("symptom_fingerprint") == fp
            and (file_path is None or e.get("file_path") == file_path)
            and not e.get("rolled_back")
        ]

    def failed_strategies_for(self, file_path: str) -> list[dict[str, Any]]:
        """All edits on a file whose verification did not pass (and weren't rolled back)."""
        return [
            e for e in self.data.get("edits", [])
            if e.get("file_path") == file_path
            and e.get("verification_outcome") in {"failed", "partial"}
            and not e.get("rolled_back")
        ]

    def fingerprints_failed(self) -> set[str]:
        return {
            e["symptom_fingerprint"]
            for e in self.data.get("edits", [])
            if e.get("verification_outcome") == "failed"
            and e.get("symptom_fingerprint")
            and not e.get("rolled_back")
        }

    def get_edit(self, edit_id: str) -> dict[str, Any] | None:
        for edit in self.data.get("edits", []):
            if edit.get("edit_id") == edit_id:
                return edit
        return None
