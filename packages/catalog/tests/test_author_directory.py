import json
import sqlite3
import unittest
from contextlib import closing

from cairn_catalog import author_directory, entities


class AuthorDirectoryTests(unittest.TestCase):
    def test_compound_names_suffixes_and_comma_notation(self):
        self.assertEqual(author_directory.name_parts("Jan van der Meer"), ("van der Meer", "Jan"))
        self.assertEqual(author_directory.name_parts("Jane Smith Jr."), ("Smith", "Jane"))
        self.assertEqual(author_directory.name_parts("Smith, Jane"), ("Smith", "Jane"))
        self.assertLess(
            author_directory.inferred_sort_key("Anna Ångström"),
            author_directory.inferred_sort_key("Amy Baker"),
        )

    def test_recorded_family_name_controls_order_and_pagination(self):
        with closing(sqlite3.connect(":memory:")) as con:
            con.row_factory = sqlite3.Row
            con.executescript("""
            CREATE TABLE author_entities(id TEXT PRIMARY KEY,display_name TEXT,identity_status TEXT,publication_count INTEGER);
            CREATE TABLE authors(paper_id TEXT,position INTEGER,details_json TEXT);
            CREATE TABLE authorships(paper_id TEXT,position INTEGER,author_id TEXT);
            INSERT INTO author_entities VALUES('a','Manuel García Márquez','source_identified',1),('b','Zoe Hidalgo','source_identified',500),('c','Jane Smith Jr.','source_identified',20);
            INSERT INTO authorships VALUES('p1',1,'a');
            """)
            con.execute(
                "INSERT INTO authors VALUES('p1',1,?)",
                (json.dumps({"family": "García Márquez", "given": "Manuel"}),),
            )
            author_directory.build(con)
            first = entities.entity_search("author", limit=1, con=con)
            second = entities.entity_search("author", limit=1, offset=1, con=con)
            self.assertEqual(first["items"][0]["id"], "a")
            self.assertEqual(first["items"][0]["family_name"], "García Márquez")
            self.assertEqual(first["items"][0]["surname_source"], "recorded_family_name")
            self.assertEqual(second["items"][0]["id"], "b")
            self.assertEqual(first["total"], second["total"])
