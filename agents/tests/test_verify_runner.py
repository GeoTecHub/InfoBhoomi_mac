"""Tests for the background VerifyRunner — start/snapshot/cancel."""
from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_center.verification_qa_agent import VerificationQAAgent, VerificationResult
from agent_center.verify_runner import VerifyRunner


class _FakeAgent:
    """Stand-in VerificationQAAgent that emits N log lines then completes."""

    def __init__(self, lines=("a","b","c"), block_secs=0.0):
        self.lines = lines
        self.block_secs = block_secs

    def verify(self, *, queue_id, committed_edit_ids, function_ids_to_rerun, log, is_cancelled):
        for line in self.lines:
            if is_cancelled():
                return VerificationResult(
                    queue_id=queue_id, started_at="t", status="cancelled",
                    overall="error", error="Cancelled by test",
                )
            log(line)
            if self.block_secs:
                time.sleep(self.block_secs)
        return VerificationResult(
            queue_id=queue_id, started_at="t", finished_at="t2",
            status="complete", overall="ok",
        )


class StartSnapshotTests(unittest.TestCase):
    def test_runs_to_completion_and_snapshots_logs(self):
        runner = VerifyRunner.singleton()
        runner.clear("Q-RUN-1")
        runner.start(
            queue_id="Q-RUN-1",
            committed_edit_ids=[], function_ids_to_rerun=[],
            agent=_FakeAgent(lines=("hello", "world")),
        )
        # Wait briefly for the daemon thread to finish.
        for _ in range(50):
            snap = runner.snapshot("Q-RUN-1")
            if not snap["running"]: break
            time.sleep(0.05)
        snap = runner.snapshot("Q-RUN-1")
        self.assertFalse(snap["running"])
        self.assertEqual(snap["status"], "complete")
        # Log has 2 lines, with timestamps prepended.
        self.assertEqual(len(snap["log"]), 2)
        self.assertTrue(any("hello" in line for line in snap["log"]))
        self.assertEqual(snap["log_offset"], 2)
        runner.clear("Q-RUN-1")

    def test_log_offset_returns_only_new_lines(self):
        runner = VerifyRunner.singleton()
        runner.clear("Q-RUN-2")
        runner.start(
            queue_id="Q-RUN-2",
            committed_edit_ids=[], function_ids_to_rerun=[],
            agent=_FakeAgent(lines=tuple(f"line{i}" for i in range(5))),
        )
        for _ in range(50):
            if not runner.snapshot("Q-RUN-2")["running"]: break
            time.sleep(0.05)
        first = runner.snapshot("Q-RUN-2", log_offset=0)
        self.assertEqual(len(first["log"]), 5)
        # Asking again from the new offset returns no new lines.
        empty = runner.snapshot("Q-RUN-2", log_offset=first["log_offset"])
        self.assertEqual(empty["log"], [])
        runner.clear("Q-RUN-2")

    def test_double_start_refused(self):
        runner = VerifyRunner.singleton()
        runner.clear("Q-RUN-3")
        # Use a slow fake agent so we can race.
        runner.start(
            queue_id="Q-RUN-3",
            committed_edit_ids=[], function_ids_to_rerun=[],
            agent=_FakeAgent(lines=("a","b","c"), block_secs=0.05),
        )
        second = runner.start(
            queue_id="Q-RUN-3",
            committed_edit_ids=[], function_ids_to_rerun=[],
            agent=_FakeAgent(),
        )
        self.assertFalse(second["ok"])
        # Drain
        for _ in range(50):
            if not runner.snapshot("Q-RUN-3")["running"]: break
            time.sleep(0.05)
        runner.clear("Q-RUN-3")

    def test_cancel_short_circuits(self):
        runner = VerifyRunner.singleton()
        runner.clear("Q-RUN-4")
        runner.start(
            queue_id="Q-RUN-4",
            committed_edit_ids=[], function_ids_to_rerun=[],
            agent=_FakeAgent(lines=("a","b","c"), block_secs=0.05),
        )
        runner.cancel("Q-RUN-4")
        for _ in range(50):
            if not runner.snapshot("Q-RUN-4")["running"]: break
            time.sleep(0.05)
        snap = runner.snapshot("Q-RUN-4")
        self.assertEqual(snap["status"], "cancelled")
        runner.clear("Q-RUN-4")


if __name__ == "__main__":
    unittest.main()
