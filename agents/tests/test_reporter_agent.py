"""Tests for ReporterAgent — fallback path + LLM path with a stub provider."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_center.architect_agent import ArchitectAgent
from agent_center.change_memory import ChangeMemory
from agent_center.investigators import InvestigationResult
from agent_center.reporter_agent import ReporterAgent
from agent_center.structured_memory import StructuredMemory


class _Stub:
    def __init__(self, layer, status):
        self.layer = layer
        self.status = status

    def investigate(self, sub):
        return InvestigationResult(
            layer=self.layer, status=self.status,
            findings=[], inspected_subcomponents=[], elapsed_ms=0.5,
        )


def _make_output(tmp, prompt="rrr owner missing"):
    arch = ArchitectAgent(
        fe_investigator=_Stub("frontend", "warning"),
        be_investigator=_Stub("backend",  "ok"),
        db_investigator=_Stub("db",       "ok"),
        memory=StructuredMemory(Path(tmp) / "m.json"),
        change_memory=ChangeMemory(Path(tmp) / "l.json"),
    )
    return arch.investigate(queue_id="Q-T", prompt=prompt)


class FallbackTests(unittest.TestCase):
    def test_no_llm_falls_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = _make_output(tmp)
            with patch("agent_center.reporter_agent.pick_provider") as pp:
                from agent_center.ai_provider import AIProviderError
                pp.side_effect = AIProviderError("no key")
                rep = ReporterAgent().report(out)
            self.assertTrue(rep.fallback)
            self.assertIn("no key", rep.fallback_reason)
            self.assertTrue(rep.body_markdown)
            self.assertEqual(len(rep.layers), 3)

    def test_overall_reflects_worst_layer(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = _make_output(tmp)
            # Force backend to be "error" to verify aggregation.
            out.be.status = "error"
            with patch("agent_center.reporter_agent.pick_provider") as pp:
                from agent_center.ai_provider import AIProviderError
                pp.side_effect = AIProviderError("no key")
                rep = ReporterAgent().report(out)
            self.assertEqual(rep.overall, "error")


class LLMPathTests(unittest.TestCase):
    def test_llm_response_populates_layers(self):
        class _StubProvider:
            name = "gemini"
            model = "gemini-2.5-flash"
            def generate_json(self, prompt, max_tokens=1500, temperature=0.2):
                return {
                    "headline": "Backend is the suspect.",
                    "overall":  "warning",
                    "frontend": {"status": "ok",      "headline": "Looks healthy.",       "bullets": ["No issues"]},
                    "backend":  {"status": "warning", "headline": "API returns empty list.", "bullets": ["Check view filter"]},
                    "database": {"status": "ok",      "headline": "Tables reachable.",     "bullets": ["row_count: 12"]},
                    "next_actions": ["Inspect rrr_data_get/", "Verify ba_unit_id"],
                }
        with tempfile.TemporaryDirectory() as tmp:
            out = _make_output(tmp)
            with patch("agent_center.reporter_agent.pick_provider") as pp:
                pp.return_value = _StubProvider()
                rep = ReporterAgent().report(out, llm_choice="gemini")
            self.assertFalse(rep.fallback)
            self.assertEqual(rep.llm_used, "gemini")
            self.assertEqual(rep.overall, "warning")
            self.assertEqual(len(rep.layers), 3)
            self.assertEqual(rep.layers[1].status, "warning")
            self.assertIn("Inspect rrr_data_get/", rep.next_actions)


if __name__ == "__main__":
    unittest.main()
