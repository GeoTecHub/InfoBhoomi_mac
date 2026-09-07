"""Tests for BaseImplementer + FE/BE concretes — scope, drift, stage, commit, rollback."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_center.change_memory import ChangeMemory
from agent_center.implementers import (
    BackendImplementer,
    BaseImplementer,
    FrontendImplementer,
    ScopeViolation,
)
from agent_center.solution_architect_agent import SolutionItem


def _item(file_path, full_text="// new content\n", *, item_id="SI-1", layer="frontend"):
    return SolutionItem(
        item_id=item_id, layer=layer, sub_component="x",
        file_path=file_path, rationale="r",
        proposed_diff="", proposed_full_text=full_text,
        fingerprint=f"{layer}|fp",
    )


class _TestImpl(BaseImplementer):
    """Helper subclass tied to a tmp project for unit tests."""

    layer = "frontend"


def _build(tmp: Path) -> _TestImpl:
    project = tmp / "project"; project.mkdir()
    fe = project / "fe_root"; fe.mkdir()
    backups = tmp / "backups"
    staging = tmp / "staging"
    return _TestImpl(
        project_root=project,
        allowed_root=fe,
        backups_dir=backups,
        staging_dir=staging,
        change_memory=ChangeMemory(tmp / "ledger.json"),
    )


class ScopeTests(unittest.TestCase):
    def test_rejects_path_outside_allowed_root(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            impl = _build(tmp)
            it = _item("other_root/x.ts")
            self.assertFalse(impl.can_handle(it))
            preview = impl.preview(it)
            self.assertFalse(preview.in_scope)

    def test_rejects_path_escaping_project_root(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            impl = _build(tmp)
            it = _item("../escape.txt")
            with self.assertRaises(ScopeViolation):
                impl._resolve_in_scope(it.file_path)


class StageCommitTests(unittest.TestCase):
    def test_new_file_stage_then_commit(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            impl = _build(tmp)
            it = _item("fe_root/services/new.ts", full_text="export const A = 1;\n")
            staged = impl.stage(it, queue_id="Q-1")
            self.assertTrue(staged.is_new_file)
            self.assertEqual(staged.before_hash, "")
            self.assertTrue(Path(staged.staging_path).exists())
            self.assertEqual(staged.backup_path, "")
            result = impl.commit(staged)
            self.assertTrue(result.ok)
            target = Path(staged.abs_path)
            self.assertTrue(target.exists())
            self.assertEqual(target.read_text(), "export const A = 1;\n")
            # Ledger entry exists.
            self.assertTrue(impl.change_memory.get_edit(result.edit_id))

    def test_existing_file_backup_and_commit(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            impl = _build(tmp)
            target = impl.allowed_root / "x.ts"
            target.write_text("OLD\n")
            it = _item("fe_root/x.ts", full_text="NEW\n")
            staged = impl.stage(it, queue_id="Q-1")
            self.assertFalse(staged.is_new_file)
            self.assertTrue(Path(staged.backup_path).exists())
            self.assertEqual(Path(staged.backup_path).read_text(), "OLD\n")
            result = impl.commit(staged)
            self.assertTrue(result.ok)
            self.assertEqual(target.read_text(), "NEW\n")

    def test_drift_detection_blocks_commit(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            impl = _build(tmp)
            target = impl.allowed_root / "drift.ts"
            target.write_text("ORIGINAL\n")
            it = _item("fe_root/drift.ts", full_text="NEW\n")
            staged = impl.stage(it, queue_id="Q-1")
            # Simulate someone else editing the file between stage and commit.
            target.write_text("EDITED-BY-SOMEONE-ELSE\n")
            result = impl.commit(staged)
            self.assertFalse(result.ok)
            self.assertIn("Drift detected", result.error)
            # Real file untouched (not overwritten with NEW).
            self.assertEqual(target.read_text(), "EDITED-BY-SOMEONE-ELSE\n")

    def test_missing_proposal_is_rejected_at_stage(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            impl = _build(tmp)
            (impl.allowed_root / "f.ts").write_text("OLD\n")
            it = SolutionItem(
                item_id="x", layer="frontend", sub_component="x",
                file_path="fe_root/f.ts", rationale="r",
                proposed_diff="--- a\n+++ b\n", proposed_full_text="",
                fingerprint="fp",
            )
            staged = impl.stage(it, queue_id="Q-1")
            self.assertTrue(staged.rejected_reason)
            self.assertEqual(staged.staging_path, "")
            # commit() returns an error rather than crashing.
            result = impl.commit(staged)
            self.assertFalse(result.ok)


class RollbackTests(unittest.TestCase):
    def test_rollback_restores_existing_file(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            impl = _build(tmp)
            target = impl.allowed_root / "r.ts"
            target.write_text("OLD\n")
            it = _item("fe_root/r.ts", full_text="NEW\n")
            staged = impl.stage(it, queue_id="Q-1")
            commit = impl.commit(staged)
            self.assertEqual(target.read_text(), "NEW\n")
            res = impl.rollback(commit.edit_id)
            self.assertTrue(res["ok"])
            self.assertEqual(target.read_text(), "OLD\n")
            edit = impl.change_memory.get_edit(commit.edit_id)
            self.assertTrue(edit["rolled_back"])

    def test_rollback_deletes_new_file(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            impl = _build(tmp)
            it = _item("fe_root/created.ts", full_text="NEW\n")
            staged = impl.stage(it, queue_id="Q-1")
            commit = impl.commit(staged)
            target = Path(staged.abs_path)
            self.assertTrue(target.exists())
            impl.rollback(commit.edit_id)
            self.assertFalse(target.exists())


class FrontendBackendDispatchTests(unittest.TestCase):
    def test_fe_handles_fe_paths_only(self):
        fe = FrontendImplementer()
        be = BackendImplementer()
        fe_item = _item("infoBhoomi-frontedend-div2/src/app/services/auth.service.ts")
        be_item = _item("InfoBhoomi_Backend_dev2/user/views/auth.py", layer="backend")
        mig_item = _item("InfoBhoomi_Backend_dev2/user/migrations/0042_x.py", layer="migration")
        self.assertTrue(fe.can_handle(fe_item))
        self.assertFalse(fe.can_handle(be_item))
        self.assertTrue(be.can_handle(be_item))
        self.assertFalse(be.can_handle(fe_item))
        # BackendImplementer must NOT handle migrations.
        self.assertFalse(be.can_handle(mig_item))


if __name__ == "__main__":
    unittest.main()
