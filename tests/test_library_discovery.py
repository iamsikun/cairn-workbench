import json
from pathlib import Path

from cairn.library.catalog import configure, list_entities, register_journal
from cairn.library.discovery import discover
from cairn.library.models import DiscoverySource, Journal, LibraryConfig, metadata
from cairn.storage.workspace import Workspace


def test_backfill_checkpoint_and_updates(ws: Workspace, tmp_path: Path) -> None:
    root = tmp_path / "synthetic-library"
    root.mkdir()
    configure(ws, LibraryConfig(root=str(root)))
    journal = register_journal(
        ws,
        "Example Journal",
        Journal(
            folder="Example",
            resolved=True,
            discovery=[DiscoverySource(kind="crossref", issn="1234-5678")],
        ),
    )
    calls = []

    def fetch(url: str, hosts: set[str]) -> bytes:
        calls.append(url)
        assert hosts == {"api.crossref.org"}
        items = (
            []
            if "cursor=next" in url
            else [
                {
                    "DOI": "10.5555/EXAMPLE",
                    "title": ["Example publication"],
                    "published": {"date-parts": [[2024]]},
                    "author": [{"given": "A", "family": "Example"}],
                }
            ]
        )
        return json.dumps({"message": {"items": items, "next-cursor": "next"}}).encode()

    first = discover(ws, fetch=fetch, page_budget=1)[0]
    assert not first.complete and len(first.added) == 1
    second = discover(ws, fetch=fetch, page_budget=1)[0]
    assert second.complete and "cursor=next" in calls[-1]
    assert len(list_entities(ws, "research", "paper")) == 1
    assert discover(ws, fetch=fetch)[0].added == []
    assert "from-index-date" in calls[-1]
    record = list_entities(ws, "research", "paper")[0]
    assert metadata(record).published == "2024"
    assert journal.id == second.journal_id


def test_unresolved_and_feed_coverage(ws: Workspace, tmp_path: Path) -> None:
    root = tmp_path / "synthetic-library"
    root.mkdir()
    configure(ws, LibraryConfig(root=str(root)))
    register_journal(ws, "Unknown", Journal(folder="Unknown"))
    register_journal(
        ws,
        "Feed journal",
        Journal(
            folder="Feed",
            resolved=True,
            discovery=[DiscoverySource(kind="atom", url="https://example.org/feed")],
        ),
    )
    xml = (
        b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>article:1</id>'
        b"<title>Sample</title><summary>Abstract.</summary></entry></feed>"
    )
    result = discover(ws, fetch=lambda url, hosts: xml)
    assert any(r.issue == "journal_identity_or_source_unresolved" for r in result)
    assert any(r.complete for r in result)
    assert "historical coverage incomplete" in next(
        metadata(r).coverage
        for r in list_entities(ws, "research", "journal")
        if r.title == "Feed journal"
    )


def test_failed_page_does_not_advance_watermark(ws: Workspace, tmp_path: Path) -> None:
    from cairn.errors import Blocked

    root = tmp_path / "synthetic-library"
    root.mkdir()
    configure(ws, LibraryConfig(root=str(root)))
    register_journal(
        ws,
        "Example",
        Journal(
            folder="Example",
            resolved=True,
            discovery=[DiscoverySource(kind="crossref", issn="1234-5678")],
        ),
    )

    def fail(url: str, hosts: set[str]) -> bytes:
        raise Blocked("synthetic outage")

    result = discover(ws, fetch=fail)[0]
    assert not result.complete and result.issue == "source_failed_retryable"
    assert ws.fs.files("receipts/library/discovery") == []
