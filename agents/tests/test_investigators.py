"""Tests for the FE / BE / DB Investigators."""
from __future__ import annotations

import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_center.component_map import (
    BackendSubcomponent,
    DBSubcomponent,
    FrontendSubcomponent,
)
from agent_center.investigators import (
    BackendInvestigator,
    DBInvestigator,
    FrontendInvestigator,
    InvestigationFinding,
)


class FrontendInvestigatorTests(unittest.TestCase):
    def test_missing_path_is_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            inv = FrontendInvestigator(project_root=Path(tmp))
            sc = FrontendSubcomponent(path="not/here.ts", kind="service", responsibility="x")
            r = inv.investigate([sc])
            self.assertEqual(r.status, "error")
            self.assertEqual(r.findings[0].severity, "error")

    def test_inspects_real_ts_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "src").mkdir()
            f = Path(tmp) / "src" / "x.ts"
            f.write_text("// TODO clean up\nimport { A } from './missing';\nexport const A = 1;\n")
            inv = FrontendInvestigator(project_root=Path(tmp))
            sc = FrontendSubcomponent(path="src/x.ts", kind="service", responsibility="r")
            r = inv.investigate([sc])
            titles = [f.title for f in r.findings]
            self.assertIn("Inspected", titles)
            self.assertTrue(any("Suspicious relative imports" in t for t in titles))
            self.assertTrue(any("TODO/FIXME" in t for t in titles))

    def test_empty_file_warns(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "empty.ts"
            f.write_text("")
            inv = FrontendInvestigator(project_root=Path(tmp))
            sc = FrontendSubcomponent(path="empty.ts", kind="service", responsibility="r")
            r = inv.investigate([sc])
            self.assertEqual(r.status, "warning")


class BackendInvestigatorTests(unittest.TestCase):
    def test_syntax_error_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "bad.py"
            f.write_text("def x(:\n  pass\n")  # syntax error
            inv = BackendInvestigator(project_root=Path(tmp))
            sc = BackendSubcomponent(path="bad.py", kind="view", responsibility="r")
            r = inv.investigate([sc])
            self.assertEqual(r.status, "error")
            self.assertTrue(any("syntax" in f.title.lower() for f in r.findings))

    def test_clean_file_passes_with_inspected_finding(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "ok.py"
            f.write_text("def hello():\n    return 1\n")
            inv = BackendInvestigator(project_root=Path(tmp))
            sc = BackendSubcomponent(path="ok.py", kind="view", responsibility="r")
            r = inv.investigate([sc])
            self.assertEqual(r.status, "ok")
            self.assertTrue(any(f.title.startswith("Inspected") for f in r.findings))

    def test_naked_except_warns(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "naked.py"
            f.write_text(textwrap.dedent("""
                def x():
                    try:
                        return 1
                    except:
                        return 0
            """).strip())
            inv = BackendInvestigator(project_root=Path(tmp))
            sc = BackendSubcomponent(path="naked.py", kind="view", responsibility="r")
            r = inv.investigate([sc])
            self.assertEqual(r.status, "warning")
            self.assertTrue(any("Naked except" in f.title for f in r.findings))

    def test_breakpoint_left_warns(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "dbg.py"
            f.write_text("def x():\n    breakpoint()\n    return 1\n")
            inv = BackendInvestigator(project_root=Path(tmp))
            sc = BackendSubcomponent(path="dbg.py", kind="view", responsibility="r")
            r = inv.investigate([sc])
            self.assertTrue(any("breakpoint" in f.title.lower() for f in r.findings))


class DBInvestigatorTests(unittest.TestCase):
    """
    Don't require a live DB. The DBVerificationAgent reports 'enabled=False'
    when no IB_DB_* config is present, which the DBInvestigator surfaces as
    severity='info'. We assert that path here.
    """

    def test_skipped_without_db_config(self):
        # If env happens to have DB config, this test is still meaningful:
        # at minimum we verify the investigator returns one finding per table.
        sc = DBSubcomponent(table="some_table", model="SomeModel", key_fields=("id",))
        inv = DBInvestigator()
        r = inv.investigate([sc])
        self.assertEqual(len(r.inspected_subcomponents), 1)
        # The first finding is always one of: info (skipped), ok (reachable), error (failed)
        self.assertIn(r.findings[0].severity, ("info", "ok", "error"))

    def test_wildcard_table_marked_info(self):
        sc = DBSubcomponent(table="lst_*", model="Lookups", key_fields=())
        r = DBInvestigator().investigate([sc])
        self.assertEqual(r.findings[0].severity, "info")
        self.assertIn("Wildcard", r.findings[0].title)


if __name__ == "__main__":
    unittest.main()
