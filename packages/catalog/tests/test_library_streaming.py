"""Regression tests for streaming the native Cairn library export."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cairn_catalog import catalog


class LibraryStreamingTests(unittest.TestCase):
    def test_generator_is_consumed_lazily_and_native_links_remain(self):
        with tempfile.TemporaryDirectory(prefix="cairn-library-stream-") as tmp:
            root = Path(tmp)
            library = root / "cairn-library/research"
            (library / "papers").mkdir(parents=True)
            (library / "notes").mkdir(parents=True)
            (root / "entity-coverage.json").write_text(
                json.dumps({"identified_author_entities": 1, "identified_institutions": 0})
            )
            journal = {
                "id": "fixture",
                "title": "Fixture Journal",
                "abbreviation": "FJ",
                "aliases": [],
                "issns": ["1234-5678"],
                "url": "https://example.org/archive",
                "start_year": 2000,
            }
            issue = {
                "id": "fixture:v1:i1",
                "cairn_slug": "fixture-volume-1-issue-1",
                "journal_id": "fixture",
                "journal": "Fixture Journal",
                "volume": "1",
                "issue": "1",
                "year": 2025,
                "date": "2025-01-01",
                "date_precision": "day",
                "entry_count": 1,
                "abstract_count": 1,
                "coverage_status": "metadata",
                "url": None,
            }
            report = {
                "total_entries": 2,
                "total_abstracts": 1,
                "journals": {
                    "fixture": {
                        "entries": 2,
                        "issues": 1,
                        "abstracts": 1,
                        "first_year": 2025,
                        "last_year": 2025,
                    }
                },
            }

            def paper(identity, slug, issue_id):
                return {
                    "id": identity,
                    "source": "doi:" + identity,
                    "cairn_slug": slug,
                    "title": f"Paper {identity}",
                    "journal_id": "fixture",
                    "journal": "Fixture Journal",
                    "issns": ["1234-5678"],
                    "authors": ["Alice Example", "Bob Example"],
                    "doi": f"10.0000/{identity}",
                    "alternate_dois": [],
                    "date": "2025-01-01",
                    "date_precision": "day",
                    "published_print": None,
                    "published_online": None,
                    "year": 2025,
                    "volume": "1" if issue_id else None,
                    "volume_series": None,
                    "publication_unit": "issue",
                    "issue": "1" if issue_id else None,
                    "article_number": None,
                    "pages": "1-10",
                    "issue_id": issue_id,
                    "entry_type": "article",
                    "publication_status": "issue_assigned",
                    "publication_status_evidence": "fixture",
                    "url": "https://example.org/paper",
                    "abstract": "An abstract." if issue_id else None,
                    "abstract_status": "available" if issue_id else "unavailable",
                    "field_sources": {"date": "crossref", "abstract": "crossref"},
                    "openalex_ids": [],
                    "repec_urls": [],
                    "archive_urls": [],
                    "sources": [],
                }

            first_path = library / "papers/first-paper.md"

            def records():
                yield paper("p1", "first-paper", issue["id"])
                # An eager list conversion would request the next item before it
                # has materialized the first paper note.
                self.assertTrue(first_path.exists())
                yield paper("p2", "second-paper", None)

            with patch.object(catalog, "ROOT", root), patch.object(catalog, "JOURNALS", [journal]):
                catalog.write_library(records(), [issue], report)

            paper_note = first_path.read_text()
            issue_note = (library / "notes/fixture-volume-1-issue-1.md").read_text()
            self.assertIn("Alice Example; Bob Example", paper_note)
            self.assertIn("[[fixture-volume-1-issue-1]]", paper_note)
            self.assertIn("[[first-paper|Paper p1]]", issue_note)
            self.assertIn("Alice Example; Bob Example", issue_note)
            self.assertTrue((library / "papers/second-paper.md").exists())


if __name__ == "__main__":
    unittest.main()
