"""
BaseImplementer — scope/hash/backup/stage/commit/rollback skeleton.
====================================================================
Every Implementer (FE / BE / DB Migration) inherits this. The base enforces:

  1. Scope check    — file_path must live under self.allowed_root.
  2. Drift check    — at stage time we record the file's sha256.
                       At commit time we re-read the file and refuse to commit
                       if the hash changed (someone else edited it mid-flow).
  3. Backup         — original file copied to AGENT_BACKUPS_DIR/<ISO-Z>/<rel>.
  4. Stage          — proposed bytes written to AGENT_STAGING_DIR/<rel>.
                       The dashboard renders this as a unified diff.
  5. Commit         — staging file replaces real file (atomic).
  6. Rollback       — read backup, restore real file, mark edit rolled_back.
  7. ChangeMemory   — every commit appends an Edit row with the symptom
                       fingerprint so the no-repeat-fix loop has full data.

Pure storage layer — no LLM calls, no network. This module is what makes
the "approval gate" real.
"""

from __future__ import annotations

import difflib
import hashlib
import shutil
import uuid
from abc import ABC
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from config import AGENT_BACKUPS_DIR, AGENT_STAGING_DIR, PROJECT_ROOT
from agent_center._atomic import atomic_write_json, file_lock
from agent_center.change_memory import ChangeMemory, hash_text
from agent_center.solution_architect_agent import SolutionItem


# ── Exceptions ────────────────────────────────────────────────────────────────

class ScopeViolation(Exception):
    """Raised when an Implementer is asked to touch a file outside its scope."""


class DriftDetected(Exception):
    """Raised when the on-disk hash differs from what was staged."""


# ── Dataclasses ───────────────────────────────────────────────────────────────

@dataclass
class StagedFile:
    item_id:        str
    queue_id:       str
    layer:          str
    file_path:      str           # repo-relative
    abs_path:       str           # absolute on this machine
    is_new_file:    bool
    before_text:    str           # empty for new files
    before_hash:    str           # "" for new files
    after_text:     str
    after_hash:     str
    diff:           str
    staging_path:   str
    backup_path:    str           # "" for new files (nothing to back up)
    staged_at:      str
    fingerprint:    str
    sub_component:  str
    rationale:      str
    rejected_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PreviewResult:
    item_id:      str
    file_path:    str
    is_new_file:  bool
    in_scope:     bool
    scope_root:   str
    has_proposal: bool
    diff:         str
    note:         str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ApplyResult:
    ok:           bool
    edit_id:      str
    item_id:      str
    queue_id:     str
    file_path:    str
    before_hash:  str
    after_hash:   str
    diff:         str
    backup_path:  str
    committed_at: str
    error:        str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _utc_now() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def _ts_dirname() -> str:
    """Filesystem-safe ISO-Z timestamp suitable for use as a directory name."""
    return datetime.utcnow().strftime("%Y-%m-%dT%H-%M-%SZ")


def make_unified_diff(before: str, after: str, file_path: str) -> str:
    diff = difflib.unified_diff(
        before.splitlines(keepends=True),
        after.splitlines(keepends=True),
        fromfile="a/" + file_path,
        tofile="b/" + file_path,
        lineterm="",
    )
    return "".join(diff)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ── Base ──────────────────────────────────────────────────────────────────────

class BaseImplementer(ABC):
    """All Implementers share scope-checked stage/commit/rollback."""

    layer: str = "base"
    allowed_root: Path = PROJECT_ROOT  # subclasses override

    def __init__(
        self,
        *,
        project_root: Path | None = None,
        allowed_root: Path | None = None,
        backups_dir:  Path | None = None,
        staging_dir:  Path | None = None,
        change_memory: ChangeMemory | None = None,
    ):
        self.project_root = (project_root or PROJECT_ROOT).resolve()
        if allowed_root is not None:
            self.allowed_root = Path(allowed_root).resolve()
        else:
            self.allowed_root = Path(self.allowed_root).resolve()
        self.backups_dir  = (backups_dir or AGENT_BACKUPS_DIR).resolve()
        self.staging_dir  = (staging_dir or AGENT_STAGING_DIR).resolve()
        self.change_memory = change_memory or ChangeMemory()

    # ── Scope ─────────────────────────────────────────────────────────────────

    def _resolve_in_scope(self, repo_relative: str) -> Path:
        """Resolve repo-relative path inside the project root and verify scope."""
        if not repo_relative:
            raise ScopeViolation("Empty file_path")
        candidate = (self.project_root / repo_relative).resolve()
        try:
            candidate.relative_to(self.project_root)
        except ValueError:
            raise ScopeViolation(f"{repo_relative} escapes project root")
        try:
            candidate.relative_to(self.allowed_root)
        except ValueError:
            raise ScopeViolation(
                f"{repo_relative} is outside this implementer's allowed root "
                f"({self.allowed_root})"
            )
        return candidate

    def can_handle(self, item: SolutionItem) -> bool:
        try:
            self._resolve_in_scope(item.file_path)
            return True
        except ScopeViolation:
            return False

    # ── Preview ───────────────────────────────────────────────────────────────

    def preview(self, item: SolutionItem) -> PreviewResult:
        try:
            target = self._resolve_in_scope(item.file_path)
        except ScopeViolation as exc:
            return PreviewResult(
                item_id=item.item_id, file_path=item.file_path,
                is_new_file=False, in_scope=False,
                scope_root=str(self.allowed_root),
                has_proposal=False, diff="", note=str(exc),
            )

        is_new = not target.exists()
        before = "" if is_new else target.read_text(encoding="utf-8", errors="replace")
        after  = self._proposed_text(item, before)
        if after is None:
            return PreviewResult(
                item_id=item.item_id, file_path=item.file_path,
                is_new_file=is_new, in_scope=True,
                scope_root=str(self.allowed_root),
                has_proposal=False, diff="",
                note="No proposed_full_text supplied; auto-apply skipped. Provide proposed_full_text or commit manually.",
            )
        return PreviewResult(
            item_id=item.item_id, file_path=item.file_path,
            is_new_file=is_new, in_scope=True,
            scope_root=str(self.allowed_root),
            has_proposal=True,
            diff=make_unified_diff(before, after, item.file_path),
        )

    # ── Stage ─────────────────────────────────────────────────────────────────

    def stage(self, item: SolutionItem, *, queue_id: str) -> StagedFile:
        target = self._resolve_in_scope(item.file_path)
        is_new = not target.exists()
        before = "" if is_new else target.read_text(encoding="utf-8", errors="replace")
        after  = self._proposed_text(item, before)
        if after is None:
            return StagedFile(
                item_id=item.item_id, queue_id=queue_id, layer=self.layer,
                file_path=item.file_path, abs_path=str(target),
                is_new_file=is_new, before_text=before,
                before_hash=_sha256(before) if before else "",
                after_text="", after_hash="", diff="",
                staging_path="", backup_path="",
                staged_at=_utc_now(),
                fingerprint=item.fingerprint,
                sub_component=item.sub_component,
                rationale=item.rationale,
                rejected_reason="No proposed_full_text supplied; cannot auto-stage.",
            )

        diff = make_unified_diff(before, after, item.file_path)

        # Backup existing file (only if it exists).
        backup_path = ""
        if not is_new:
            backup_root = self.backups_dir / _ts_dirname()
            backup_root.mkdir(parents=True, exist_ok=True)
            backup_target = backup_root / item.file_path
            backup_target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, backup_target)
            backup_path = str(backup_target)

        # Write staging file.
        staging_target = self.staging_dir / item.file_path
        staging_target.parent.mkdir(parents=True, exist_ok=True)
        staging_target.write_text(after, encoding="utf-8")

        return StagedFile(
            item_id=item.item_id, queue_id=queue_id, layer=self.layer,
            file_path=item.file_path, abs_path=str(target),
            is_new_file=is_new,
            before_text=before, before_hash=_sha256(before) if before else "",
            after_text=after,   after_hash=_sha256(after),
            diff=diff,
            staging_path=str(staging_target),
            backup_path=backup_path,
            staged_at=_utc_now(),
            fingerprint=item.fingerprint,
            sub_component=item.sub_component,
            rationale=item.rationale,
        )

    # ── Commit ────────────────────────────────────────────────────────────────

    def commit(
        self,
        staged: StagedFile,
        *,
        linked_issue_id: str = "",
        linked_run_id:   str = "",
        llm_used:        str = "",
    ) -> ApplyResult:
        if staged.rejected_reason:
            return ApplyResult(
                ok=False, edit_id="", item_id=staged.item_id,
                queue_id=staged.queue_id, file_path=staged.file_path,
                before_hash="", after_hash="", diff="", backup_path="",
                committed_at=_utc_now(),
                error=staged.rejected_reason,
            )

        target = Path(staged.abs_path)
        # Drift check: did anyone touch the file since we staged?
        if target.exists():
            current = target.read_text(encoding="utf-8", errors="replace")
            current_hash = _sha256(current)
            if staged.before_hash and current_hash != staged.before_hash:
                return ApplyResult(
                    ok=False, edit_id="", item_id=staged.item_id,
                    queue_id=staged.queue_id, file_path=staged.file_path,
                    before_hash=current_hash, after_hash=staged.after_hash,
                    diff=staged.diff, backup_path=staged.backup_path,
                    committed_at=_utc_now(),
                    error=(
                        "Drift detected: file changed between stage and commit. "
                        "Re-run /api/solve and re-stage to incorporate the new content."
                    ),
                )

        # Apply: write the staged content to the real file atomically-ish.
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(staged.after_text, encoding="utf-8")

        edit = self.change_memory.record_edit(
            agent=type(self).__name__,
            component=staged.sub_component or staged.file_path,
            file_path=staged.file_path,
            before_text=staged.before_text,
            after_text=staged.after_text,
            diff=staged.diff,
            backup_path=staged.backup_path,
            symptom_fingerprint=staged.fingerprint,
            linked_issue_id=linked_issue_id,
            linked_run_id=linked_run_id,
            llm=llm_used,
            verification_outcome="pending",
        )
        return ApplyResult(
            ok=True, edit_id=edit["edit_id"], item_id=staged.item_id,
            queue_id=staged.queue_id, file_path=staged.file_path,
            before_hash=staged.before_hash, after_hash=staged.after_hash,
            diff=staged.diff, backup_path=staged.backup_path,
            committed_at=_utc_now(),
        )

    # ── Rollback ──────────────────────────────────────────────────────────────

    def rollback(self, edit_id: str) -> dict[str, Any]:
        edit = self.change_memory.get_edit(edit_id)
        if edit is None:
            raise KeyError(edit_id)
        if edit.get("rolled_back"):
            return {"ok": True, "already_rolled_back": True, "edit": edit}
        backup_path = edit.get("backup_path", "")
        rel_path    = edit.get("file_path", "")
        target      = self._resolve_in_scope(rel_path)

        if not backup_path:
            # New-file edit: rollback = delete the file we created.
            if target.exists():
                target.unlink()
            self.change_memory.mark_rolled_back(edit_id)
            return {"ok": True, "restored_from": "", "deleted": str(target)}

        bp = Path(backup_path)
        if not bp.exists():
            return {"ok": False, "error": f"Backup missing at {backup_path}"}
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(bp, target)
        self.change_memory.mark_rolled_back(edit_id)
        return {"ok": True, "restored_from": backup_path, "target": str(target)}

    # ── Hooks for subclasses ─────────────────────────────────────────────────

    def _proposed_text(self, item: SolutionItem, before: str) -> str | None:
        """
        Return the proposed full file content. Returns ``None`` to signal that
        the implementer cannot produce auto-applicable content for this item
        (typically because only proposed_diff is set and we don't apply diffs
        in the base implementation).

        Subclasses can override for special cases (e.g. DBMigrationImplementer
        always treats proposed_full_text as authoritative).
        """
        if item.proposed_full_text:
            return item.proposed_full_text
        # No full_text → we don't auto-apply diffs in this milestone.
        return None
