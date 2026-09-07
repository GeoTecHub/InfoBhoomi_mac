"""
Persistent cache of generated SolutionPlans, keyed by queue_id.
================================================================
Why on disk: lets the user amend a plan, restart the dashboard, and pick
up where they left off without re-running the LLM.

Backed by atomic_write + file_lock so concurrent dashboard requests are safe.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from config import AGENT_SOLUTION_PLANS_FILE, STATE_DIR
from agent_center._atomic import atomic_write_json, file_lock, read_json


class SolutionPlanStore:
    def __init__(self, path: Path = AGENT_SOLUTION_PLANS_FILE):
        self.path = Path(path)
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        self.data = self._load()

    def _load(self) -> dict[str, Any]:
        loaded = read_json(self.path, default=None)
        if isinstance(loaded, dict) and loaded:
            loaded.setdefault("version", 1)
            loaded.setdefault("plans", {})
            return loaded
        return {"version": 1, "plans": {}}

    def save(self) -> None:
        with file_lock(self.path):
            atomic_write_json(self.path, self.data)

    # ── Public API ────────────────────────────────────────────────────────────

    def put(self, queue_id: str, plan: dict[str, Any]) -> dict[str, Any]:
        if not queue_id:
            raise ValueError("queue_id is required")
        # Read-modify-write under the lock so concurrent puts don't lose updates.
        with file_lock(self.path):
            self.data = self._load()
            plans = self.data.setdefault("plans", {})
            plans[queue_id] = plan
            if len(plans) > 200:
                keys_sorted = sorted(
                    plans.items(),
                    key=lambda kv: kv[1].get("generated_at", ""),
                    reverse=True,
                )
                self.data["plans"] = dict(keys_sorted[:200])
            atomic_write_json(self.path, self.data)
        return plan

    def get(self, queue_id: str) -> dict[str, Any] | None:
        return self.data.get("plans", {}).get(queue_id)

    def all(self) -> dict[str, dict[str, Any]]:
        return dict(self.data.get("plans", {}))

    def delete(self, queue_id: str) -> bool:
        with file_lock(self.path):
            self.data = self._load()
            plans = self.data.get("plans", {})
            if queue_id in plans:
                del plans[queue_id]
                atomic_write_json(self.path, self.data)
                return True
        return False
