"""
Applier — coordinates Implementers across a SolutionPlan.

Workflow:

  preview(plan, approvals)   — diff + scope check for each approved item.
                               Pure read-only. Used by the dashboard's
                               "preview before staging" step.
  stage(plan, approvals, queue_id)
                              — generate backups + staging files for each
                                approved item. No source-tree writes yet.
  commit(plan, staged_list)  — copy staging files to real source files;
                                record ChangeMemory entries; advance queue.
  rollback(edit_id)          — restore from backup; mark ledger.

Per Decision #6 the dashboard exposes rollback to anyone with access.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Iterable

from agent_center.change_memory import ChangeMemory
from agent_center.implementers import (
    ApplyResult,
    BackendImplementer,
    BaseImplementer,
    DBMigrationImplementer,
    FrontendImplementer,
    PreviewResult,
    StagedFile,
)
from agent_center.solution_architect_agent import SolutionItem


@dataclass
class StageBatch:
    queue_id: str
    staged:   list[StagedFile] = field(default_factory=list)
    rejected: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "queue_id": self.queue_id,
            "staged":   [s.to_dict() for s in self.staged],
            "rejected": list(self.rejected),
        }


@dataclass
class CommitBatch:
    queue_id: str
    results:  list[ApplyResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"queue_id": self.queue_id, "results": [r.to_dict() for r in self.results]}


class Applier:
    """Routes SolutionItems to the right Implementer, scope-checked."""

    def __init__(
        self,
        *,
        fe: FrontendImplementer | None = None,
        be: BackendImplementer  | None = None,
        mig: DBMigrationImplementer | None = None,
        change_memory: ChangeMemory | None = None,
    ):
        self.change_memory = change_memory or ChangeMemory()
        self.fe  = fe  or FrontendImplementer(change_memory=self.change_memory)
        self.be  = be  or BackendImplementer(change_memory=self.change_memory)
        self.mig = mig or DBMigrationImplementer(change_memory=self.change_memory)
        self._impls: tuple[BaseImplementer, ...] = (self.mig, self.fe, self.be)
        # Order matters: migrations should be matched before generic backend.

    def implementer_for(self, item: SolutionItem) -> BaseImplementer | None:
        for impl in self._impls:
            if impl.can_handle(item):
                return impl
        return None

    # ── Preview ───────────────────────────────────────────────────────────────

    def preview(self, items: Iterable[SolutionItem]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for item in items:
            impl = self.implementer_for(item)
            if impl is None:
                out.append({
                    "item_id": item.item_id, "file_path": item.file_path,
                    "in_scope": False, "scope_root": "",
                    "has_proposal": bool(item.proposed_full_text),
                    "diff": "", "is_new_file": False,
                    "note": "No implementer accepts this item's file_path. Check the path or layer.",
                })
                continue
            out.append(impl.preview(item).to_dict() | {"layer": impl.layer})
        return out

    # ── Stage ─────────────────────────────────────────────────────────────────

    def stage(
        self,
        items: Iterable[SolutionItem],
        *,
        queue_id: str,
    ) -> StageBatch:
        batch = StageBatch(queue_id=queue_id)
        for item in items:
            impl = self.implementer_for(item)
            if impl is None:
                batch.rejected.append({
                    "item_id": item.item_id, "file_path": item.file_path,
                    "reason":  "No implementer accepts this item.",
                })
                continue
            staged = impl.stage(item, queue_id=queue_id)
            if staged.rejected_reason:
                batch.rejected.append({
                    "item_id": item.item_id, "file_path": item.file_path,
                    "reason":  staged.rejected_reason,
                })
            else:
                batch.staged.append(staged)
        return batch

    # ── Commit ────────────────────────────────────────────────────────────────

    def commit(
        self,
        staged: Iterable[StagedFile],
        *,
        linked_issue_id: str = "",
        linked_run_id:   str = "",
        llm_used:        str = "",
    ) -> CommitBatch:
        batch = CommitBatch(queue_id="")
        for s in staged:
            batch.queue_id = s.queue_id  # all share one
            impl = self._impl_for_layer(s.layer)
            result = impl.commit(
                s,
                linked_issue_id=linked_issue_id,
                linked_run_id=linked_run_id,
                llm_used=llm_used,
            )
            batch.results.append(result)
        return batch

    # ── Rollback ──────────────────────────────────────────────────────────────

    def rollback(self, edit_id: str) -> dict[str, Any]:
        edit = self.change_memory.get_edit(edit_id)
        if edit is None:
            raise KeyError(edit_id)
        # Pick the implementer that owns the file path's layer (as recorded).
        agent_name = edit.get("agent", "")
        if agent_name == "FrontendImplementer":
            impl = self.fe
        elif agent_name == "DBMigrationImplementer":
            impl = self.mig
        else:
            impl = self.be
        return impl.rollback(edit_id)

    # ── Internals ─────────────────────────────────────────────────────────────

    def _impl_for_layer(self, layer: str) -> BaseImplementer:
        if layer == "frontend":  return self.fe
        if layer == "backend":   return self.be
        if layer == "migration": return self.mig
        raise ValueError(f"Unknown layer for staged file: {layer!r}")
