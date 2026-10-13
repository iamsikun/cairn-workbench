import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from cairn_catalog import catalog, catalog_server, publication_status


class PublicationStageTests(unittest.TestCase):
    def test_missing_issue_alone_does_not_mean_forthcoming(self):
        self.assertEqual(
            publication_status.classify({"date": "1974", "volume": "20"})[0], "unassigned"
        )
        self.assertEqual(
            publication_status.classify(
                {"published_online": "2026-09-12", "published_print": "2026-10", "volume": "20"}
            )[0],
            "unassigned",
        )

    def test_online_first_can_have_a_volume_but_no_issue(self):
        self.assertEqual(
            publication_status.classify({"volume": "72", "published_online": "2026-09-12"})[0],
            "online_first",
        )
        self.assertEqual(
            publication_status.classify(
                {"volume": "72", "issue": "10", "published_online": "2026-09-12"}
            )[0],
            "issue_assigned",
        )

    def test_issue_assignment_updates_the_same_paper(self):
        journal = next(j for j in catalog.JOURNALS if j["id"] == "mnsc")
        raw = {
            "DOI": "10.1287/mnsc.2026.fixture",
            "title": ["A forthcoming paper"],
            "author": [{"given": "Jane", "family": "Scholar"}],
            "type": "journal-article",
            "published-online": {"date-parts": [[2026, 9, 12]]},
            "ISSN": ["0025-1909"],
            "publisher": "Institute for Operations Research and the Management Sciences (INFORMS)",
        }
        provenance = {
            "id": raw["DOI"],
            "provider": "crossref",
            "url": "https://doi.org/" + raw["DOI"],
            "retrieved_at": "fixture",
            "raw_file": "fixture",
        }
        with tempfile.TemporaryDirectory() as temp, patch.object(catalog, "ROOT", Path(temp)):
            with patch.object(
                catalog, "raw_records", return_value=iter([("crossref", journal, raw, provenance)])
            ):
                first, _, _, _ = catalog.compile_records()
            updated = {
                **raw,
                "volume": "72",
                "issue": "11",
                "published-print": {"date-parts": [[2026, 11]]},
            }
            with patch.object(
                catalog,
                "raw_records",
                return_value=iter([("crossref", journal, updated, provenance)]),
            ):
                second, issues, _, _ = catalog.compile_records()
        self.assertEqual(len(first), len(second))
        self.assertEqual(first[0]["id"], second[0]["id"])
        self.assertEqual(first[0]["cairn_slug"], second[0]["cairn_slug"])
        self.assertEqual(first[0]["publication_status"], "online_first")
        self.assertEqual(second[0]["publication_status"], "issue_assigned")
        self.assertEqual(second[0]["published_online"], "2026-09-12")
        self.assertEqual(second[0]["issue_id"], issues[0]["id"])

    def test_invalid_stage_is_rejected(self):
        with self.assertRaises(ValueError):
            publication_status.where("anything' OR 1=1")

    def test_stage_filters_select_unassigned_and_online_first_separately(self):
        with closing(sqlite3.connect(":memory:")) as con:
            con.row_factory = sqlite3.Row
            con.executescript("""
            CREATE TABLE journals(id TEXT,title TEXT);
            CREATE TABLE papers(id TEXT,title TEXT,date TEXT,date_precision TEXT,doi TEXT,journal_id TEXT,authors_json TEXT,volume TEXT,issue TEXT,issue_id TEXT,pages TEXT,entry_type TEXT,abstract TEXT,publication_status TEXT,publication_status_evidence TEXT);
            INSERT INTO journals VALUES('mnsc','Management Science');
            """)
            for i, stage in enumerate(["issue_assigned", "online_first", "unassigned"]):
                con.execute(
                    "INSERT INTO papers VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        str(i),
                        "Paper " + str(i),
                        "2026-09-12",
                        "day",
                        None,
                        "mnsc",
                        "[]",
                        "72" if i == 0 else None,
                        "10" if i == 0 else None,
                        "i1" if i == 0 else None,
                        None,
                        "article_or_other",
                        None,
                        stage,
                        "fixture",
                    ),
                )
            con.execute("ALTER TABLE papers ADD COLUMN record_json TEXT DEFAULT '{}'")
            self.assertEqual(catalog_server.papers_query(con, stage="online_first")["total"], 1)
            self.assertEqual(catalog_server.papers_query(con, stage="pending")["total"], 2)
            self.assertEqual(
                catalog_server.papers_query(con, stage="unassigned")["items"][0]["id"], "2"
            )
