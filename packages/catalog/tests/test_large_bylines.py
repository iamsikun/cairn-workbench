"""Regression coverage for matching provider evidence on long coauthor lists."""

import gzip
import io
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from cairn_catalog import catalog, entities


class LargeBylineMatchingTests(unittest.TestCase):
    def test_long_byline_aligns_and_ambiguous_initials_do_not_merge(self):
        names = [f"Author{i:03d} Researcher" for i in range(98)] + ["Jane Smith", "John Smith"]
        work_ids = ["https://openalex.org/W9000000001", "https://openalex.org/W9000000002"]
        record = {
            "id": "fixture-paper",
            "journal_id": "aer",
            "journal": "American Economic Review",
            "issns": ["0002-8282"],
            "doi": "10.0000/long-byline",
            "alternate_dois": [],
            "title": "A paper with a long byline",
            "authors": names,
            "author_details": [{"name": name} for name in names],
            "date": "2025-01-01",
            "date_precision": "day",
            "published_print": None,
            "published_online": None,
            "year": 2025,
            "url": "https://example.org/paper",
            "openalex_ids": work_ids,
            "repec_urls": [],
            "archive_urls": [],
            "sources": [],
            "field_sources": {},
            "entry_type": "article",
            "volume": "1",
            "issue": "1",
            "pages": "1-10",
            "abstract": None,
            "issue_id": None,
            "cairn_slug": "fixture-paper",
            "abstract_status": "unavailable_in_harvested_sources",
        }

        def observed(name, index):
            return {
                "author": {
                    "display_name": name,
                    "id": f"https://openalex.org/A{index + 1}",
                    "orcid": f"https://orcid.org/0000-0002-{index:04d}-0001",
                },
                "institutions": [],
            }

        aligned = [observed(name, i) for i, name in enumerate(names)]
        ambiguous = [observed("J. Smith", 500), observed("J Smith", 501)]
        works = [
            {
                "id": work_ids[0],
                "doi": "https://doi.org/10.0000/long-byline",
                "authorships": aligned,
            },
            {"id": work_ids[1], "doi": None, "authorships": ambiguous},
        ]

        with tempfile.TemporaryDirectory(prefix="cairn-long-byline-") as tmp:
            root = Path(tmp)
            raw = root / "raw/openalex/aer"
            raw.mkdir(parents=True)
            payload = {"retrieved_at": "2026-10-13T00:00:00+00:00", "response": {"results": works}}
            with gzip.open(raw / "page-00001.json.gz", "wt", encoding="utf-8") as handle:
                json.dump(payload, handle)
            (raw / "state.json").write_text(json.dumps({"complete": True, "pages": 1}))

            with patch.object(catalog, "ROOT", root), patch.object(entities, "ROOT", root):
                with redirect_stdout(io.StringIO()):
                    catalog.sql_database([record], [])
                with closing(sqlite3.connect(root / "catalog.sqlite")) as con:
                    authorships = dict(
                        con.execute(
                            "SELECT position,author_id FROM authorships WHERE paper_id='fixture-paper'"
                        )
                    )
                    identifiers = {
                        identifier
                        for (identifier,) in con.execute(
                            "SELECT identifier FROM author_identifiers"
                        )
                    }

        self.assertEqual(len(authorships), len(names))
        self.assertEqual(authorships[99], "orcid:0000-0002-0098-0001")
        self.assertEqual(authorships[100], "orcid:0000-0002-0099-0001")
        self.assertNotIn("orcid:0000-0002-0500-0001", identifiers)
        self.assertNotIn("orcid:0000-0002-0501-0001", identifiers)


if __name__ == "__main__":
    unittest.main()
