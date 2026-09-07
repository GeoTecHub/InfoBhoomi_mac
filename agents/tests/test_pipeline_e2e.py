"""
End-to-end happy-path test of the self-healing pipeline.
=========================================================
Stubs out: LLM providers, subprocess.Popen (no real ng build / manage.py),
and uses an isolated tmp project tree so the test doesn't touch real source.

Drives the pipeline:
  enqueue → architect.investigate → reporter.report → solution_architect.propose
  → applier.preview/stage/commit → verification_qa_agent.verify
  → ChangeMemory + CostLedger assertions.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_center.applier import Applier
from agent_center.architect_agent import ArchitectAgent
from agent_center.change_memory import ChangeMemory
from agent_center.cost_ledger import CostLedger
from agent_center.investigators import (
    InvestigationFinding,
    InvestigationResult,
)
from agent_center.implementers import (
    BackendImplementer as BEImpl,
    DBMigrationImplementer,
    FrontendImplementer,
)
from agent_center.issue_queue import IssueQueue
from agent_center.reporter_agent import ReporterAgent
from agent_center.solution_architect_agent import SolutionArchitectAgent
from agent_center.structured_memory import StructuredMemory
from agent_center.verification_qa_agent import VerificationQAAgent


# ── Stubs ────────────────────────────────────────────────────────────────────

class _StubInvestigator:
    def __init__(self, layer, status, findings):
        self.layer = layer; self.status = status; self.findings = findings
    def investigate(self, sub):
        return InvestigationResult(
            layer=self.layer, status=self.status,
            findings=self.findings, inspected_subcomponents=[],
            elapsed_ms=0.1,
        )


class _StubProvider:
    name = "gemini"
    model = "gemini-2.5-flash"
    def __init__(self, response):
        self._response = response
        self.last_usage = {"input_tokens": 200, "output_tokens": 60,
                           "model": self.model, "provider": self.name}
    def generate_json(self, prompt, max_tokens=1500, temperature=0.2):
        return self._response


# ── E2E test ─────────────────────────────────────────────────────────────────

class HappyPathE2ETests(unittest.TestCase):
    def test_full_pipeline(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            # Build an isolated project tree.
            project = tmp / "project"; project.mkdir()
            fe_root = project / "fe"; fe_root.mkdir()
            be_root = project / "be"; be_root.mkdir()
            (be_root / "user").mkdir()
            (be_root / "user" / "migrations").mkdir()
            target = fe_root / "x.ts"
            target.write_text("OLD\n")
            (fe_root / "package.json").write_text('{"scripts": {"build": "ng build"}}')

            # State files inside tmp.
            ledger_path  = tmp / "ledger.json"
            cost_path    = tmp / "cost.json"
            mem_path     = tmp / "mem.json"
            queue_path   = tmp / "q.json"
            backups_dir  = tmp / "backups"
            staging_dir  = tmp / "staging"

            # ── 1. Enqueue ────────────────────────────────────────────────
            queue = IssueQueue(queue_path)
            entry = queue.enqueue("RRR owner not showing")
            self.assertEqual(queue.list_state()["current"]["queue_id"], entry["queue_id"])

            # ── 2. Architect.investigate ──────────────────────────────────
            fe_finding = InvestigationFinding(
                layer="frontend", severity="warning", title="Suspicious",
                affected_subcomponent="fe/x.ts",
                evidence={"file": "fe/x.ts"},
            )
            arch = ArchitectAgent(
                fe_investigator=_StubInvestigator("frontend", "warning", [fe_finding]),
                be_investigator=_StubInvestigator("backend",  "ok",       []),
                db_investigator=_StubInvestigator("db",       "ok",       []),
                memory=StructuredMemory(mem_path),
                change_memory=ChangeMemory(ledger_path),
            )
            out = arch.investigate(queue_id=entry["queue_id"], prompt=entry["prompt"])
            self.assertTrue(out.issue["issue_id"].startswith("ISS-"))

            # ── 3. Reporter — stubbed LLM ─────────────────────────────────
            reporter_resp = {
                "headline": "Frontend has a suspicious import",
                "overall":  "warning",
                "frontend": {"status": "warning", "headline": "fe", "bullets": ["x"]},
                "backend":  {"status": "ok",      "headline": "be", "bullets": []},
                "database": {"status": "ok",      "headline": "db", "bullets": []},
                "next_actions": ["look at x.ts"],
            }
            with patch("agent_center.reporter_agent.pick_provider") as pp, \
                 patch("agent_center.reporter_agent.CostLedger") as CLR:
                pp.return_value = _StubProvider(reporter_resp)
                CLR.return_value = CostLedger(cost_path)
                report = ReporterAgent().report(out, llm_choice="gemini")
            self.assertFalse(report.fallback)
            self.assertEqual(report.overall, "warning")

            # ── 4. Solution Architect — stubbed LLM ───────────────────────
            solution_resp = {
                "headline": "Replace x.ts with a safer import.",
                "summary":  "Update the relative import in x.ts.",
                "items": [
                    {
                        "layer": "frontend",
                        "sub_component": "x.ts",
                        "file_path": "fe/x.ts",
                        "rationale": "Unresolved relative import.",
                        "proposed_diff": "@@ -1 +1 @@\n-OLD\n+NEW",
                        "proposed_full_text": "NEW\n",
                        "risk_notes": ["one-line change"],
                        "tests_to_rerun": ["rrr.lifecycle"],
                        "confidence": "high",
                    }
                ],
            }
            with patch("agent_center.solution_architect_agent.pick_provider") as pp, \
                 patch("agent_center.solution_architect_agent.CostLedger") as CLS:
                pp.return_value = _StubProvider(solution_resp)
                CLS.return_value = CostLedger(cost_path)
                plan = SolutionArchitectAgent().propose(architect_output=out, llm_choice="gemini")
            self.assertFalse(plan.fallback)
            self.assertEqual(len(plan.items), 1)

            # ── 5. Applier: preview → stage → commit ─────────────────────
            ledger = ChangeMemory(ledger_path)
            fe_impl = FrontendImplementer(project_root=project, allowed_root=fe_root,
                                          backups_dir=backups_dir, staging_dir=staging_dir,
                                          change_memory=ledger)
            be_impl = BEImpl(project_root=project, allowed_root=be_root,
                             backups_dir=backups_dir, staging_dir=staging_dir,
                             change_memory=ledger)
            mig_impl = DBMigrationImplementer(project_root=project,
                                              allowed_root=be_root / "user" / "migrations",
                                              backups_dir=backups_dir, staging_dir=staging_dir,
                                              change_memory=ledger)
            applier = Applier(fe=fe_impl, be=be_impl, mig=mig_impl, change_memory=ledger)

            previews = applier.preview(plan.items)
            self.assertTrue(previews[0]["in_scope"])
            self.assertTrue(previews[0]["has_proposal"])

            stage_batch = applier.stage(plan.items, queue_id=entry["queue_id"])
            self.assertEqual(len(stage_batch.staged), 1)
            self.assertEqual(target.read_text(), "OLD\n")  # not committed yet

            commit_batch = applier.commit(stage_batch.staged, linked_run_id=entry["queue_id"])
            self.assertTrue(commit_batch.results[0].ok)
            self.assertEqual(target.read_text(), "NEW\n")
            edit_id = commit_batch.results[0].edit_id

            # ── 6. Verify (stubbed subprocess) ────────────────────────────
            class _FakeProc:
                def __init__(self, *args, **kwargs):
                    self.stdout = iter(["compiling...\n", "Build at: dist/...\n"])
                    self.returncode = 0
                def wait(self, timeout=None): return 0
                def kill(self): pass

            agent = VerificationQAAgent(change_memory=ledger, fe_root=fe_root, be_root=be_root)
            with patch("agent_center.verification_qa_agent.shutil.which", return_value="/usr/bin/npm"), \
                 patch("agent_center.verification_qa_agent.subprocess.Popen", _FakeProc):
                vresult = agent.verify(
                    queue_id=entry["queue_id"],
                    committed_edit_ids=[edit_id],
                    function_ids_to_rerun=[],
                    log=lambda _l: None,
                )
            self.assertEqual(vresult.status, "complete")
            self.assertEqual(vresult.frontend.status, "ok")

            # ChangeMemory shows the edit as passed.
            persisted = ChangeMemory(ledger_path).get_edit(edit_id)
            self.assertEqual(persisted["verification_outcome"], "passed")

            # ── 7. CostLedger has two calls (reporter + solution_architect) ──
            cost_calls = CostLedger(cost_path).all_calls()
            self.assertEqual(len(cost_calls), 2)
            steps = sorted(c["step"] for c in cost_calls)
            self.assertEqual(steps, ["reporter", "solution_architect"])

            # ── 8. Round complete ────────────────────────────────────────
            queue.complete_current(outcome="resolved", issue_id=out.issue["issue_id"])
            self.assertIsNone(queue.list_state()["current"])


if __name__ == "__main__":
    unittest.main()
