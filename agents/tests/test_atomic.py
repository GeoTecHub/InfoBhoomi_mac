"""Tests for agent_center._atomic — atomic write + cross-platform lock."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_center._atomic import atomic_write_json, file_lock, read_json


class AtomicWriteTests(unittest.TestCase):
    def test_atomic_write_creates_file_with_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "out.json"
            atomic_write_json(path, {"a": 1, "b": [2, 3]})
            self.assertTrue(path.exists())
            self.assertEqual(json.loads(path.read_text()), {"a": 1, "b": [2, 3]})

    def test_atomic_write_overwrites_existing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "out.json"
            path.write_text('{"old": true}')
            atomic_write_json(path, {"new": True})
            self.assertEqual(json.loads(path.read_text()), {"new": True})

    def test_atomic_write_creates_parent_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "deeper" / "still" / "out.json"
            atomic_write_json(path, {"x": 1})
            self.assertTrue(path.exists())

    def test_atomic_write_does_not_leave_tmpfile(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "out.json"
            atomic_write_json(path, {"x": 1})
            leftovers = [p for p in Path(tmp).iterdir() if p.name.startswith(".out.json")]
            self.assertEqual(leftovers, [])


class ReadJsonTests(unittest.TestCase):
    def test_returns_default_when_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(read_json(Path(tmp) / "nope.json", default={"d": 1}), {"d": 1})

    def test_returns_default_when_corrupt(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text("{not json")
            self.assertEqual(read_json(path, default=[]), [])


class FileLockTests(unittest.TestCase):
    def test_lock_serialises_concurrent_writers(self):
        """Two threads incrementing the same JSON counter must not race."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "counter.json"
            atomic_write_json(path, {"n": 0})

            def bump():
                for _ in range(50):
                    with file_lock(path):
                        data = read_json(path, default={"n": 0})
                        data["n"] += 1
                        atomic_write_json(path, data)

            threads = [threading.Thread(target=bump) for _ in range(4)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            final = read_json(path)
            self.assertEqual(final["n"], 4 * 50)

    def test_lock_released_on_exception(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "x.json"
            try:
                with file_lock(path):
                    raise RuntimeError("boom")
            except RuntimeError:
                pass
            # We should be able to acquire again immediately.
            with file_lock(path):
                pass


if __name__ == "__main__":
    unittest.main()
