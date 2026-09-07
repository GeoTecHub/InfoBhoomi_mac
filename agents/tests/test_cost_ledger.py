"""Tests for CostLedger + estimate_cost_usd + Reporter/SolutionArchitect wiring."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_center.cost_ledger import CostLedger, estimate_cost_usd


class EstimateTests(unittest.TestCase):
    def test_known_model(self):
        # Claude sonnet: $3 / 1M input, $15 / 1M output
        # 1_000_000 input + 100_000 output -> 3 + 1.5 = 4.5
        self.assertAlmostEqual(estimate_cost_usd("claude-sonnet-4-6", 1_000_000, 100_000), 4.5)

    def test_unknown_model_returns_zero(self):
        self.assertEqual(estimate_cost_usd("ghost-model-9999", 100_000, 50_000), 0.0)

    def test_env_override(self):
        with patch.dict("os.environ", {"IB_AGENT_LLM_RATE_GEMINI_2_5_FLASH": "1.0,5.0"}, clear=False):
            # 100k input + 100k output -> 0.1 + 0.5 = 0.6
            self.assertAlmostEqual(estimate_cost_usd("gemini-2.5-flash", 100_000, 100_000), 0.6)


class LedgerTests(unittest.TestCase):
    def test_record_and_query_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = CostLedger(Path(tmp) / "c.json")
            ledger.record(step="reporter", provider="gemini", model="gemini-2.5-flash",
                          input_tokens=1000, output_tokens=200, queue_id="Q-1")
            ledger.record(step="solution_architect", provider="claude", model="claude-sonnet-4-6",
                          input_tokens=2000, output_tokens=400, queue_id="Q-1")
            ledger.record(step="reporter", provider="gemini", model="gemini-2.5-flash",
                          input_tokens=500, output_tokens=100, queue_id="Q-2")
            self.assertEqual(len(ledger.all_calls()), 3)
            self.assertEqual(len(ledger.calls_for_queue("Q-1")), 2)

    def test_totals_aggregation(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = CostLedger(Path(tmp) / "c.json")
            ledger.record(step="reporter", provider="gemini", model="gemini-2.5-flash",
                          input_tokens=1000, output_tokens=200, queue_id="Q-1")
            ledger.record(step="solution_architect", provider="claude", model="claude-sonnet-4-6",
                          input_tokens=2000, output_tokens=400, queue_id="Q-1")
            t = ledger.totals(queue_id="Q-1")
            self.assertEqual(t["calls"], 2)
            self.assertEqual(t["input_tokens"], 3000)
            self.assertEqual(t["output_tokens"], 600)
            self.assertGreater(t["cost_usd"], 0.0)
            self.assertIn("gemini", t["by_provider"])
            self.assertIn("claude", t["by_provider"])
            self.assertIn("reporter", t["by_step"])
            self.assertIn("solution_architect", t["by_step"])

    def test_negative_tokens_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = CostLedger(Path(tmp) / "c.json")
            with self.assertRaises(ValueError):
                ledger.record(step="reporter", provider="gemini", model="gemini-2.5-flash",
                              input_tokens=-1, output_tokens=0)

    def test_persistence_across_instances(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "c.json"
            CostLedger(path).record(step="x", provider="gemini", model="gemini-2.5-flash",
                                    input_tokens=1, output_tokens=1)
            self.assertEqual(len(CostLedger(path).all_calls()), 1)


class ReporterIntegrationTests(unittest.TestCase):
    """Verify that the Reporter records to the ledger after an LLM call."""

    def test_reporter_records_call_on_success(self):
        from agent_center.architect_agent import ArchitectAgent
        from agent_center.change_memory import ChangeMemory
        from agent_center.investigators import InvestigationResult
        from agent_center.reporter_agent import ReporterAgent
        from agent_center.structured_memory import StructuredMemory

        class _Stub:
            layer = "frontend"; status = "ok"
            def investigate(self, sub):
                return InvestigationResult(layer=self.layer, status=self.status,
                                           findings=[], inspected_subcomponents=[],
                                           elapsed_ms=0.1)

        class _StubProvider:
            name = "gemini"
            model = "gemini-2.5-flash"
            last_usage = {"input_tokens": 123, "output_tokens": 45,
                          "model": "gemini-2.5-flash", "provider": "gemini"}
            def generate_json(self, prompt, max_tokens=1500, temperature=0.2):
                return {
                    "headline": "h", "overall": "ok",
                    "frontend": {"status":"ok","headline":"f","bullets":[]},
                    "backend":  {"status":"ok","headline":"b","bullets":[]},
                    "database": {"status":"ok","headline":"d","bullets":[]},
                    "next_actions": ["x"],
                }

        with tempfile.TemporaryDirectory() as tmp:
            # Redirect ledger to tmp by patching the module-level path.
            ledger_path = Path(tmp) / "c.json"
            with patch("agent_center.reporter_agent.CostLedger") as LedgerCls:
                LedgerCls.return_value = CostLedger(ledger_path)
                arch = ArchitectAgent(
                    fe_investigator=_Stub(),
                    be_investigator=_Stub(),
                    db_investigator=_Stub(),
                    memory=StructuredMemory(Path(tmp) / "m.json"),
                    change_memory=ChangeMemory(Path(tmp) / "l.json"),
                )
                out = arch.investigate(queue_id="Q-LDG", prompt="x")
                with patch("agent_center.reporter_agent.pick_provider") as pp:
                    pp.return_value = _StubProvider()
                    ReporterAgent().report(out, llm_choice="gemini")
            calls = CostLedger(ledger_path).all_calls()
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0]["step"], "reporter")
            self.assertEqual(calls[0]["input_tokens"], 123)
            self.assertEqual(calls[0]["queue_id"], "Q-LDG")


if __name__ == "__main__":
    unittest.main()
