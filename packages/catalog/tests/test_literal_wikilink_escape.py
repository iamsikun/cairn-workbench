"""Literal source brackets must not become Cairn links in exported notes."""

import html
import tempfile
import unittest
from pathlib import Path

from cairn_catalog import catalog


class LiteralWikiLinkEscapeTests(unittest.TestCase):
    def test_math_notation_is_plain_text_and_abstract_round_trips(self):
        abstract = "The von Neumann norm is written [[A]], while [[B]] denotes a second operator &amp; its norm."
        record = {
            "title": "A result about [[A]]",
            "journal": "Fixture Journal",
            "authors": ["A. [[Author]]"],
            "url": "https://example.org/paper",
            "date": "2025-01-01",
            "date_precision": "day",
            "volume": "1",
            "issue": "1",
            "pages": "1-5",
            "doi": "10.0000/fixture",
            "published_print": None,
            "published_online": None,
            "article_number": None,
            "publication_unit": "issue",
            "entry_type": "article",
            "journal_membership": None,
            "field_sources": {"abstract": "crossref"},
            "abstract": abstract,
            "alternate_dois": [],
            "sources": [],
            "issue_id": "fixture:v1:i1",
        }
        issue = {"cairn_slug": "fixture-v1-i1", "volume": "1", "issue": "1"}
        _, parse = catalog.cairn_imports()
        with tempfile.TemporaryDirectory(prefix="cairn-wikilink-escape-") as tmp:
            path = Path(tmp) / "papers" / "fixture.md"
            catalog.yaml_note(
                path,
                {"title": record["title"], "kind": "paper", "created": "2026-10-13"},
                catalog.paper_body(record, issue),
            )
            note = parse(path)

        self.assertEqual(note.body_links, ["fixture-v1-i1"])
        self.assertIn(catalog.wiki_text(abstract), note.body)
        self.assertIn(html.unescape(abstract), html.unescape(note.body))
        self.assertNotIn("[[A]]", note.body)
        self.assertNotIn("[[B]]", note.body)


if __name__ == "__main__":
    unittest.main()
