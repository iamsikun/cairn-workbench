"""Discovery insights must not change when SQLite chooses a different row order."""

import sqlite3
import unittest

from cairn_catalog import insights


class InsightOrderTests(unittest.TestCase):
    def test_rising_terms_are_independent_of_input_order(self):
        papers = [
            ("d", "Signal alpha beta gamma"),
            ("a", "Signal delta epsilon zeta"),
            ("c", "Signal eta theta iota"),
            ("b", "Signal kappa lambda mu"),
        ]
        baseline = [("old" + str(i), "Unrelated historical evidence") for i in range(10)]
        first = insights.rising_terms(papers, baseline)
        self.assertTrue(first)
        self.assertEqual(first, insights.rising_terms(list(reversed(papers)), baseline))

    def test_build_survives_reversed_unordered_selects(self):
        with sqlite3.connect(":memory:") as con:
            con.executescript("""
                CREATE TABLE papers(id TEXT PRIMARY KEY, journal_id TEXT, title TEXT, entry_type TEXT);
                CREATE TABLE publication_events(paper_id TEXT, date_lower TEXT, date_upper TEXT);
                CREATE TABLE authorships(paper_id TEXT, author_id TEXT);
                CREATE TABLE author_entities(id TEXT, display_name TEXT, identity_status TEXT);
                CREATE TABLE affiliations(paper_id TEXT, institution_id TEXT);
                CREATE TABLE institution_entities(id TEXT, display_name TEXT, identity_status TEXT);
            """)
            for ident, title in [
                ("d", "Signal alpha beta gamma"),
                ("a", "Signal delta epsilon zeta"),
                ("c", "Signal eta theta iota"),
                ("b", "Signal kappa lambda mu"),
            ]:
                con.execute("INSERT INTO papers VALUES(?,?,?,?)", (ident, "aer", title, "article"))
                con.execute(
                    "INSERT INTO publication_events VALUES(?,?,?)",
                    (ident, "2026-09-01", "2026-09-01"),
                )
            original = insights.build(con, "2026-10-12")
            con.execute("PRAGMA reverse_unordered_selects=ON")
            self.assertEqual(original, insights.build(con, "2026-10-12"))


if __name__ == "__main__":
    unittest.main()
