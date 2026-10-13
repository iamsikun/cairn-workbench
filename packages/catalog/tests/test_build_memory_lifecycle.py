"""Ensure normalized paper records are released before graph construction."""

import json
import tempfile
import unittest
import weakref
from pathlib import Path
from unittest.mock import patch

from cairn_catalog import catalog, entities


class WeakRecord(dict):
    __slots__ = ("__weakref__",)


class BuildMemoryLifecycleTests(unittest.TestCase):
    def test_build_releases_records_before_graph_and_streams_library_input(self):
        with tempfile.TemporaryDirectory(prefix="cairn-build-lifecycle-") as tmp:
            root = Path(tmp)
            record = WeakRecord(id="paper-1", title="Fixture")
            reference = weakref.ref(record)
            holder = [[record]]
            del record
            report = {
                "total_entries": 1,
                "total_issues": 0,
                "total_abstracts": 0,
                "duplicates_merged": 0,
            }
            events = []

            def compile_fixture():
                return holder.pop(), [], {}, 0

            def coverage_fixture(records, issues, raw_counts, duplicates):
                return report

            def make_metadata_db(records, issues, build_graph=True):
                self.assertFalse(build_graph)
                path = root / "catalog.sqlite.tmp"
                path.write_text("metadata db")
                return path

            def build_graph_fixture(db):
                self.assertIsNone(
                    reference(), "normalized records must be collected before graph build"
                )
                self.assertTrue(db.exists())
                events.append("graph")

            def library_fixture(records, issues, report_arg):
                self.assertEqual(events, ["graph"])
                self.assertEqual([row["id"] for row in records], ["paper-1"])
                events.append("library")

            with (
                patch.object(catalog, "ROOT", root),
                patch.object(catalog, "compile_records", new=compile_fixture),
                patch.object(catalog, "coverage", new=coverage_fixture),
                patch.object(catalog, "sql_database", new=make_metadata_db),
                patch.object(catalog, "write_coverage", new=lambda _: None),
                patch.object(catalog, "write_library", new=library_fixture),
                patch.object(entities, "build_entities", new=build_graph_fixture),
            ):
                catalog.build(args=None)

            self.assertEqual(events, ["graph", "library"])
            self.assertEqual((root / "catalog.sqlite").read_text(), "metadata db")
            self.assertEqual(json.loads((root / "coverage.json").read_text())["total_entries"], 1)


if __name__ == "__main__":
    unittest.main()
