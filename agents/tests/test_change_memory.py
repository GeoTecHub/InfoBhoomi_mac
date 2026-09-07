"""Tests for agent_center.change_memory — per-edit ledger."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_center.change_memory import ChangeMemory, hash_text


class HashTests(unittest.TestCase):
    def test_hash_is_stable_and_prefixed(self):
        h = hash_text("hello")
        self.assertTrue(h.startswith("sha256:"))
        self.assertEqual(h, hash_text("hello"))
        self.assertNotEqual(h, hash_text("hello!"))


class RecordEditTests(unittest.TestCase):
    def test_record_edit_persists_and_increments(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = ChangeMemory(Path(tmp) / "ledger.json")
            edit = ledger.record_edit(
                agent="BackendImplementer",
                component="rrr.views.py::link_ba_unit",
                file_path="InfoBhoomi_Backend_dev2/user/views/rrr.py",
                before_text="old",
                after_text="new",
                diff="--- a\n+++ b\n",
                symptom_fingerprint="rrr.lifecycle|backend|/rrr_data_get|GET|200|owner",
                linked_issue_id="ISS-1",
                llm="claude-sonnet-4-6",
            )
            self.assertTrue(edit["edit_id"].startswith("EDIT-"))
            self.assertEqual(edit["before_hash"], hash_text("old"))
            self.assertEqual(edit["after_hash"], hash_text("new"))
            self.assertEqual(edit["verification_outcome"], "pending")
            self.assertEqual(len(edit["fingerprint_hash"]), 12)

            # Reload from disk, confirm persistence
            ledger2 = ChangeMemory(Path(tmp) / "ledger.json")
            self.assertEqual(len(ledger2.all_edits()), 1)

    def test_update_verification_changes_outcome(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = ChangeMemory(Path(tmp) / "ledger.json")
            edit = ledger.record_edit(
                agent="X", component="c", file_path="f",
                before_text="a", after_text="b",
            )
            updated = ledger.update_verification(edit["edit_id"], "passed", {"foo": 1})
            self.assertEqual(updated["verification_outcome"], "passed")
            self.assertEqual(updated["verification_evidence"], {"foo": 1})

    def test_update_verification_rejects_unknown_outcome(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = ChangeMemory(Path(tmp) / "ledger.json")
            edit = ledger.record_edit(agent="X", component="c", file_path="f",
                                     before_text="a", after_text="b")
            with self.assertRaises(ValueError):
                ledger.update_verification(edit["edit_id"], "weird")


class WasAttemptedTests(unittest.TestCase):
    def test_was_attempted_finds_matching_fingerprint(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = ChangeMemory(Path(tmp) / "ledger.json")
            ledger.record_edit(
                agent="X", component="c", file_path="rrr.py",
                before_text="a", after_text="b",
                symptom_fingerprint="fp1",
            )
            ledger.record_edit(
                agent="X", component="c", file_path="rrr.py",
                before_text="b", after_text="c",
                symptom_fingerprint="fp2",
            )
            self.assertEqual(len(ledger.was_attempted("fp1")), 1)
            self.assertEqual(len(ledger.was_attempted("fp1", "rrr.py")), 1)
            self.assertEqual(len(ledger.was_attempted("fp1", "other.py")), 0)
            self.assertEqual(len(ledger.was_attempted("nope")), 0)

    def test_rolled_back_edits_excluded_from_was_attempted(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = ChangeMemory(Path(tmp) / "ledger.json")
            edit = ledger.record_edit(
                agent="X", component="c", file_path="f",
                before_text="a", after_text="b",
                symptom_fingerprint="fp",
            )
            ledger.mark_rolled_back(edit["edit_id"])
            self.assertEqual(ledger.was_attempted("fp"), [])

    def test_failed_strategies_for(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = ChangeMemory(Path(tmp) / "ledger.json")
            e1 = ledger.record_edit(agent="X", component="c", file_path="f",
                                   before_text="a", after_text="b")
            ledger.update_verification(e1["edit_id"], "failed")
            e2 = ledger.record_edit(agent="X", component="c", file_path="f",
                                   before_text="b", after_text="c")
            ledger.update_verification(e2["edit_id"], "passed")
            failed = ledger.failed_strategies_for("f")
            self.assertEqual(len(failed), 1)
            self.assertEqual(failed[0]["edit_id"], e1["edit_id"])


if __name__ == "__main__":
    unittest.main()
