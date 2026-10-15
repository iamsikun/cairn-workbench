import gzip
import json
import os
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from pathlib import Path
from unittest.mock import patch

from cairn_catalog import entities
from cairn_catalog import update_catalog as updater

from cairn.store import KB, init


class FlexiblePeriodTests(unittest.TestCase):
    def test_calendar_year_and_block(self):
        self.assertEqual(entities.period_bounds("2024")[:2], ("2024-01-01", "2024-12-31"))
        self.assertEqual(entities.period_bounds("2020:2024")[:2], ("2020-01-01", "2024-12-31"))

    def test_rolling_leap_and_quarters(self):
        self.assertEqual(
            entities.period_bounds("last-5-years", "2024-02-29")[:2], ("2019-03-01", "2024-02-29")
        )
        self.assertEqual(
            entities.period_bounds("last-10-years", "2026-10-11")[:2], ("2016-10-12", "2026-10-11")
        )
        self.assertEqual(
            entities.period_bounds("last-2-quarters", "2026-10-11")[:2],
            ("2026-04-12", "2026-10-11"),
        )

    def test_arbitrary_and_open_bounds(self):
        self.assertEqual(
            entities.period_bounds(start_date="2023-04-17", end_date="2026-08-03")[:2],
            ("2023-04-17", "2026-08-03"),
        )
        self.assertEqual(entities.period_bounds(start_date="2020-01-01")[1], "9999-12-31")
        with self.assertRaises(ValueError):
            entities.period_bounds(start_date="2026-10-12", end_date="2026-10-11")


class RefreshTests(unittest.TestCase):
    def test_catalog_entrypoint_links_survive_the_hosted_runner(self):
        for hosted in (False, True):
            with self.subTest(hosted=hosted), tempfile.TemporaryDirectory() as temp:
                root = Path(temp) / "catalog"
                root.mkdir()
                workspace = Path(temp) / "kb"
                init(workspace)
                kb = KB(workspace)
                kb.save(
                    kind="note",
                    title="Journal catalog",
                    body=(
                        "# Journal catalog\n\n<!-- catalog-refresh:start -->\n"
                        "old generated status\n<!-- catalog-refresh:end -->\n\n"
                        "My own catalog observations.\n"
                    ),
                )
                updater.catalog.atomic_json(
                    root / "coverage.json",
                    {
                        "as_of": "2026-10-14",
                        "total_entries": 3,
                        "total_issues": 2,
                        "total_abstracts": 1,
                    },
                )
                updater.catalog.atomic_json(
                    root / "entity-coverage.json",
                    {"identified_author_entities": 4, "identified_institutions": 5},
                )
                env = {
                    "GITHUB_ACTIONS": "true" if hosted else "false",
                    "GITHUB_SERVER_URL": "https://github.com",
                    "GITHUB_REPOSITORY": "fixture/private-kb",
                    "GITHUB_RUN_ID": "123",
                }
                with (
                    patch.dict(os.environ, env),
                    patch.object(updater.catalog, "open_kb", return_value=kb),
                ):
                    updater.sync_entrypoints(root)
                body = kb.get("journal-catalog")["body"]
                self.assertIn("My own catalog observations.", body)
                self.assertIn("**3 entries", body)
                if hosted:
                    self.assertIn("https://github.com/fixture/private-kb/actions/runs/123", body)
                    self.assertNotIn(str(root), body)
                else:
                    self.assertIn(str(root / "catalog.html"), body)
                    self.assertIn(str(root / "update-report.json"), body)

    def test_first_refresh_stages_and_publishes_without_an_existing_edition(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "new" / "catalog"

            def build(_):
                stage = updater.catalog.ROOT
                self.assertTrue((stage / "journals.json").exists())
                updater.catalog.atomic_json(
                    stage / "coverage.json",
                    {"total_entries": 1, "journal_membership": {}},
                )
                (stage / "catalog.html").write_text("first verified edition")

            with (
                patch.object(updater, "refresh_service", return_value=[]),
                patch.object(updater.catalog, "harvest_repec"),
                patch.object(updater.catalog, "harvest_publisher"),
                patch("cairn_catalog.publisher_archives.harvest_jmlr"),
                patch.object(updater.catalog, "build", side_effect=build),
                patch.object(updater.catalog, "validate"),
                patch.object(updater.build_browser, "build", return_value={"assets": "fixture"}),
                patch.object(updater.build_browser, "prune_assets", return_value=[]),
                patch.object(updater.verify_offline, "verify", return_value=1),
                patch.object(updater.personalize, "run", return_value={}),
            ):
                result = updater.refresh(root)
            self.assertEqual(result["mode"], "initial")
            self.assertEqual(result["entry_change"], 1)
            self.assertEqual((root / "catalog.html").read_text(), "first verified edition")
            self.assertTrue((root / "update-state.json").exists())
            self.assertEqual(
                json.loads((root / "journals.json").read_text()), updater.catalog.JOURNALS
            )

    def test_archive_outages_are_warnings_not_a_failed_refresh(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "catalog"

            def build(_):
                stage = updater.catalog.ROOT
                updater.catalog.atomic_json(
                    stage / "coverage.json", {"total_entries": 1, "journal_membership": {}}
                )
                (stage / "catalog.html").write_text("edition")

            down = ConnectionError("archive down")
            with (
                patch.object(updater, "refresh_service", return_value=[]),
                patch.object(updater.catalog, "harvest_repec", side_effect=down),
                patch.object(updater.catalog, "harvest_publisher"),
                patch("cairn_catalog.publisher_archives.harvest_jmlr", side_effect=down),
                patch.object(updater.catalog, "build", side_effect=build),
                patch.object(updater.catalog, "validate"),
                patch.object(updater.build_browser, "build", return_value={"assets": "fixture"}),
                patch.object(updater.build_browser, "prune_assets", return_value=[]),
                patch.object(updater.verify_offline, "verify", return_value=1),
                patch.object(updater.personalize, "run", return_value={}),
            ):
                result = updater.refresh(root)
            report = json.loads((root / "update-report.json").read_text())
            self.assertEqual(report["status"], "success", result)
            warnings = " ".join(report["warnings"])
            self.assertIn("JMLR archive unavailable", warnings)
            self.assertIn("RePEc unavailable", warnings)

    def test_retry_after_accepts_seconds_and_http_dates(self):
        later = datetime.now(UTC) + timedelta(seconds=30)
        self.assertEqual(updater.catalog.retry_after_seconds("5"), 5)
        self.assertAlmostEqual(
            updater.catalog.retry_after_seconds(format_datetime(later, usegmt=True)), 30, delta=2
        )
        self.assertEqual(updater.catalog.retry_after_seconds("soon"), 0)
        self.assertEqual(updater.catalog.retry_after_seconds(None), 0)

    def test_failed_first_build_does_not_claim_a_published_edition(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "new-catalog"
            with patch.object(updater.catalog, "build", side_effect=RuntimeError("build failed")):
                with self.assertRaisesRegex(RuntimeError, "build failed"):
                    updater.refresh(root, rebuild_only=True)
            self.assertFalse((root / "coverage.json").exists())
            self.assertFalse((root / "update-state.json").exists())
            self.assertEqual(
                json.loads((root / "update-report.json").read_text())["status"], "failed"
            )

    def test_concurrent_source_update_prevents_stale_publication(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "raw").mkdir()
            (root / "cairn-library").mkdir()
            (root / "journals.json").write_text("[]")
            (root / "coverage.json").write_text('{"as_of":"2026-10-12","total_entries":1}')
            (root / "catalog.html").write_text("previous edition")
            (root / "update-state.json").write_text('{"crossref_until":"2026-10-10"}')

            def build(_):
                updater.catalog.atomic_json(
                    updater.catalog.ROOT / "coverage.json",
                    {"total_entries": 1, "journal_membership": {}},
                )
                (root / "raw/new-evidence.json").write_text('{"new":"source evidence"}')

            with (
                patch.object(updater.catalog, "build", side_effect=build),
                patch.object(updater.catalog, "validate"),
                patch.object(updater.build_browser, "build", return_value={}),
                patch.object(updater.verify_offline, "verify", return_value=0),
            ):
                with self.assertRaisesRegex(RuntimeError, "live source cache changed"):
                    updater.refresh(root, rebuild_only=True)
            self.assertEqual((root / "catalog.html").read_text(), "previous edition")
            self.assertEqual(
                json.loads((root / "update-state.json").read_text())["crossref_until"], "2026-10-10"
            )
            self.assertTrue((root / "raw/new-evidence.json").exists())

    def test_failed_build_preserves_live_catalog_and_checkpoint(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "raw").mkdir()
            (root / "cairn-library").mkdir()
            (root / "journals.json").write_text("[]")
            (root / "coverage.json").write_text('{"as_of":"2026-10-11"}')
            (root / "catalog.html").write_text("previous edition")
            (root / "update-state.json").write_text('{"crossref_until":"2026-10-10"}')
            with patch.object(
                updater.catalog, "build", side_effect=RuntimeError("fixture failed validation")
            ):
                with self.assertRaises(RuntimeError):
                    updater.refresh(root, rebuild_only=True)
            self.assertEqual((root / "catalog.html").read_text(), "previous edition")
            self.assertEqual(
                json.loads((root / "update-state.json").read_text())["crossref_until"], "2026-10-10"
            )
            self.assertEqual(
                json.loads((root / "update-report.json").read_text())["status"], "failed"
            )
            self.assertEqual(updater.catalog.ROOT, updater.ROOT)

    def test_generated_note_preserves_creation_and_hardlinked_previous_file(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            previous = root / "previous.md"
            staged = root / "staged.md"
            updater.catalog.yaml_note(
                previous, {"title": "Example", "created": "2020-01-01"}, "Old body"
            )
            import os

            os.link(previous, staged)
            updater.catalog.yaml_note(
                staged, {"title": "Example", "created": "2026-10-11"}, "Updated body"
            )
            self.assertIn("2020-01-01", staged.read_text())
            self.assertIn("Old body", previous.read_text())
            self.assertNotIn("Updated body", previous.read_text())

    def test_upsert_replaces_metadata_and_is_idempotent(self):
        old = {
            "DOI": "10.1/a",
            "title": ["Old"],
            "abstract": "Removed",
            "author": [{"family": "One"}],
        }
        new = {"DOI": "10.1/a", "title": ["Corrected"], "author": [{"family": "Two"}]}
        records, timestamps = {"10.1/a": old}, {"10.1/a": "old-date"}
        self.assertEqual(updater.upsert(records, timestamps, [new], "crossref", "new-date"), (0, 1))
        self.assertNotIn("abstract", records["10.1/a"])
        self.assertEqual(
            updater.upsert(records, timestamps, [new], "crossref", "later-date"), (0, 0)
        )
        self.assertEqual(timestamps["10.1/a"], "new-date")

    def test_provider_refresh_preserves_baseline_and_timestamps(self):
        class Client:
            def get(self, url, params):
                self.params = params
                return self

            def json(self):
                return {
                    "message": {
                        "items": [{"DOI": "10.1/new", "title": ["New"]}],
                        "next-cursor": "next",
                        "total-results": 1,
                    }
                }

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            folder = root / "raw/crossref/aer"
            folder.mkdir(parents=True)
            (folder / "state.json").write_text(json.dumps({"complete": True, "pages": 1}))
            with gzip.open(folder / "page-00001.json.gz", "wt") as h:
                json.dump(
                    {
                        "retrieved_at": "original",
                        "response": {"message": {"items": [{"DOI": "10.1/old", "title": ["Old"]}]}},
                    },
                    h,
                )
            client = Client()
            with patch.object(updater.catalog, "JOURNALS", [updater.catalog.JOURNALS[0]]):
                result = updater.refresh_service(
                    "crossref", root, "2026-09-27", "2026-10-11", "2024-10-11", client
                )
            records, timestamps, state = updater.read_cache(folder, "crossref")
            self.assertEqual(set(records), {"10.1/old", "10.1/new"})
            self.assertEqual(timestamps["10.1/old"], "original")
            self.assertEqual(result[0]["added"], 1)
            self.assertIn("from-index-date:2026-09-27", client.params["filter"])
            self.assertTrue(state["complete"])

    def test_failed_publication_restores_previous_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            stage, backup = root / "stage", root / "backup"
            stage.mkdir()
            for name in ["a.json", "catalog.html"]:
                (root / name).write_text("old-" + name)
                (stage / name).write_text("new-" + name)
            replace = Path.replace

            def fail_last(path, target):
                if path == stage / "catalog.html":
                    raise OSError("fixture publication failure")
                return replace(path, target)

            with patch.object(Path, "replace", fail_last):
                with self.assertRaises(OSError):
                    updater.publish(stage, root, backup)
            self.assertEqual((root / "a.json").read_text(), "old-a.json")
            self.assertEqual((root / "catalog.html").read_text(), "old-catalog.html")

    def test_interrupted_publication_is_recovered(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            stage, backup = root / "stage", root / "backup"
            stage.mkdir()
            backup.mkdir()
            (backup / "catalog.html").write_text("old")
            (root / "catalog.html").write_text("new")
            (root / "update-pending.json").write_text(
                json.dumps(
                    {
                        "stage": str(stage),
                        "backup": str(backup),
                        "names": ["catalog.html"],
                        "existing": ["catalog.html"],
                    }
                )
            )
            updater.recover_pending(root)
            self.assertEqual((root / "catalog.html").read_text(), "old")
            self.assertEqual((stage / "catalog.html").read_text(), "new")
            self.assertFalse((root / "update-pending.json").exists())

    def test_split_browser_publication_rolls_back_pages_and_retains_old_assets(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            stage, backup = root / "stage", root / "backup"
            stage.mkdir()
            (root / "catalog-assets-old").mkdir()
            (root / "catalog-assets-old/data.js").write_text("old data")
            (stage / "catalog-assets-new").mkdir()
            (stage / "catalog-assets-new/data.js").write_text("new data")
            for name in [
                "catalog.html",
                "search.html",
                "authors.html",
                "institutions.html",
                "browser-build.json",
            ]:
                (root / name).write_text("old " + name)
                (stage / name).write_text("new " + name)
            replace = Path.replace

            def fail_last(path, target):
                if path == stage / "catalog.html":
                    self.assertTrue((root / "catalog-assets-new/data.js").exists())
                    raise OSError("publication interrupted")
                return replace(path, target)

            with patch.object(Path, "replace", fail_last):
                with self.assertRaises(OSError):
                    updater.publish(stage, root, backup)
            self.assertEqual((root / "catalog-assets-old/data.js").read_text(), "old data")
            self.assertFalse((root / "catalog-assets-new").exists())
            for name in [
                "catalog.html",
                "search.html",
                "authors.html",
                "institutions.html",
                "browser-build.json",
            ]:
                self.assertEqual((root / name).read_text(), "old " + name)
