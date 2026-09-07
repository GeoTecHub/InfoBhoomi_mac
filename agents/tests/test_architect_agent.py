"""Tests for ArchitectAgent — coordinator + investigator dispatch."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_center.architect_agent import ArchitectAgent, InvestigationPlan
from agent_center.change_memory import ChangeMemory
from agent_center.investigators import (
    BackendInvestigator,
    DBInvestigator,
    FrontendInvestigator,
    InvestigationResult,
)
from agent_center.structured_memory import StructuredMemory


class _StubInvestigator:
    """Returns a fixed InvestigationResult; lets us test Architect in isolation."""

    def __init__(self, layer, status, count):
        self.layer  = layer
        self.status = status
        self.count  = count
        self.received = None

    def investigate(self, subcomponents):
        self.received = list(subcomponents)
        return InvestigationResult(
            layer=self.layer,
            status=self.status,
            findings=[],
            inspected_subcomponents=[getattr(sc, "path", getattr(sc, "table", "?")) for sc in self.received],
            elapsed_ms=1.0,
        )


class ArchitectDispatchTests(unittest.TestCase):
    def _arch(self, tmp):
        return ArchitectAgent(
            fe_investigator=_StubInvestigator("frontend", "warning", 0),
            be_investigator=_StubInvestigator("backend",  "ok",      0),
            db_investigator=_StubInvestigator("db",       "ok",      0),
            memory=StructuredMemory(Path(tmp) / "m.json"),
            change_memory=ChangeMemory(Path(tmp) / "l.json"),
            max_routes=3,
        )

    def test_routes_rrr_prompt_to_rrr_lifecycle(self):
        with tempfile.TemporaryDirectory() as tmp:
            arch = self._arch(tmp)
            out  = arch.investigate(queue_id="Q-1", prompt="RRR owner is not showing")
            self.assertIn("rrr.lifecycle", out.plan.selected_function_ids)

    def test_each_investigator_receives_its_subcomponents(self):
        with tempfile.TemporaryDirectory() as tmp:
            arch = self._arch(tmp)
            out  = arch.investigate(queue_id="Q-2", prompt="parcel polygon save failing")
            self.assertGreater(len(arch.fe.received), 0)
            self.assertGreater(len(arch.be.received), 0)
            self.assertGreaterEqual(len(arch.db.received), 0)
            self.assertEqual(out.fe.layer, "frontend")
            self.assertEqual(out.be.layer, "backend")
            self.assertEqual(out.db.layer, "db")

    def test_plan_contains_routes_and_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            arch = self._arch(tmp)
            out  = arch.investigate(queue_id="Q-3", prompt="parcel polygon save failing")
            self.assertIsInstance(out.plan, InvestigationPlan)
            self.assertTrue(out.plan.routes)
            self.assertTrue(out.plan.component_map_entries)

    def test_persists_an_issue(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem  = StructuredMemory(Path(tmp) / "m.json")
            arch = ArchitectAgent(
                fe_investigator=_StubInvestigator("frontend", "ok", 0),
                be_investigator=_StubInvestigator("backend",  "ok", 0),
                db_investigator=_StubInvestigator("db",       "ok", 0),
                memory=mem,
                change_memory=ChangeMemory(Path(tmp) / "l.json"),
            )
            out = arch.investigate(queue_id="Q-4", prompt="layer panel not rendering")
            self.assertEqual(out.issue["symptom"], "layer panel not rendering")
            self.assertEqual(len(mem.list_issues()), 1)

    def test_includes_prior_failed_strategies_from_change_memory(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = ChangeMemory(Path(tmp) / "l.json")
            edit = ledger.record_edit(
                agent="BackendImplementer",
                component="rrr.views.py",
                file_path="InfoBhoomi_Backend_dev2/user/views/rrr.py",
                before_text="x", after_text="y",
                symptom_fingerprint="fp",
            )
            ledger.update_verification(edit["edit_id"], "failed")

            arch = ArchitectAgent(
                fe_investigator=_StubInvestigator("frontend", "ok", 0),
                be_investigator=_StubInvestigator("backend",  "ok", 0),
                db_investigator=_StubInvestigator("db",       "ok", 0),
                memory=StructuredMemory(Path(tmp) / "m.json"),
                change_memory=ledger,
            )
            out = arch.investigate(queue_id="Q-5", prompt="RRR owner is not showing")
            file_paths = [p["file_path"] for p in out.plan.prior_failed_strategies]
            self.assertIn("InfoBhoomi_Backend_dev2/user/views/rrr.py", file_paths)


if __name__ == "__main__":
    unittest.main()
