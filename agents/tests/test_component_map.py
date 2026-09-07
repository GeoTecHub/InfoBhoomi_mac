"""Tests for agent_center.component_map — structure + drift checker."""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_center.component_map import (
    COMPONENT_MAP,
    all_entries,
    coverage_check,
    drift_check,
    function_ids,
    get_entry,
)
from agent_center.function_registry import all_functions


class StructureTests(unittest.TestCase):
    def test_all_entries_have_function_id(self):
        for entry in COMPONENT_MAP:
            self.assertTrue(entry.function_id, entry)

    def test_function_ids_unique(self):
        ids = function_ids()
        self.assertEqual(len(ids), len(set(ids)))

    def test_get_entry_finds_known(self):
        entry = get_entry("rrr.lifecycle")
        self.assertEqual(entry.function_id, "rrr.lifecycle")
        self.assertTrue(entry.frontend)
        self.assertTrue(entry.backend)

    def test_get_entry_raises_for_unknown(self):
        with self.assertRaises(KeyError):
            get_entry("nonexistent.function")


class CoverageTests(unittest.TestCase):
    def test_every_registry_function_has_a_map_entry(self):
        cov = coverage_check()
        self.assertEqual(cov["registry_only"], [], f"Missing map entries: {cov['registry_only']}")
        self.assertEqual(cov["map_only"], [], f"Stale map entries: {cov['map_only']}")
        self.assertTrue(cov["ok"])

    def test_runtime_dependencies_reference_known_function_ids(self):
        known = set(function_ids())
        for entry in COMPONENT_MAP:
            for dep in entry.runtime_dependencies:
                self.assertIn(dep, known, f"{entry.function_id} → unknown dep {dep}")


class DriftTests(unittest.TestCase):
    """
    Strict drift assertion runs only when IB_RUN_DRIFT_CHECK=true so unrelated
    test runs don't fail when working in a partial checkout. We always sanity-
    check that drift_check returns the expected shape.
    """

    def test_drift_check_shape(self):
        d = drift_check()
        for key in ("fe_root", "be_root", "missing_fe_paths", "missing_be_paths", "ok"):
            self.assertIn(key, d)
        self.assertIsInstance(d["missing_fe_paths"], list)
        self.assertIsInstance(d["missing_be_paths"], list)

    @unittest.skipUnless(
        os.environ.get("IB_RUN_DRIFT_CHECK", "").lower() in ("1", "true", "yes"),
        "Set IB_RUN_DRIFT_CHECK=true to enforce path-on-disk drift assertions.",
    )
    def test_no_drift_against_disk(self):
        d = drift_check()
        self.assertTrue(
            d["ok"],
            f"Component map drift detected.\n  FE missing: {d['missing_fe_paths']}\n  BE missing: {d['missing_be_paths']}",
        )


if __name__ == "__main__":
    unittest.main()
