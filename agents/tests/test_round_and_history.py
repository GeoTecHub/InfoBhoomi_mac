"""Tests for the P6 round controller + History tab helpers."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_center.change_memory import ChangeMemory
from agent_center.dashboard_server import (
    build_round_followup_prompt,
    filter_history_edits,
)
from agent_center.issue_queue import IssueQueue


class RoundPromptTests(unittest.TestCase):
    def test_includes_prior_queue_id_and_failed_count(self):
        prompt = build_round_followup_prompt(
            prior_prompt="RRR owner not showing",
            prior_queue_id="Q-OLD",
            verify_snapshot=None,
            prior_failed_count=3,
        )
        self.assertIn("Round follow-up of Q-OLD", prompt)
        self.assertIn("RRR owner not showing", prompt)
        self.assertIn("3 prior fix attempt(s)", prompt)

    def test_includes_verify_summary_when_available(self):
        snap = {
            "found": True,
            "result": {
                "overall": "error",
                "frontend": {"status": "ok"},
                "backend":  {"status": "error"},
                "db":       {"status": "ok"},
            },
        }
        prompt = build_round_followup_prompt(
            prior_prompt="x", prior_queue_id="Q-1",
            verify_snapshot=snap, prior_failed_count=0,
        )
        self.assertIn("overall=error", prompt)
        self.assertIn("FE=ok", prompt)
        self.assertIn("BE=error", prompt)
        self.assertIn("DB=ok", prompt)

    def test_handles_missing_snapshot_gracefully(self):
        prompt = build_round_followup_prompt(
            prior_prompt="x", prior_queue_id="Q-1",
            verify_snapshot={"found": False}, prior_failed_count=0,
        )
        # No verify summary when snapshot is empty.
        self.assertNotIn("overall=", prompt)


class HistoryFilterTests(unittest.TestCase):
    def _edits(self):
        return [
            {"edit_id": "E1", "file_path": "fe/a.ts", "agent": "FrontendImplementer",
             "verification_outcome": "passed", "linked_run_id": "Q-A", "rolled_back": False},
            {"edit_id": "E2", "file_path": "be/b.py", "agent": "BackendImplementer",
             "verification_outcome": "failed", "linked_run_id": "Q-B", "rolled_back": False},
            {"edit_id": "E3", "file_path": "be/migrations/0042.py", "agent": "DBMigrationImplementer",
             "verification_outcome": "pending", "linked_run_id": "Q-A", "rolled_back": True},
        ]

    def test_no_filter_returns_all(self):
        self.assertEqual(len(filter_history_edits(self._edits())), 3)

    def test_file_substring_filter(self):
        out = filter_history_edits(self._edits(), file="migrations")
        self.assertEqual([e["edit_id"] for e in out], ["E3"])

    def test_outcome_filter(self):
        out = filter_history_edits(self._edits(), outcome="failed")
        self.assertEqual([e["edit_id"] for e in out], ["E2"])

    def test_queue_id_filter(self):
        out = filter_history_edits(self._edits(), queue_id="Q-A")
        self.assertEqual({e["edit_id"] for e in out}, {"E1", "E3"})

    def test_combined_filters(self):
        out = filter_history_edits(self._edits(), agent="frontend", outcome="passed")
        self.assertEqual([e["edit_id"] for e in out], ["E1"])


class RoundQueueIntegrationTests(unittest.TestCase):
    """Drive IssueQueue + ChangeMemory through the round flow without HTTP."""

    def test_round_completes_prior_and_promotes_new(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue  = IssueQueue(Path(tmp) / "q.json")
            ledger = ChangeMemory(Path(tmp) / "l.json")
            first  = queue.enqueue("RRR owner missing")
            # Simulate a failed apply round on Q-A.
            ledger.record_edit(
                agent="BackendImplementer", component="rrr",
                file_path="be/views/rrr.py", before_text="x", after_text="y",
                symptom_fingerprint="fp", linked_run_id=first["queue_id"],
            )
            ledger.update_verification(ledger.all_edits()[0]["edit_id"], "failed")
            # Round handler does: complete_current(failed) → enqueue new.
            queue.complete_current(outcome="failed")
            second = queue.enqueue(build_round_followup_prompt(
                prior_prompt="RRR owner missing", prior_queue_id=first["queue_id"],
                verify_snapshot=None, prior_failed_count=1,
            ))
            state = queue.list_state()
            self.assertEqual(state["current"]["queue_id"], second["queue_id"])
            self.assertIn("Round follow-up", state["current"]["prompt"])
            self.assertEqual(state["history"][0]["outcome"], "failed")

    def test_failed_edits_excluded_when_rolled_back(self):
        # ChangeMemory.was_attempted already excludes rolled-back; sanity-check.
        with tempfile.TemporaryDirectory() as tmp:
            ledger = ChangeMemory(Path(tmp) / "l.json")
            edit = ledger.record_edit(
                agent="X", component="c", file_path="f",
                before_text="a", after_text="b", symptom_fingerprint="fp",
            )
            ledger.update_verification(edit["edit_id"], "failed")
            ledger.mark_rolled_back(edit["edit_id"])
            self.assertEqual(ledger.was_attempted("fp"), [])


if __name__ == "__main__":
    unittest.main()
