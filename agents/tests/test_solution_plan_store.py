"""Tests for SolutionPlanStore."""
from __future__ import annotations

import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_center.solution_plan_store import SolutionPlanStore


class StoreTests(unittest.TestCase):
    def test_put_get_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = SolutionPlanStore(Path(tmp) / "p.json")
            s.put("Q-1", {"queue_id": "Q-1", "headline": "h", "items": [], "generated_at": "2026-05-05T00:00:00Z"})
            self.assertEqual(s.get("Q-1")["headline"], "h")

    def test_get_returns_none_for_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = SolutionPlanStore(Path(tmp) / "p.json")
            self.assertIsNone(s.get("missing"))

    def test_delete_removes_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = SolutionPlanStore(Path(tmp) / "p.json")
            s.put("Q-1", {"queue_id": "Q-1"})
            self.assertTrue(s.delete("Q-1"))
            self.assertIsNone(s.get("Q-1"))
            self.assertFalse(s.delete("Q-1"))

    def test_concurrent_puts_serialised(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "p.json"
            def write(i):
                s = SolutionPlanStore(path)
                s.put(f"Q-{i}", {"queue_id": f"Q-{i}", "headline": str(i), "generated_at": f"2026-05-05T00:00:{i:02d}Z"})
            threads = [threading.Thread(target=write, args=(i,)) for i in range(8)]
            for t in threads: t.start()
            for t in threads: t.join()
            final = SolutionPlanStore(path)
            self.assertEqual(len(final.all()), 8)

    def test_put_requires_queue_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = SolutionPlanStore(Path(tmp) / "p.json")
            with self.assertRaises(ValueError):
                s.put("", {"x": 1})


if __name__ == "__main__":
    unittest.main()
