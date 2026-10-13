import gzip
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cairn_catalog import catalog, journal_membership, publication_status, update_catalog


class CatalogExpansionTests(unittest.TestCase):
    def test_publisher_archive_admits_non_doi_article_and_enriches_it(self):
        journal = dict(
            id="jmlr",
            title="Journal of Machine Learning Research",
            issns=["1532-4435"],
            publication_unit="volume",
            archive_prefixes=["https://jmlr.org/papers/"],
        )
        url = "https://jmlr.org/papers/v1/example.html"
        raw = dict(
            id=url,
            url=url,
            title="A rigorous learning algorithm",
            authors=["Jane Scholar"],
            volume="1",
            issue=None,
            pages="1-12",
            date="2000-10",
            year=2000,
            abstract="The original publisher abstract.",
        )
        provenance = dict(
            provider="journal_archive",
            id=url,
            url=url,
            archive_url="https://jmlr.org/papers/v1/",
            raw_file="retained-publisher-response",
            retrieved_at="2026-10-12",
        )
        oa = dict(
            id="https://openalex.org/Wexample",
            doi=None,
            title=raw["title"],
            publication_year=2000,
            biblio=dict(volume="1", first_page="1", last_page="12"),
            authorships=[
                dict(author=dict(display_name="Jane Scholar", id="https://openalex.org/Aexample"))
            ],
            type="article",
        )
        oa_provenance = dict(
            provider="openalex",
            id=oa["id"],
            url=oa["id"],
            raw_file="retained-provider-response",
            retrieved_at="2026-10-12",
        )
        with tempfile.TemporaryDirectory() as temp, patch.object(catalog, "ROOT", Path(temp)):
            with patch.object(
                catalog,
                "raw_records",
                return_value=iter(
                    [
                        ("journal_archive", journal, raw, provenance),
                        ("openalex", journal, oa, oa_provenance),
                    ]
                ),
            ):
                records, issues, _, _ = catalog.compile_records()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["id"], url)
        self.assertIsNone(records[0]["doi"])
        self.assertEqual(records[0]["abstract"], raw["abstract"])
        self.assertEqual(records[0]["openalex_ids"], [oa["id"]])
        self.assertEqual(records[0]["publication_status"], "issue_assigned")
        self.assertEqual(issues[0]["id"], "jmlr:v1")
        self.assertIsNone(issues[0]["issue"])
        self.assertEqual(records[0]["journal_membership"]["archive_status"], "confirmed")

    def test_archive_host_or_path_mismatch_is_quarantined(self):
        journal = dict(
            id="jmlr", title="JMLR", issns=[], archive_prefixes=["https://jmlr.org/papers/"]
        )
        gate = journal_membership.Gate(
            Path("/nonexistent-fixture"), catalog.same_paper, catalog.titlekey
        )
        raw = dict(
            title="An unrelated proceedings paper", url="https://jmlr.org/proceedings/example.html"
        )
        record = dict(journal_id="jmlr", title=raw["title"], doi=None)
        provenance = dict(
            id=raw["url"], archive_url="https://jmlr.org/papers/v1/", retrieved_at="fixture"
        )
        self.assertFalse(gate.check(raw, "journal_archive", journal, record, provenance))
        self.assertEqual(len(gate.quarantine), 1)

    def test_registry_publisher_rules_remain_strict(self):
        journal = dict(
            id="newjournal", issns=["0001-5962"], publishers=["International Press of Boston"]
        )
        raw = dict(
            DOI="10.1/example", ISSN=["0001-5962"], publisher="International Press of Boston"
        )
        self.assertIsNotNone(journal_membership.crossref_evidence(raw, journal)[0])
        self.assertIsNone(
            journal_membership.crossref_evidence({**raw, "publisher": "Test accounts"}, journal)[0]
        )

    def test_restarted_volume_series_produces_distinct_issues_and_papers(self):
        journal = dict(
            id="annmath",
            title="Annals of Mathematics",
            issns=["0003-486X"],
            publishers=["JSTOR"],
            series_restart_year=1899,
        )
        entries = []
        for year in [1884, 1899]:
            raw = dict(
                DOI=f"10.2307/{year}",
                ISSN=["0003-486X"],
                publisher="JSTOR",
                title=["Notes"],
                volume="1",
                issue="1",
                page="1-2",
                published={"date-parts": [[year]]},
                type="journal-article",
            )
            entries.append(
                (
                    "crossref",
                    journal,
                    raw,
                    dict(
                        provider="crossref",
                        id=raw["DOI"],
                        url="https://doi.org/" + raw["DOI"],
                        raw_file="fixture",
                        retrieved_at="fixture",
                    ),
                )
            )
        with tempfile.TemporaryDirectory() as temp, patch.object(catalog, "ROOT", Path(temp)):
            with patch.object(catalog, "raw_records", return_value=iter(entries)):
                records, issues, _, _ = catalog.compile_records()
        self.assertEqual(len(records), 2)
        self.assertEqual(
            {i["id"] for i in issues}, {"annmath:sfirst:v1:i1", "annmath:ssecond:v1:i1"}
        )

    def test_volume_assignment_does_not_mark_published_articles_forthcoming(self):
        self.assertEqual(
            publication_status.classify(
                dict(publication_unit="volume", volume="27", published_online="2026-10")
            )[0],
            "issue_assigned",
        )
        self.assertEqual(
            publication_status.classify(
                dict(publication_unit="volume", published_online="2026-10")
            )[0],
            "online_first",
        )

    def test_partial_source_retains_records_without_claiming_complete_traversal(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            state = dict(
                pages=1,
                retrieved=1,
                complete=False,
                usable_checkpoint=True,
                incomplete_reason="Provider daily budget exhausted.",
            )
            (folder / "state.json").write_text(json.dumps(state))
            with gzip.open(folder / "page-00001.json.gz", "wt") as handle:
                json.dump(
                    dict(
                        retrieved_at="fixture",
                        response=dict(results=[dict(id="https://openalex.org/W1")]),
                    ),
                    handle,
                )
            records, _, result = update_catalog.read_cache(folder, "openalex")
            self.assertEqual(list(records), ["https://openalex.org/W1"])
            self.assertFalse(result["complete"])
            state.pop("incomplete_reason")
            (folder / "state.json").write_text(json.dumps(state))
            with self.assertRaisesRegex(RuntimeError, "Incomplete baseline"):
                update_catalog.read_cache(folder, "openalex")


if __name__ == "__main__":
    unittest.main()
