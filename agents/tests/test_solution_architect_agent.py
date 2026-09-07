"""Tests for SolutionArchitectAgent — fallback + LLM stub + user-edit merge."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_center.architect_agent import ArchitectAgent
from agent_center.change_memory import ChangeMemory
from agent_center.investigators import InvestigationFinding, InvestigationResult
from agent_center.solution_architect_agent import (
    SolutionArchitectAgent,
    SolutionItem,
    SolutionPlan,
    merge_user_edits,
)
from agent_center.structured_memory import StructuredMemory


class _Stub:
    def __init__(self, layer, status, findings=None):
        self.layer    = layer
        self.status   = status
        self.findings = findings or []
    def investigate(self, sub):
        return InvestigationResult(
            layer=self.layer, status=self.status,
            findings=self.findings, inspected_subcomponents=[],
            elapsed_ms=0.5,
        )


def _make_output(tmp, prompt="rrr owner missing"):
    fe_finding = InvestigationFinding(
        layer="frontend", severity="warning",
        title="Suspicious relative imports",
        affected_subcomponent="infoBhoomi-frontedend-div2/src/app/components/dialogs/add-right-holder",
        evidence={"file": "infoBhoomi-frontedend-div2/src/app/components/dialogs/add-right-holder/foo.ts"},
    )
    be_finding = InvestigationFinding(
        layer="backend", severity="error",
        title="Python syntax error",
        affected_subcomponent="InfoBhoomi_Backend_dev2/user/views/rrr.py",
        evidence={"file": "InfoBhoomi_Backend_dev2/user/views/rrr.py"},
    )
    arch = ArchitectAgent(
        fe_investigator=_Stub("frontend", "warning", [fe_finding]),
        be_investigator=_Stub("backend",  "error",   [be_finding]),
        db_investigator=_Stub("db",       "ok",      []),
        memory=StructuredMemory(Path(tmp) / "m.json"),
        change_memory=ChangeMemory(Path(tmp) / "l.json"),
    )
    return arch.investigate(queue_id="Q-T", prompt=prompt)


class FallbackTests(unittest.TestCase):
    def test_fallback_creates_one_item_per_warning_or_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = _make_output(tmp)
            with patch("agent_center.solution_architect_agent.pick_provider") as pp:
                from agent_center.ai_provider import AIProviderError
                pp.side_effect = AIProviderError("no key")
                plan = SolutionArchitectAgent().propose(architect_output=out)
            self.assertTrue(plan.fallback)
            self.assertEqual(len(plan.items), 2)  # one FE warning + one BE error
            layers = sorted({i.layer for i in plan.items})
            self.assertEqual(layers, ["backend", "frontend"])
            for item in plan.items:
                self.assertEqual(item.confidence, "low")
                self.assertEqual(item.proposed_diff, "")
                self.assertTrue(item.fingerprint)


class LLMPathTests(unittest.TestCase):
    def test_llm_returns_plan_with_grouped_items(self):
        class _StubProvider:
            name = "claude"
            model = "claude-sonnet-4-6"
            def generate_json(self, prompt, max_tokens=4500, temperature=0.2):
                return {
                    "headline": "Patch RRR view to populate ba_unit_id.",
                    "summary":  "The /rrr_data_get/ endpoint filters by ba_unit_id which is null for new parcels.",
                    "items": [
                        {
                            "layer": "backend",
                            "sub_component": "rrr.views.link_ba_unit",
                            "file_path": "InfoBhoomi_Backend_dev2/user/views/rrr.py",
                            "rationale": "Backfill ba_unit_id when missing.",
                            "proposed_diff": "@@ -1 +1 @@\n-old\n+new",
                            "risk_notes": ["touches hot path"],
                            "tests_to_rerun": ["rrr.lifecycle"],
                            "confidence": "medium",
                        },
                        {
                            "layer": "migration",
                            "sub_component": "0042_backfill",
                            "file_path": "InfoBhoomi_Backend_dev2/user/migrations/0042_backfill.py",
                            "rationale": "Backfill historical rows.",
                            "proposed_diff": "",
                            "proposed_full_text": "from django.db import migrations\n",
                            "risk_notes": ["large table — run during off-peak"],
                            "tests_to_rerun": [],
                            "confidence": "high",
                        },
                    ],
                }
        with tempfile.TemporaryDirectory() as tmp:
            out = _make_output(tmp)
            with patch("agent_center.solution_architect_agent.pick_provider") as pp:
                pp.return_value = _StubProvider()
                plan = SolutionArchitectAgent().propose(architect_output=out, llm_choice="claude")
            self.assertFalse(plan.fallback)
            self.assertEqual(plan.llm_used, "claude")
            self.assertEqual(plan.headline, "Patch RRR view to populate ba_unit_id.")
            self.assertEqual(len(plan.items), 2)
            grouped = plan.items_by_layer()
            self.assertEqual(len(grouped["backend"]), 1)
            self.assertEqual(len(grouped["migration"]), 1)
            for item in plan.items:
                self.assertTrue(item.fingerprint)
                self.assertTrue(item.item_id.startswith("SI-"))

    def test_llm_drops_invalid_layer(self):
        class _StubProvider:
            name  = "claude"
            model = "claude-sonnet-4-6"
            def generate_json(self, prompt, max_tokens=4500, temperature=0.2):
                return {
                    "headline": "h", "summary": "s",
                    "items": [
                        {"layer": "frontend", "file_path": "infoBhoomi-frontedend-div2/x.ts", "rationale": "r", "proposed_diff": "d", "confidence": "high"},
                        {"layer": "spaceship", "file_path": "x", "rationale": "y", "proposed_diff": "z", "confidence": "high"},
                        {"layer": "backend",  "file_path": "", "rationale": "missing path", "proposed_diff": "z", "confidence": "high"},
                    ],
                }
        with tempfile.TemporaryDirectory() as tmp:
            out = _make_output(tmp)
            with patch("agent_center.solution_architect_agent.pick_provider") as pp:
                pp.return_value = _StubProvider()
                plan = SolutionArchitectAgent().propose(architect_output=out, llm_choice="claude")
            self.assertEqual(len(plan.items), 1)
            self.assertEqual(plan.items[0].layer, "frontend")


class MergeUserEditsTests(unittest.TestCase):
    def test_merge_overlays_editable_fields(self):
        plan = {
            "queue_id": "Q-1",
            "items": [
                {
                    "item_id": "SI-A",
                    "layer": "backend", "sub_component": "x", "file_path": "f.py",
                    "rationale": "old", "proposed_diff": "", "proposed_full_text": "",
                    "risk_notes": [], "tests_to_rerun": [], "confidence": "medium",
                    "fingerprint": "fp", "user_edited": False,
                }
            ],
            "user_amended": False,
        }
        merged = merge_user_edits(plan, [
            {"item_id": "SI-A", "rationale": "new", "proposed_diff": "diff!", "confidence": "high"}
        ])
        item = merged["items"][0]
        self.assertEqual(item["rationale"], "new")
        self.assertEqual(item["proposed_diff"], "diff!")
        self.assertEqual(item["confidence"], "high")
        self.assertTrue(item["user_edited"])
        self.assertTrue(merged["user_amended"])

    def test_merge_ignores_unknown_item(self):
        plan = {"items": [{"item_id": "SI-A", "rationale": "x", "user_edited": False}]}
        merged = merge_user_edits(plan, [{"item_id": "SI-Z", "rationale": "y"}])
        self.assertEqual(merged["items"][0]["rationale"], "x")
        self.assertFalse(merged["items"][0]["user_edited"])

    def test_merge_ignores_non_editable_field(self):
        plan = {"items": [{"item_id": "SI-A", "file_path": "old.py", "rationale": "r", "user_edited": False}]}
        merged = merge_user_edits(plan, [{"item_id": "SI-A", "file_path": "evil.py"}])
        self.assertEqual(merged["items"][0]["file_path"], "old.py")


if __name__ == "__main__":
    unittest.main()
