"""Tests for agent_center.issue_queue — sequential FIFO."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_center.issue_queue import IssueQueue


class EnqueueTests(unittest.TestCase):
    def test_first_enqueue_promotes_to_current(self):
        with tempfile.TemporaryDirectory() as tmp:
            q = IssueQueue(Path(tmp) / "q.json")
            entry = q.enqueue("first issue")
            state = q.list_state()
            self.assertEqual(state["current"]["queue_id"], entry["queue_id"])
            self.assertEqual(state["current"]["step"], "investigating")
            self.assertEqual(state["pending"], [])

    def test_second_enqueue_appends_to_pending(self):
        with tempfile.TemporaryDirectory() as tmp:
            q = IssueQueue(Path(tmp) / "q.json")
            q.enqueue("a")
            second = q.enqueue("b")
            state = q.list_state()
            self.assertEqual(state["current"]["prompt"], "a")
            self.assertEqual(len(state["pending"]), 1)
            self.assertEqual(state["pending"][0]["queue_id"], second["queue_id"])

    def test_empty_prompt_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            q = IssueQueue(Path(tmp) / "q.json")
            with self.assertRaises(ValueError):
                q.enqueue("   ")


class CompleteTests(unittest.TestCase):
    def test_complete_promotes_next(self):
        with tempfile.TemporaryDirectory() as tmp:
            q = IssueQueue(Path(tmp) / "q.json")
            q.enqueue("a")
            q.enqueue("b")
            done = q.complete_current(outcome="resolved", issue_id="ISS-1")
            self.assertEqual(done["prompt"], "a")
            self.assertEqual(done["outcome"], "resolved")
            state = q.list_state()
            self.assertEqual(state["current"]["prompt"], "b")
            self.assertEqual(state["current"]["step"], "investigating")

    def test_complete_with_empty_queue_clears_current(self):
        with tempfile.TemporaryDirectory() as tmp:
            q = IssueQueue(Path(tmp) / "q.json")
            q.enqueue("only")
            q.complete_current()
            self.assertIsNone(q.list_state()["current"])

    def test_complete_unknown_outcome_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            q = IssueQueue(Path(tmp) / "q.json")
            q.enqueue("x")
            with self.assertRaises(ValueError):
                q.complete_current(outcome="???")


class CancelPendingTests(unittest.TestCase):
    def test_cancel_pending_removes_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            q = IssueQueue(Path(tmp) / "q.json")
            q.enqueue("a")
            second = q.enqueue("b")
            cancelled = q.cancel_pending(second["queue_id"])
            self.assertEqual(cancelled["outcome"], "cancelled")
            self.assertEqual(q.list_state()["pending"], [])

    def test_cannot_cancel_current_via_pending_api(self):
        with tempfile.TemporaryDirectory() as tmp:
            q = IssueQueue(Path(tmp) / "q.json")
            current = q.enqueue("a")
            with self.assertRaises(KeyError):
                q.cancel_pending(current["queue_id"])


class StepTests(unittest.TestCase):
    def test_update_step_only_for_current(self):
        with tempfile.TemporaryDirectory() as tmp:
            q = IssueQueue(Path(tmp) / "q.json")
            entry = q.enqueue("a")
            q.update_step(entry["queue_id"], "solution")
            self.assertEqual(q.list_state()["current"]["step"], "solution")

    def test_update_step_rejects_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            q = IssueQueue(Path(tmp) / "q.json")
            entry = q.enqueue("a")
            with self.assertRaises(ValueError):
                q.update_step(entry["queue_id"], "made-up")


if __name__ == "__main__":
    unittest.main()
