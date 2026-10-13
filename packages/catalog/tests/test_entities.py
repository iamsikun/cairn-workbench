"""Checks for namesake handling, date precision, affiliation counts, and Cairn import."""

import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from cairn_catalog import entities
from catalog_fixtures import synthetic_catalog


class DateAndIdentityTests(unittest.TestCase):
    def test_last_completed_quarter_and_rollover(self):
        self.assertEqual(
            entities.period_bounds(as_of="2026-10-11"), ("2026-07-01", "2026-09-30", "2026-Q3")
        )
        self.assertEqual(
            entities.period_bounds(as_of="2026-01-01"), ("2025-10-01", "2025-12-31", "2025-Q4")
        )
        self.assertEqual(entities.period_bounds(as_of="2026-04-01")[2], "2026-Q1")
        self.assertEqual(entities.period_bounds("2024-Q1")[1], "2024-03-31")
        with self.assertRaises(ValueError):
            entities.period_bounds("2026-Q5")

    def test_partial_and_unverified_dates(self):
        self.assertEqual(entities.date_bounds("2024-02"), ("2024-02-01", "2024-02-29", "month"))
        self.assertEqual(entities.date_bounds("2026"), ("2026-01-01", "2026-12-31", "year"))
        self.assertEqual(
            entities.date_bounds("2026-08-15", "provider_day_unverified")[2],
            "provider_date_unverified",
        )
        self.assertIsNone(entities.date_bounds("2026-02-30"))
        self.assertIsNone(entities.date_bounds("0"))

    def test_identifier_conflicts_do_not_merge_people(self):
        g = entities.IdentityGroups()
        first, second, oa = (
            "orcid:0000-0001-0000-0001",
            "orcid:0000-0001-0000-0002",
            "openalex:A123",
        )
        self.assertTrue(g.join(first, oa, {}))
        self.assertFalse(g.join(second, oa, {}))
        self.assertNotEqual(g.root(first), g.root(second))
        self.assertEqual(len(g.conflicts), 1)

    def test_source_provider_is_retained(self):
        item = entities.authors_for_work(
            {
                "author": [
                    {
                        "given": "Jane",
                        "family": "Smith",
                        "ORCID": "https://orcid.org/0000-0001-0000-0001",
                    }
                ]
            },
            "crossref",
        )[0]
        self.assertEqual(item["provider"], "crossref")


class QueryTests(unittest.TestCase):
    def setUp(self):
        self.con = sqlite3.connect(":memory:")
        self.con.row_factory = sqlite3.Row
        self.con.executescript("""
        CREATE TABLE journals(id TEXT,title TEXT);
        CREATE TABLE papers(id TEXT,title TEXT,journal_id TEXT,doi TEXT,volume TEXT,issue TEXT,pages TEXT,authors_json TEXT,cairn_slug TEXT,entry_type TEXT,publication_status TEXT DEFAULT 'issue_assigned',publication_status_evidence TEXT,record_json TEXT DEFAULT '{}');
        CREATE TABLE author_entities(id TEXT,display_name TEXT,identity_status TEXT,publication_count INTEGER);
        CREATE TABLE author_identifiers(identifier TEXT,author_id TEXT);
        CREATE TABLE author_aliases(author_id TEXT,name TEXT,normalized_name TEXT,provider TEXT);
        CREATE TABLE authorships(paper_id TEXT,position INTEGER,author_id TEXT);
        CREATE TABLE institution_entities(id TEXT,display_name TEXT,identity_status TEXT,publication_count INTEGER,openalex_id TEXT);
        CREATE TABLE institution_aliases(institution_id TEXT,name TEXT,normalized_name TEXT);
        CREATE TABLE affiliations(paper_id TEXT,position INTEGER,institution_id TEXT);
        CREATE TABLE publication_events(paper_id TEXT,basis TEXT,date TEXT,date_lower TEXT,date_upper TEXT,precision TEXT,provider TEXT);
        CREATE VIRTUAL TABLE entity_names USING fts5(kind UNINDEXED,entity_id UNINDEXED,name);
        INSERT INTO journals VALUES('aer','American Economic Review');
        INSERT INTO author_entities VALUES('openalex:A1','Jane Smith','source_identified',4),('openalex:A2','Jane Smith','source_identified',1);
        INSERT INTO author_aliases VALUES('openalex:A1','Jane Smith','jane smith','openalex'),('openalex:A2','Jane Smith','jane smith','openalex');
        INSERT INTO entity_names VALUES('author','openalex:A1','Jane Smith'),('author','openalex:A2','Jane Smith');
        INSERT INTO institution_entities VALUES('ror:012345678','University One','source_identified',4,'openalex:I1'),('ror:987654321','University Two','source_identified',1,'openalex:I2');
        INSERT INTO institution_aliases VALUES('ror:012345678','University One','university one'),('ror:987654321','University Two','university two');
        """)
        for n, date, precision in [
            (1, "2026-08", "month"),
            (2, "2026", "year"),
            (3, "2026-09-15", "provider_day_unverified"),
            (4, None, None),
        ]:
            pid = f"p{n}"
            self.con.execute(
                "INSERT INTO papers(id,title,journal_id,doi,volume,issue,pages,authors_json,cairn_slug,entry_type) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    pid,
                    "Paper " + str(n),
                    "aer",
                    "10.1/" + pid,
                    "1",
                    "1",
                    "1",
                    '["Jane Smith"]',
                    pid,
                    "article",
                ),
            )
            self.con.execute("INSERT INTO authorships VALUES(?,?,?)", (pid, 1, "openalex:A1"))
            self.con.execute("INSERT INTO affiliations VALUES(?,?,?)", (pid, 1, "ror:012345678"))
            if date:
                lo, hi, precision = entities.date_bounds(date, precision)
                self.con.execute(
                    "INSERT INTO publication_events VALUES(?,?,?,?,?,?,?)",
                    (pid, "issue", date, lo, hi, precision, "fixture"),
                )
        # A second coauthor with the same institution must not duplicate a paper count.
        self.con.execute("INSERT INTO authorships VALUES('p1',2,'openalex:A2')")
        self.con.execute("INSERT INTO affiliations VALUES('p1',2,'ror:012345678')")
        self.con.execute("INSERT INTO affiliations VALUES('p2',1,'ror:987654321')")
        self.con.execute(
            "INSERT INTO publication_events VALUES('p1','online','2026-06-30','2026-06-30','2026-06-30','day','fixture')"
        )

    def tearDown(self):
        self.con.close()

    def query(self, kind="author", value="openalex:A1", **kwargs):
        return entities.publication_query(kind, value, as_of="2026-10-11", con=self.con, **kwargs)

    def test_name_collision_requires_explicit_identity(self):
        with self.assertRaises(ValueError):
            entities.resolve_entity("author", "Jane Smith", self.con)
        self.assertEqual(
            entities.resolve_entity("author", "https://openalex.org/A2", self.con)["id"],
            "openalex:A2",
        )

    def test_publication_lists_retain_series_and_article_numbers(self):
        self.con.execute(
            "UPDATE papers SET record_json=? WHERE id='p1'",
            (
                json.dumps(
                    {
                        "volume_series": "second",
                        "publication_unit": "volume",
                        "article_number": "17",
                    }
                ),
            ),
        )
        item = next(p for p in self.query(period="all")["items"] if p["id"] == "p1")
        self.assertEqual(
            (item["volume_series"], item["publication_unit"], item["article_number"]),
            ("second", "volume", "17"),
        )

    def test_quarter_precision_and_missing_date(self):
        r = self.query()
        self.assertEqual(
            (r["certain_count"], r["uncertain_count"], r["undated_publications_all_years"]),
            (1, 2, 1),
        )
        self.assertEqual([p["id"] for p in r["items"]], ["p1"])
        r = self.query(include_uncertain=True)
        self.assertEqual(r["total"], 3)
        self.assertEqual(sum(p["period_membership"] == "uncertain" for p in r["items"]), 2)

    def test_institution_counts_papers_once(self):
        r = self.query("institution", "ror:012345678")
        self.assertEqual((r["certain_count"], r["uncertain_count"]), (1, 2))
        # University Two is attached only to p2, not all of Jane Smith's papers.
        self.assertEqual(
            self.query("institution", "ror:987654321", include_uncertain=True)["total"], 1
        )

    def test_online_and_issue_dates_are_separate(self):
        self.assertEqual(self.query(basis="online")["total"], 0)
        self.assertEqual(self.query(period="2026-Q2", basis="online")["total"], 1)
        self.assertEqual(self.query(basis="print")["undated_publications_all_years"], 4)

    def test_all_years_bibliography_includes_undated_papers(self):
        result = self.query(period="all")
        self.assertEqual(result["total"], 4)
        self.assertEqual({p["id"] for p in result["items"]}, {"p1", "p2", "p3", "p4"})
        self.assertEqual(result["uncertain_count"], 0)

    def test_year_accepts_year_precision_but_custom_range_remains_uncertain(self):
        result = self.query(period="2026")
        self.assertEqual((result["certain_count"], result["uncertain_count"]), (3, 0))
        result = self.query(period="all", start_date="2026-08-01", end_date="2026-08-31")
        self.assertEqual((result["certain_count"], result["uncertain_count"]), (1, 2))

    def test_stage_filters_apply_to_entity_counts(self):
        self.con.execute("UPDATE papers SET publication_status='online_first' WHERE id='p1'")
        self.con.execute("UPDATE papers SET publication_status='unassigned' WHERE id='p4'")
        self.assertEqual(self.query(stage="online_first")["total"], 1)
        result = self.query(period="all", stage="pending")
        self.assertEqual(result["total"], 2)
        self.assertEqual(result["undated_publications_all_years"], 1)

    def test_same_name_coauthors_link_to_different_source_identities(self):
        self.con.execute(
            "UPDATE papers SET authors_json='[\"Jane Smith\",\"Jane Smith\"]' WHERE id='p1'"
        )
        paper = next(p for p in self.query(period="all")["items"] if p["id"] == "p1")
        self.assertEqual(
            [a["author_id"] for a in paper["author_entities"]], ["openalex:A1", "openalex:A2"]
        )
        self.assertEqual(
            [a["observed_name"] for a in paper["author_entities"]], ["Jane Smith", "Jane Smith"]
        )

    def test_result_bylines_keep_first_ten_and_report_full_count(self):
        names = [f"Author {i}" for i in range(1, 13)]
        self.con.execute("UPDATE papers SET authors_json=? WHERE id='p1'", (json.dumps(names),))
        self.con.executemany(
            "INSERT INTO authorships VALUES(?,?,?)",
            [("p1", i, "openalex:A1" if i % 2 else "openalex:A2") for i in range(3, 13)],
        )
        paper = next(p for p in self.query(period="all")["items"] if p["id"] == "p1")
        self.assertEqual(paper["author_count"], 12)
        self.assertEqual(paper["authors"], names[:10])
        self.assertEqual([a["position"] for a in paper["author_entities"]], list(range(1, 11)))

    def test_pagination_does_not_change_count(self):
        first = self.query(include_uncertain=True, limit=1)
        second = self.query(include_uncertain=True, limit=1, offset=1)
        self.assertEqual(first["total"], second["total"])
        self.assertNotEqual(first["items"][0]["id"], second["items"][0]["id"])

    def test_search_matches_token_boundaries(self):
        self.con.execute(
            "INSERT INTO author_aliases VALUES('openalex:A2','Jane Evangelist','jane evangelist','openalex')"
        )
        self.con.execute(
            "INSERT INTO entity_names VALUES('author','openalex:A2','Jane Evangelist')"
        )
        self.assertEqual(entities.entity_search("author", "Jane List", con=self.con)["total"], 0)


class NativeImportTests(unittest.TestCase):
    def test_database_publish_includes_graph_and_preserves_previous_on_failure(self):
        from cairn_catalog import catalog

        with tempfile.TemporaryDirectory(prefix="cairn-entity-build-") as tmp:
            root = Path(tmp)
            record = synthetic_catalog(root)
            with patch.object(catalog, "ROOT", root), patch.object(entities, "ROOT", root):
                with closing(entities.connect(True, db=root / "catalog.sqlite")) as con:
                    self.assertEqual(
                        con.execute("SELECT COUNT(*) FROM authorships").fetchone()[0],
                        len(record["authors"]),
                    )
                    self.assertEqual(con.execute("PRAGMA integrity_check").fetchone()[0], "ok")
                previous = (root / "catalog.sqlite").read_bytes()
                with patch.object(
                    entities, "build_entities", side_effect=RuntimeError("fixture failure")
                ):
                    with self.assertRaises(RuntimeError):
                        catalog.sql_database([record], [])
                self.assertEqual((root / "catalog.sqlite").read_bytes(), previous)

    def test_import_and_preserve_existing_personal_note(self):
        from cairn_catalog import catalog

        KB, parse = catalog.cairn_imports()
        connect = entities.connect
        with tempfile.TemporaryDirectory(prefix="cairn-entity-test-") as tmp:
            data, workspace = Path(tmp) / "catalog", Path(tmp) / "kb"
            data.mkdir()
            workspace.mkdir()
            synthetic_catalog(data)
            (workspace / ".cairn").write_text("", encoding="utf-8")
            database = lambda readonly=False, db=None: connect(readonly, db=data / "catalog.sqlite")
            with (
                patch.object(catalog, "WORKSPACE", workspace),
                patch.object(catalog, "ROOT", data),
                patch.object(entities, "connect", database),
            ):
                result = entities.import_entity("author", "orcid:0000-0002-0000-0001")
                kb = KB(workspace, "research")
                note = kb.resolve(result["slug"])
                self.assertEqual(
                    parse(note.path).meta["catalog_entity_id"], "orcid:0000-0002-0000-0001"
                )
                self.assertIn("A synthetic paper", note.body)
                body = note.body + "\n\nMy reading observation.\n"
                kb.save(kind="note", title=note.title, body=body, revision=note.revision)
                saved_body = kb.resolve(result["slug"]).body
                again = entities.import_entity("author", "orcid:0000-0002-0000-0001")
                self.assertEqual(again["status"], "preserved_existing_note")
                self.assertEqual(kb.resolve(result["slug"]).body, saved_body)

    def test_import_requires_a_configured_workspace(self):
        from cairn_catalog import catalog

        with patch.object(catalog, "WORKSPACE", None), self.assertRaises(SystemExit):
            catalog.open_kb()


if __name__ == "__main__":
    unittest.main()
