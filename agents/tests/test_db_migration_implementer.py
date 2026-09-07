"""Tests for DBMigrationImplementer — explicit-apply gate, command, file gen."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_center.change_memory import ChangeMemory
from agent_center.implementers import DBMigrationImplementer
from agent_center.implementers.db_migration import MigrationApplyResult
from agent_center.solution_architect_agent import SolutionItem


class CanHandleTests(unittest.TestCase):
    def test_only_handles_migration_layer_inside_migrations_dir(self):
        impl = DBMigrationImplementer()
        good = SolutionItem(
            item_id="m", layer="migration", sub_component="0042_x",
            file_path="InfoBhoomi_Backend_dev2/user/migrations/0042_x.py",
            rationale="r", proposed_diff="", proposed_full_text="from django.db import migrations\n",
            fingerprint="fp",
        )
        bad_layer = SolutionItem(
            item_id="m", layer="backend", sub_component="x",
            file_path="InfoBhoomi_Backend_dev2/user/migrations/0042_x.py",
            rationale="r", proposed_diff="", proposed_full_text="x",
            fingerprint="fp",
        )
        bad_path = SolutionItem(
            item_id="m", layer="migration", sub_component="x",
            file_path="InfoBhoomi_Backend_dev2/user/views/auth.py",
            rationale="r", proposed_diff="", proposed_full_text="x",
            fingerprint="fp",
        )
        self.assertTrue(impl.can_handle(good))
        self.assertFalse(impl.can_handle(bad_layer))
        self.assertFalse(impl.can_handle(bad_path))


class ManualCommandTests(unittest.TestCase):
    def test_manual_command_includes_manage_py(self):
        cmd = DBMigrationImplementer.manual_command()
        self.assertIn("manage.py", cmd)
        self.assertIn("migrate", cmd)


class AutoApplyTests(unittest.TestCase):
    def test_auto_apply_refused_outside_development(self):
        with patch("agent_center.implementers.db_migration.AGENT_ENVIRONMENT", "production"):
            impl = DBMigrationImplementer()
            res = impl.apply_migration()
            self.assertFalse(res.ok)
            self.assertIn("disabled outside development", res.error)
            self.assertIn("manage.py", res.command)

    def test_auto_apply_in_development_runs_subprocess(self):
        # Use a stub subprocess.run that always succeeds with rc=0.
        with patch("agent_center.implementers.db_migration.AGENT_ENVIRONMENT", "development"):
            with patch("agent_center.implementers.db_migration.subprocess.run") as mocked:
                class FakeProc:
                    returncode = 0
                    stdout = "Migrations applied: 0042_x"
                    stderr = ""
                mocked.return_value = FakeProc()
                impl = DBMigrationImplementer()
                res = impl.apply_migration(timeout_seconds=5)
                self.assertTrue(res.ok)
                self.assertEqual(res.return_code, 0)
                self.assertIn("0042_x", res.stdout)


if __name__ == "__main__":
    unittest.main()
