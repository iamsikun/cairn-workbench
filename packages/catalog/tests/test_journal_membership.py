import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cairn_catalog import catalog, journal_membership


class JournalMembershipTests(unittest.TestCase):
    def setUp(self):
        self.journal = next(j for j in catalog.JOURNALS if j["id"] == "mnsc")
        self.good = {
            "DOI": "10.1287/mnsc.2026.example",
            "title": ["An actual journal paper"],
            "ISSN": ["0025-1909"],
            "publisher": "Institute for Operations Research and the Management Sciences (INFORMS)",
            "volume": "72",
            "issue": "10",
            "page": "123-130",
            "published-print": {"date-parts": [[2026, 10]]},
            "type": "journal-article",
        }

    def compile(self, items, root):
        entries = []
        for provider, raw in items:
            provenance = {
                "provider": provider,
                "id": raw.get("DOI") or raw["id"],
                "raw_file": "fixture",
                "url": "https://example.org",
                "retrieved_at": "fixture",
            }
            entries.append((provider, self.journal, raw, provenance))
        with (
            patch.object(catalog, "ROOT", root),
            patch.object(catalog, "raw_records", return_value=iter(entries)),
        ):
            return catalog.compile_records()

    def test_same_name_foreign_journal_is_quarantined_before_merge(self):
        bad = {
            "id": "https://openalex.org/Wwrong",
            "doi": None,
            "title": "Повышение конкурентоспособности",
            "publication_date": "2016-01-01",
            "publication_year": 2016,
            "type": "article",
            "biblio": {"volume": "6", "issue": "4"},
            "primary_location": {
                "landing_page_url": "https://ideas.repec.org/a/scn/mngsci/y2016i4p53-61.html",
                "source": {"display_name": "Management Science", "issn": ["0025-1909"]},
            },
        }
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            records, issues, _, _ = self.compile([("crossref", self.good), ("openalex", bad)], root)
            quarantine = [
                json.loads(line) for line in (root / "quarantine.jsonl").read_text().splitlines()
            ]
        self.assertEqual(len(records), 1)
        self.assertEqual({i["volume"] for i in issues}, {"72"})
        self.assertEqual(quarantine[0]["source_id"], bad["id"])

    def test_crossref_search_bucket_cannot_override_actual_issn_or_publisher(self):
        for field, value in [("ISSN", ["2304-022X"]), ("publisher", "Financial University")]:
            with self.subTest(field=field):
                evidence, reason = journal_membership.crossref_evidence(
                    {**self.good, field: value}, self.journal
                )
                self.assertIsNone(evidence)
                self.assertTrue(reason)

    def test_foreign_working_paper_doi_cannot_become_a_journal_alias(self):
        bad = {
            "id": "https://openalex.org/Wversion",
            "doi": "https://doi.org/10.2139/ssrn.123",
            "title": self.good["title"][0],
            "type": "article",
            "publication_year": 2026,
            "biblio": {"volume": "72", "issue": "10", "first_page": "123", "last_page": "130"},
        }
        with tempfile.TemporaryDirectory() as temp:
            records, _, _, _ = self.compile(
                [("crossref", self.good), ("openalex", bad)], Path(temp)
            )
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["alternate_dois"], [])
        self.assertEqual(records[0]["openalex_ids"], [])

    def test_true_forthcoming_and_non_english_titles_use_identity_not_language(self):
        good = {
            k: v
            for k, v in self.good.items()
            if k not in ["volume", "issue", "page", "published-print"]
        }
        good.update(
            {
                "title": ["Über die Entscheidung"],
                "published-online": {"date-parts": [[2026, 10, 1]]},
            }
        )
        with tempfile.TemporaryDirectory() as temp:
            records, issues, _, _ = self.compile([("crossref", good)], Path(temp))
        self.assertEqual(records[0]["publication_status"], "online_first")
        self.assertEqual(
            records[0]["journal_membership"]["archive_status"], "not_individually_checked"
        )
        self.assertEqual(issues, [])

    def test_exact_doi_in_checked_publisher_toc_is_independent_confirmation(self):
        raw = {
            "id": "https://openalex.org/Warchive",
            "doi": "https://doi.org/" + self.good["DOI"],
            "title": self.good["title"][0],
            "type": "article",
        }
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "raw/membership").mkdir(parents=True)
            (root / "raw/membership/archive-evidence.json").write_text(
                json.dumps(
                    {
                        "excluded": [],
                        "confirmed": [
                            {
                                "journal_id": "mnsc",
                                "doi": self.good["DOI"],
                                "url": "https://pubsonline.informs.org/toc/mnsc/72/10",
                                "checked_at": "2026-10-12",
                            }
                        ],
                    }
                )
            )
            records, _, _, _ = self.compile([("openalex", raw)], root)
        self.assertEqual(records[0]["journal_membership"]["archive_status"], "confirmed")

    def test_unverified_january_first_is_displayed_as_year(self):
        self.assertEqual(
            journal_membership.display_date("2016-01-01", "provider_day_unverified"),
            "2016 (day and month unverified)",
        )
        self.assertEqual(
            journal_membership.display_date("2016-01-01", "provider_date_unverified"),
            "2016 (day and month unverified)",
        )
        self.assertEqual(journal_membership.display_date("2016-01-01", "day"), "2016-01-01")

    def test_same_doi_with_conflicting_title_cannot_enrich_authors(self):
        bad = {
            "id": "https://openalex.org/Wconflict",
            "doi": "https://doi.org/" + self.good["DOI"],
            "title": "Entirely unrelated title",
            "type": "article",
        }
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            records, _, _, _ = self.compile([("crossref", self.good), ("openalex", bad)], root)
            quarantine = json.loads((root / "quarantine.jsonl").read_text())
        self.assertEqual(records[0]["openalex_ids"], [])
        self.assertIn("conflicts", quarantine["reason"])


if __name__ == "__main__":
    unittest.main()
