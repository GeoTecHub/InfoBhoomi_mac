"""Tests for the Applier coordinator — routes items + stage/commit/rollback."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_center.applier import Applier
from agent_center.change_memory import ChangeMemory
from agent_center.implementers import (
    BackendImplementer,
    DBMigrationImplementer,
    FrontendImplementer,
)
from agent_center.solution_architect_agent import SolutionItem


def _build_applier(tmp: Path) -> tuple[Applier, Path]:
    project = tmp / "project"; project.mkdir()
    fe_root = project / "fe"; fe_root.mkdir()
    be_root = project / "be"; be_root.mkdir()
    mig_root = be_root / "user" / "migrations"; mig_root.mkdir(parents=True)
    backups = tmp / "backups"
    staging = tmp / "staging"
    ledger  = ChangeMemory(tmp / "ledger.json")
    fe = FrontendImplementer(project_root=project, allowed_root=fe_root,
                             backups_dir=backups, staging_dir=staging,
                             change_memory=ledger)
    be = BackendImplementer(project_root=project, allowed_root=be_root,
                            backups_dir=backups, staging_dir=staging,
                            change_memory=ledger)
    mig = DBMigrationImplementer(project_root=project, allowed_root=mig_root,
                                 backups_dir=backups, staging_dir=staging,
                                 change_memory=ledger)
    return Applier(fe=fe, be=be, mig=mig, change_memory=ledger), project


def _item(layer, file_path, full_text, item_id="SI-1"):
    return SolutionItem(
        item_id=item_id, layer=layer, sub_component="x",
        file_path=file_path, rationale="r",
        proposed_diff="", proposed_full_text=full_text,
        fingerprint=f"{layer}|fp",
    )


class RoutingTests(unittest.TestCase):
    def test_routes_each_layer_to_correct_implementer(self):
        with tempfile.TemporaryDirectory() as t:
            applier, _ = _build_applier(Path(t))
            fe_it  = _item("frontend",  "fe/services/x.ts", "// fe", "F-1")
            be_it  = _item("backend",   "be/views/auth.py", "# be", "B-1")
            mig_it = _item("migration", "be/user/migrations/0042_x.py", "# mig", "M-1")
            self.assertIsInstance(applier.implementer_for(fe_it), FrontendImplementer)
            self.assertIsInstance(applier.implementer_for(be_it), BackendImplementer)
            self.assertIsInstance(applier.implementer_for(mig_it), DBMigrationImplementer)

    def test_unrouted_item_returns_none(self):
        with tempfile.TemporaryDirectory() as t:
            applier, _ = _build_applier(Path(t))
            it = _item("frontend", "outside/file.ts", "// x", "X-1")
            self.assertIsNone(applier.implementer_for(it))


class StageCommitTests(unittest.TestCase):
    def test_stage_then_commit_writes_files_and_records_edits(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            applier, project = _build_applier(tmp)
            (project / "fe" / "old.ts").write_text("OLD\n")
            items = [
                _item("frontend", "fe/old.ts", "NEW\n", "F-1"),
                _item("backend",  "be/new.py", "# new\n", "B-1"),
                _item("migration","be/user/migrations/0042_y.py", "# mig\n", "M-1"),
            ]
            batch = applier.stage(items, queue_id="Q-1")
            self.assertEqual(len(batch.staged), 3)
            self.assertEqual(len(batch.rejected), 0)
            commit = applier.commit(batch.staged, linked_run_id="Q-1")
            ok_results = [r for r in commit.results if r.ok]
            self.assertEqual(len(ok_results), 3)
            self.assertEqual((project / "fe" / "old.ts").read_text(), "NEW\n")
            self.assertEqual((project / "be" / "new.py").read_text(), "# new\n")
            self.assertEqual((project / "be" / "user" / "migrations" / "0042_y.py").read_text(), "# mig\n")
            self.assertEqual(len(applier.change_memory.all_edits()), 3)

    def test_rejected_items_skipped(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            applier, _ = _build_applier(tmp)
            items = [
                _item("frontend", "outside/file.ts", "// x", "X-1"),  # rejected: no impl
                _item("frontend", "fe/ok.ts", "// new", "F-2"),
            ]
            batch = applier.stage(items, queue_id="Q-1")
            self.assertEqual(len(batch.staged), 1)
            self.assertEqual(len(batch.rejected), 1)


class RollbackTests(unittest.TestCase):
    def test_rollback_via_applier_dispatches_correctly(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            applier, project = _build_applier(tmp)
            (project / "fe" / "x.ts").write_text("OLD\n")
            batch = applier.stage([_item("frontend", "fe/x.ts", "NEW\n", "F-1")], queue_id="Q-1")
            commit = applier.commit(batch.staged)
            edit_id = commit.results[0].edit_id
            res = applier.rollback(edit_id)
            self.assertTrue(res["ok"])
            self.assertEqual((project / "fe" / "x.ts").read_text(), "OLD\n")


if __name__ == "__main__":
    unittest.main()
