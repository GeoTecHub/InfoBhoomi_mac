"""
Architect Agent — coordinator (no LLM).
========================================
Responsibilities:
  1. Take a user prompt + queue_id.
  2. Run DebugRouter to pick top function_id(s).
  3. Pull each function's ComponentMap entry → FE / BE / DB sub-components.
  4. Ask ChangeMemory for prior failed strategies on those sub-components,
     so the downstream Solution Architect (P3) can avoid repeating them.
  5. Dispatch to FrontendInvestigator / BackendInvestigator / DBInvestigator
     in series (parallel later if needed — sequential issue queue means there
     is only one issue in flight at a time, so we don't need threads here).
  6. Persist a StructuredMemory issue tying everything together.
  7. Return an ``InvestigationPlan`` plus aggregated findings.

The Architect does NOT call any LLM. The Reporter (Step 4) does.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

from agent_center.change_memory import ChangeMemory
from agent_center.component_map import (
    BackendSubcomponent,
    ComponentMapEntry,
    DBSubcomponent,
    FrontendSubcomponent,
    get_entry,
)
from agent_center.debug_router_agent import DebugRouterAgent, RoutedFunction
from agent_center.investigators import (
    BackendInvestigator,
    DBInvestigator,
    FrontendInvestigator,
    InvestigationResult,
)
from agent_center.structured_memory import StructuredMemory


def _utc_now() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


@dataclass
class InvestigationPlan:
    queue_id:                str
    prompt:                  str
    selected_function_ids:   list[str]
    routes:                  list[dict]                  # RoutedFunction.to_dict()
    component_map_entries:   list[dict]                  # ComponentMapEntry as dict
    prior_failed_strategies: list[dict]                  # ChangeMemory edits
    created_at:              str = field(default_factory=_utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ArchitectOutput:
    plan:    InvestigationPlan
    issue:   dict[str, Any]
    fe:      InvestigationResult
    be:      InvestigationResult
    db:      InvestigationResult
    elapsed_ms: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan":  self.plan.to_dict(),
            "issue": self.issue,
            "fe":    self.fe.to_dict(),
            "be":    self.be.to_dict(),
            "db":    self.db.to_dict(),
            "elapsed_ms": self.elapsed_ms,
            "summary": self.summary(),
        }

    def summary(self) -> dict[str, Any]:
        return {
            "frontend": self.fe.status,
            "backend":  self.be.status,
            "db":       self.db.status,
            "fe_finding_count": len(self.fe.findings),
            "be_finding_count": len(self.be.findings),
            "db_finding_count": len(self.db.findings),
        }


class ArchitectAgent:
    """Reads the map, dispatches Investigators, aggregates evidence."""

    def __init__(
        self,
        *,
        router: DebugRouterAgent | None = None,
        fe_investigator: FrontendInvestigator | None = None,
        be_investigator: BackendInvestigator | None = None,
        db_investigator: DBInvestigator | None = None,
        memory: StructuredMemory | None = None,
        change_memory: ChangeMemory | None = None,
        max_routes: int = 3,
    ):
        self.router  = router  or DebugRouterAgent()
        self.fe      = fe_investigator or FrontendInvestigator()
        self.be      = be_investigator or BackendInvestigator()
        self.db      = db_investigator or DBInvestigator()
        self.memory  = memory or StructuredMemory()
        self.change  = change_memory or ChangeMemory()
        self.max_routes = max_routes

    # ── Public entry point ────────────────────────────────────────────────────

    def investigate(self, *, queue_id: str, prompt: str) -> ArchitectOutput:
        started = time.perf_counter()

        routes = self.router.route(prompt, limit=self.max_routes)
        selected: list[ComponentMapEntry] = []
        for r in routes:
            try:
                selected.append(get_entry(r.function_id))
            except KeyError:
                # Function in registry but not in map — surface as a soft warning
                continue
        # Aggregate all FE/BE/DB sub-components across selected entries.
        fe_components = _flatten([list(e.frontend) for e in selected])
        be_components = _flatten([list(e.backend)  for e in selected])
        db_components = _flatten([list(e.db)       for e in selected])

        # Look up prior failed edits for any file we'd touch — caller (Solution
        # Architect) gets these as anti-suggestions.
        prior: list[dict] = []
        for sc in fe_components + be_components:
            prior.extend(self.change.failed_strategies_for(sc.path))

        # Persist an Issue (top route used as primary category for memory dedup).
        if routes:
            top = routes[0]
            issue = self.memory.record_issue(
                function_category=top.category,
                sub_function=top.display_name,
                symptom=prompt.strip(),
                detected_by="Architect Agent",
                debug_notes=(
                    f"Routed to {len(routes)} function(s); "
                    f"matched terms: {', '.join(top.matched_terms)}"
                ),
            )
        else:
            issue = self.memory.record_issue(
                function_category="Unknown",
                sub_function="Unmatched prompt",
                symptom=prompt.strip(),
                detected_by="Architect Agent",
                debug_notes="DebugRouter returned no routes.",
            )

        plan = InvestigationPlan(
            queue_id=queue_id,
            prompt=prompt.strip(),
            selected_function_ids=[r.function_id for r in routes],
            routes=[r.to_dict() for r in routes],
            component_map_entries=[_entry_dict(e) for e in selected],
            prior_failed_strategies=prior,
        )

        # Run Investigators sequentially (sequential queue → no contention).
        fe_result = self.fe.investigate(fe_components)
        be_result = self.be.investigate(be_components)
        db_result = self.db.investigate(db_components)

        elapsed = round((time.perf_counter() - started) * 1000, 2)
        return ArchitectOutput(
            plan=plan,
            issue=issue,
            fe=fe_result,
            be=be_result,
            db=db_result,
            elapsed_ms=elapsed,
        )


# ── helpers ───────────────────────────────────────────────────────────────────

def _flatten(nested: list[list]) -> list:
    out = []
    for inner in nested:
        out.extend(inner)
    return out


def _entry_dict(entry: ComponentMapEntry) -> dict[str, Any]:
    return {
        "function_id": entry.function_id,
        "frontend": [{"path": s.path, "kind": s.kind, "responsibility": s.responsibility} for s in entry.frontend],
        "backend":  [{"path": s.path, "kind": s.kind, "responsibility": s.responsibility} for s in entry.backend],
        "db":       [{"table": s.table, "model": s.model, "key_fields": list(s.key_fields)} for s in entry.db],
        "runtime_dependencies": list(entry.runtime_dependencies),
    }
