"""
LLM cost ledger.
================
Records every Reporter / Solution Architect call so the dashboard can show
"this debugging round cost X tokens / Y cents". Cost rates are conservative
estimates per the rate table below; users can override via env if needed.

Schema of ``.agent_state/llm_cost_ledger.json``:
{
  "version": 1,
  "calls": [
    {
      "call_id":         "CALL-...",
      "queue_id":        "Q-...",
      "linked_issue_id": "ISS-...",
      "step":            "reporter" | "solution_architect" | "fix_proposal" | ...,
      "provider":        "gemini" | "claude" | ...,
      "model":           "gemini-2.5-flash",
      "input_tokens":    int,
      "output_tokens":   int,
      "cost_usd":        float,
      "recorded_at":     "ISO-Z"
    }
  ]
}
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from config import AGENT_LLM_COST_FILE, STATE_DIR
from agent_center._atomic import atomic_write_json, file_lock, read_json


# Default rates in USD per 1M tokens (input, output).
# Override individual entries via env "IB_AGENT_LLM_RATE_<MODEL>"="in,out".
_DEFAULT_RATES: dict[str, tuple[float, float]] = {
    "gemini-2.5-flash":   (0.30, 2.50),
    "gemini-2.5-pro":     (3.50, 10.50),
    "claude-haiku-4-5-20251001": (1.00, 5.00),
    "claude-sonnet-4-6":  (3.00, 15.00),
    "claude-opus-4-6":    (15.00, 75.00),
}


def _utc_now() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def estimate_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    """
    Return a conservative cost estimate. Returns 0.0 when the model is unknown
    so we never inflate; tests can call this directly.
    """
    env_key = f"IB_AGENT_LLM_RATE_{model.upper().replace('-', '_').replace('.', '_')}"
    override = os.environ.get(env_key, "")
    if override:
        try:
            in_rate, out_rate = (float(x) for x in override.split(","))
            return round(input_tokens * in_rate / 1_000_000 + output_tokens * out_rate / 1_000_000, 6)
        except (ValueError, AttributeError):
            pass
    in_rate, out_rate = _DEFAULT_RATES.get(model, (0.0, 0.0))
    return round(input_tokens * in_rate / 1_000_000 + output_tokens * out_rate / 1_000_000, 6)


class CostLedger:
    """Persistent per-call ledger with atomic write + lock."""

    def __init__(self, path: Path = AGENT_LLM_COST_FILE):
        self.path = Path(path)
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        self.data = self._load()

    def _load(self) -> dict[str, Any]:
        loaded = read_json(self.path, default=None)
        if isinstance(loaded, dict) and loaded:
            loaded.setdefault("version", 1)
            loaded.setdefault("calls", [])
            return loaded
        return {"version": 1, "calls": []}

    # ── Recording ─────────────────────────────────────────────────────────────

    def record(
        self,
        *,
        step:            str,
        provider:        str,
        model:           str,
        input_tokens:    int,
        output_tokens:   int,
        queue_id:        str = "",
        linked_issue_id: str = "",
    ) -> dict[str, Any]:
        if input_tokens < 0 or output_tokens < 0:
            raise ValueError("token counts must be >= 0")
        call = {
            "call_id":         f"CALL-{uuid.uuid4().hex[:10].upper()}",
            "queue_id":        queue_id,
            "linked_issue_id": linked_issue_id,
            "step":            step,
            "provider":        provider,
            "model":           model,
            "input_tokens":    int(input_tokens),
            "output_tokens":   int(output_tokens),
            "cost_usd":        estimate_cost_usd(model, input_tokens, output_tokens),
            "recorded_at":     _utc_now(),
        }
        # Read-modify-write under the lock so concurrent recorders don't lose calls.
        with file_lock(self.path):
            self.data = self._load()
            self.data.setdefault("calls", []).insert(0, call)
            # Cap at 5,000 calls.
            self.data["calls"] = self.data["calls"][:5000]
            atomic_write_json(self.path, self.data)
        return call

    # ── Queries ───────────────────────────────────────────────────────────────

    def all_calls(self) -> list[dict[str, Any]]:
        return list(self.data.get("calls", []))

    def calls_for_queue(self, queue_id: str) -> list[dict[str, Any]]:
        return [c for c in self.all_calls() if c.get("queue_id") == queue_id]

    def totals(self, *, queue_id: str = "") -> dict[str, Any]:
        """Aggregate by provider, model, and step."""
        calls = self.calls_for_queue(queue_id) if queue_id else self.all_calls()
        agg = {
            "calls":          len(calls),
            "input_tokens":   sum(c.get("input_tokens", 0)  for c in calls),
            "output_tokens":  sum(c.get("output_tokens", 0) for c in calls),
            "cost_usd":       round(sum(c.get("cost_usd", 0.0) for c in calls), 6),
            "by_provider":    {},
            "by_model":       {},
            "by_step":        {},
        }
        for c in calls:
            for key, label in (("by_provider", "provider"), ("by_model", "model"), ("by_step", "step")):
                bucket = agg[key].setdefault(c.get(label, ""), {
                    "calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0,
                })
                bucket["calls"]         += 1
                bucket["input_tokens"]  += c.get("input_tokens", 0)
                bucket["output_tokens"] += c.get("output_tokens", 0)
                bucket["cost_usd"]      += c.get("cost_usd", 0.0)
        # Round cost_usd buckets.
        for key in ("by_provider", "by_model", "by_step"):
            for bucket in agg[key].values():
                bucket["cost_usd"] = round(bucket["cost_usd"], 6)
        return agg
