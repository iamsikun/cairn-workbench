"""Affiliation rows keep each source's provenance while evidence is held compactly."""

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

UNI = {
    "id": "https://openalex.org/I1",
    "ror": "https://ror.org/012345678",
    "display_name": "University One",
    "country_code": "US",
    "type": "education",
}


def record(names, details):
    return {
        "id": "paper-1",
        "journal_id": "aer",
        "journal": "American Economic Review",
        "issns": ["0002-8282"],
        "doi": "10.0000/paper-1",
        "alternate_dois": [],
        "title": "A paper",
        "authors": names,
        "author_details": details,
        "date": "2025-01-01",
        "date_precision": "day",
        "published_print": None,
        "published_online": None,
        "year": 2025,
        "url": "https://example.org/paper",
        "openalex_ids": ["https://openalex.org/W1"],
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
        "cairn_slug": "paper-1",
        "abstract_status": "unavailable_in_harvested_sources",
    }


def page(root, provider, body):
    folder = root / "raw" / provider / "aer"
    folder.mkdir(parents=True)
    with gzip.open(folder / "page-00001.json.gz", "wt", encoding="utf-8") as handle:
        json.dump(body, handle)
    (folder / "state.json").write_text(json.dumps({"complete": True, "pages": 1}))


class AffiliationProvenanceTests(unittest.TestCase):
    def test_each_affiliation_row_names_its_source(self):
        names = ["Jane Smith", "John Doe"]
        details = [
            {"name": "Jane Smith", "openalex_id": "https://openalex.org/A1", "affiliations": [UNI]},
            {"name": "John Doe"},
        ]
        crossref = {
            "DOI": "10.0000/paper-1",
            "author": [
                {"given": "Jane", "family": "Smith", "affiliation": [{"name": "University One"}]},
                {"given": "John", "family": "Doe", "affiliation": [{"name": "Unknown College"}]},
            ],
        }
        openalex = {
            "id": "https://openalex.org/W1",
            "doi": "https://doi.org/10.0000/paper-1",
            "authorships": [
                {"author": {"display_name": "Jane Smith", "id": "https://openalex.org/A1"}},
                {
                    "author": {"display_name": "John Doe", "id": "https://openalex.org/A2"},
                    "institutions": [UNI],
                },
            ],
        }
        with tempfile.TemporaryDirectory(prefix="cairn-provenance-") as tmp:
            root = Path(tmp)
            page(root, "crossref", {"response": {"message": {"items": [crossref]}}})
            page(root, "openalex", {"response": {"results": [openalex]}})
            with patch.object(catalog, "ROOT", root), patch.object(entities, "ROOT", root):
                with redirect_stdout(io.StringIO()):
                    catalog.sql_database([record(names, details)], [])
                with closing(sqlite3.connect(root / "catalog.sqlite")) as con:
                    rows = con.execute(
                        "SELECT position,institution_id,provider,link_basis,raw_name,evidence_json"
                        " FROM affiliations ORDER BY rowid"
                    ).fetchall()
                    aliases = con.execute("SELECT * FROM author_aliases ORDER BY rowid").fetchall()

        crossref = {
            "work_id": "10.0000/paper-1",
            "raw_file": "raw/crossref/aer/page-00001.json.gz",
            "match_basis": "same_paper_exact_author_name",
        }
        openalex = {
            "work_id": "https://openalex.org/W1",
            "raw_file": "raw/openalex/aer/page-00001.json.gz",
            "match_basis": "same_paper_exact_author_name",
        }
        unresolved = "unresolved-institution:" + entities.digest("unknown college")
        self.assertEqual(
            [(r[0], r[1], r[2], r[3], r[4], json.loads(r[5])) for r in rows],
            [
                (
                    1,
                    "ror:012345678",
                    "openalex",
                    "asserted_identifier",
                    "University One",
                    {"match_basis": "catalog_author_credit"},
                ),
                (
                    1,
                    "ror:012345678",
                    "crossref",
                    "exact_name_to_identifier",
                    "University One",
                    crossref,
                ),
                (2, unresolved, "crossref", "unresolved_label", "Unknown College", crossref),
                (2, "ror:012345678", "openalex", "asserted_identifier", "University One", openalex),
            ],
        )
        self.assertEqual(aliases, sorted(aliases))


if __name__ == "__main__":
    unittest.main()
