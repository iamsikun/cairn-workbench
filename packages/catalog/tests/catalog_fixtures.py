"""Synthetic catalog data shared by the tests."""

import gzip
import io
import json
from contextlib import redirect_stdout
from unittest.mock import patch

from cairn_catalog import entities


def synthetic_catalog(root):
    """A one-paper catalog whose two authors carry ORCIDs in a cached OpenAlex page."""
    from cairn_catalog import catalog

    names = ["Jane Fixture", "John Example"]
    work = "https://openalex.org/W9000000101"
    record = {
        "id": "fixture-paper",
        "journal_id": "aer",
        "journal": "American Economic Review",
        "issns": ["0002-8282"],
        "doi": "10.0000/fixture",
        "alternate_dois": [],
        "title": "A synthetic paper",
        "authors": names,
        "author_details": [{"name": name} for name in names],
        "date": "2025-01-01",
        "date_precision": "day",
        "published_print": None,
        "published_online": None,
        "year": 2025,
        "url": "https://example.org/paper",
        "openalex_ids": [work],
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
        "source": "doi:10.0000/fixture",
    }
    authorships = [
        {
            "author": {
                "display_name": name,
                "id": f"https://openalex.org/A{i + 1}",
                "orcid": f"https://orcid.org/0000-0002-0000-000{i + 1}",
            },
            "institutions": [],
        }
        for i, name in enumerate(names)
    ]
    raw = root / "raw/openalex/aer"
    raw.mkdir(parents=True)
    page = {
        "retrieved_at": "2026-10-13T00:00:00+00:00",
        "response": {
            "results": [
                {"id": work, "doi": "https://doi.org/10.0000/fixture", "authorships": authorships}
            ]
        },
    }
    with gzip.open(raw / "page-00001.json.gz", "wt", encoding="utf-8") as handle:
        json.dump(page, handle)
    (raw / "state.json").write_text(json.dumps({"complete": True, "pages": 1}))
    with patch.object(catalog, "ROOT", root), patch.object(entities, "ROOT", root):
        with redirect_stdout(io.StringIO()):
            catalog.sql_database([record], [])
    return record
