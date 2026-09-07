"""Tests for VerificationQAAgent — per-layer aggregation, ChangeMemory propagation."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_center.change_memory import ChangeMemory
from agent_center.verification_qa_agent import (
    LayerVerification,
    VerificationQAAgent,
    VerificationResult,
)


class _Recorder:
    def __init__(self): self.lines = []
    def __call__(self, line): self.lines.append(line)


class WorstAggregationTests(unittest.TestCase):
    def test_skipped_when_no_layers_touched_and_no_function_ids(self):
        with tempfile.TemporaryDirectory() as t:
            ledger = ChangeMemory(Path(t) / "l.json")
            agent  = VerificationQAAgent(change_memory=ledger)
            res = agent.verify(queue_id="Q-1")
            self.assertEqual(res.status, "complete")
            self.assertEqual(res.frontend.status, "skipped")
            self.assertEqual(res.backend.status,  "skipped")
            self.assertEqual(res.db.status,       "skipped")
            self.assertEqual(res.overall, "skipped")


class CancellationTests(unittest.TestCase):
    def test_cancellation_short_circuits(self):
        with tempfile.TemporaryDirectory() as t:
            ledger = ChangeMemory(Path(t) / "l.json")
            edit = ledger.record_edit(
                agent="FrontendImplementer", component="x",
                file_path="infoBhoomi-frontedend-div2/src/app/x.ts",
                before_text="", after_text="x",
            )
            log = _Recorder()
            agent = VerificationQAAgent(change_memory=ledger)
            res = agent.verify(
                queue_id="Q-1",
                committed_edit_ids=[edit["edit_id"]],
                log=log, is_cancelled=lambda: True,
            )
            self.assertEqual(res.status, "cancelled")
            self.assertIn("Cancelled", res.error)


class FrontendSmokeTests(unittest.TestCase):
    def test_fe_smoke_skipped_when_no_build_tool(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            ledger = ChangeMemory(tmp / "l.json")
            edit = ledger.record_edit(
                agent="FrontendImplementer", component="x",
                file_path="infoBhoomi-frontedend-div2/src/app/x.ts",
                before_text="", after_text="x",
                symptom_fingerprint="fp",
            )
            agent = VerificationQAAgent(change_memory=ledger, fe_root=tmp / "no_fe")
            with patch("agent_center.verification_qa_agent.shutil.which", return_value=None):
                res = agent.verify(queue_id="Q-1", committed_edit_ids=[edit["edit_id"]])
            self.assertEqual(res.frontend.status, "skipped")

    def test_fe_smoke_succeeds_when_subprocess_returns_zero(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            (tmp / "fe").mkdir()
            (tmp / "fe" / "package.json").write_text('{"scripts": {"build": "ng build"}}')
            ledger = ChangeMemory(tmp / "l.json")
            edit = ledger.record_edit(
                agent="FrontendImplementer", component="x",
                file_path="infoBhoomi-frontedend-div2/src/app/x.ts",
                before_text="", after_text="x",
            )
            agent = VerificationQAAgent(change_memory=ledger, fe_root=tmp / "fe")

            class _FakeProc:
                def __init__(self, *_, **__): self.stdout = iter(["compiling...\n", "Build at: dist/...\n"]); self.returncode = 0
                def wait(self, timeout=None): return 0
                def kill(self): pass
            with patch("agent_center.verification_qa_agent.shutil.which", return_value="/usr/bin/npm"), \
                 patch("agent_center.verification_qa_agent.subprocess.Popen", _FakeProc):
                res = agent.verify(queue_id="Q-1", committed_edit_ids=[edit["edit_id"]])
            self.assertEqual(res.frontend.status, "ok")
            self.assertEqual(res.frontend.return_code, 0)
            updated = ledger.get_edit(edit["edit_id"])
            self.assertEqual(updated["verification_outcome"], "passed")

    def test_fe_smoke_failure_marks_edit_failed(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            (tmp / "fe").mkdir()
            (tmp / "fe" / "package.json").write_text('{"scripts": {"build": "ng build"}}')
            ledger = ChangeMemory(tmp / "l.json")
            edit = ledger.record_edit(
                agent="FrontendImplementer", component="x",
                file_path="infoBhoomi-frontedend-div2/src/app/x.ts",
                before_text="", after_text="x",
            )
            agent = VerificationQAAgent(change_memory=ledger, fe_root=tmp / "fe")

            class _FakeProc:
                def __init__(self, *_, **__): self.stdout = iter(["error TS1005\n"]); self.returncode = 1
                def wait(self, timeout=None): return 1
                def kill(self): pass
            with patch("agent_center.verification_qa_agent.shutil.which", return_value="/usr/bin/npm"), \
                 patch("agent_center.verification_qa_agent.subprocess.Popen", _FakeProc):
                res = agent.verify(queue_id="Q-1", committed_edit_ids=[edit["edit_id"]])
            self.assertEqual(res.frontend.status, "error")
            self.assertEqual(res.overall, "error")
            self.assertEqual(ledger.get_edit(edit["edit_id"])["verification_outcome"], "failed")


class BackendSmokeTests(unittest.TestCase):
    def test_py_compile_failure_marks_layer_error(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            project = tmp / "project"; project.mkdir()
            be = project / "be"; be.mkdir()
            broken = project / "be_broken.py"
            broken.write_text("def x(:\n  pass\n")  # syntax error

            ledger = ChangeMemory(tmp / "l.json")
            edit = ledger.record_edit(
                agent="BackendImplementer", component="x",
                file_path="be_broken.py", before_text="", after_text="bad",
            )
            agent = VerificationQAAgent(change_memory=ledger, be_root=be)
            with patch("agent_center.verification_qa_agent.PROJECT_ROOT", project):
                res = agent.verify(queue_id="Q-1", committed_edit_ids=[edit["edit_id"]])
            self.assertEqual(res.backend.status, "error")
            self.assertEqual(ledger.get_edit(edit["edit_id"])["verification_outcome"], "failed")


if __name__ == "__main__":
    unittest.main()
