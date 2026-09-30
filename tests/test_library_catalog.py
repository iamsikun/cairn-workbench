import io
from pathlib import Path

import pypdf
import pytest

from cairn.errors import Denied
from cairn.library.catalog import configure, correct, list_entities, mark, scan
from cairn.library.index import papers, render_catalog
from cairn.library.models import LibraryConfig, Paper, metadata
from cairn.storage.workspace import Workspace


def pdf(title: str = "Synthetic paper") -> bytes:
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.add_metadata({"/Title": title, "/Author": "A. Example"})
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def library(ws: Workspace, tmp_path: Path) -> Path:
    root = tmp_path / "synthetic-library"
    (root / "Example Journal").mkdir(parents=True)
    configure(ws, LibraryConfig(root=str(root)))
    return root


def test_inventory_idempotence_move_revision_and_owner_fields(
    ws: Workspace, tmp_path: Path
) -> None:
    root = library(ws, tmp_path)
    file = root / "Example Journal" / "paper.pdf"
    file.write_bytes(pdf())
    first = scan(ws)
    assert first.baseline and len(first.added) == 1
    paper_id = first.added[0]
    assert scan(ws).unchanged == 1
    mark(ws, paper_id, "read", scope="research")
    correct(ws, paper_id, {"title": "Owner title"}, scope="research")
    moved = file.with_name("renamed.pdf")
    file.rename(moved)
    assert scan(ws).moved == [paper_id]
    moved.write_bytes(pdf("Revised title"))
    assert scan(ws).changed == [paper_id]
    rows = papers(ws, scope="research", reading="read")
    assert len(rows) == 1 and rows[0]["title"] == "Owner title"
    assert rows[0]["metadata"]["files"][-1]["availability"] == "available"


def test_offline_and_partial_scans_do_not_delete(ws: Workspace, tmp_path: Path) -> None:
    root = library(ws, tmp_path)
    (root / "Example Journal" / "paper.pdf").write_bytes(pdf())
    scan(ws)
    (root / "bad-link").symlink_to(tmp_path)
    result = scan(ws)
    assert not result.complete and result.issues["bad-link"] == "symlink_denied"
    root.rename(root.with_name("offline"))
    assert not scan(ws).complete
    assert papers(ws, scope="research", available=True)


def test_duplicates_scopes_and_rendering(ws: Workspace, tmp_path: Path) -> None:
    root = library(ws, tmp_path)
    data = pdf("<script>alert(1)</script>")
    (root / "Example Journal" / "a.pdf").write_bytes(data)
    (root / "Example Journal" / "b.pdf").write_bytes(data)
    scan(ws)
    rows = papers(ws, scope="research")
    assert len(rows) == 1
    assert papers(ws, scope="finance") == []
    assert "<script>" not in render_catalog(rows)
    record = list_entities(ws, "research", "paper")[0]
    assert isinstance(metadata(record), Paper)
    with pytest.raises(Denied):
        mark(ws, record.id, "read", scope="finance")


def test_owner_catalog_recovery(
    ws: Workspace, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from cairn.errors import RecoveryRequired
    from cairn.library import store
    from cairn.transactions.apply import recover

    root = library(ws, tmp_path)
    (root / "Example Journal" / "paper.pdf").write_bytes(pdf())

    def stop(workspace: Workspace, label: str) -> None:
        if label == "library_write:0":
            raise RuntimeError("synthetic crash")

    monkeypatch.setattr(store, "_crash", stop)
    with pytest.raises(RuntimeError):
        scan(ws)
    with pytest.raises(RecoveryRequired):
        papers(ws, scope="research")
    monkeypatch.setattr(store, "_crash", lambda *args: None)
    recover(ws)
    assert len(papers(ws, scope="research")) == 1


def test_model_cannot_replace_catalog(ws: Workspace, tmp_path: Path) -> None:
    from cairn.adapters.protocol import Candidate, Result
    from cairn.ingest.service import capture, extract
    from cairn.proposals.service import prepare_job, stage_result
    from cairn.records.models import canonical, digest

    root = library(ws, tmp_path)
    (root / "Example Journal" / "paper.pdf").write_bytes(pdf())
    scan(ws)
    paper = list_entities(ws, "research", "paper")[0]
    source_file = tmp_path / "evidence.txt"
    source_file.write_text("Synthetic evidence")
    source = capture(ws, source_file, domain="research")
    extract(ws, source.id, inline_synthetic=True)
    job = prepare_job(ws, source.id, scope_name="research", related_ids=[]).job
    paper.sections.clear()
    with pytest.raises(Denied, match="owner-controlled"):
        stage_result(
            ws,
            Result(
                job_id=job.id,
                input_hash=digest(canonical(job)),
                provider=job.provider,
                candidates=[
                    Candidate(
                        record=paper, body="changed", rationale="Attempt to erase reading status"
                    )
                ],
            ),
        )


def test_resolving_journal_preserves_identity_and_empty_scan_is_uncertain(ws, tmp_path) -> None:
    from cairn.library.catalog import register_journal
    from cairn.library.models import Journal

    root = library(ws, tmp_path)
    file = root / "Example Journal/a.pdf"
    file.write_bytes(pdf())
    scan(ws)
    original = list_entities(ws, "research", "journal")[0]
    resolved = register_journal(
        ws,
        "Synthetic Journal of Examples",
        Journal(
            folder="Example Journal", resolved=True, publication_series=["Series A", "Series B"]
        ),
    )
    assert resolved.id == original.id
    assert len(list_entities(ws, "research", "journal")) == 1
    paper = list_entities(ws, "research", "paper")[0]
    assert metadata(paper).metadata_evidence["title"].source_id
    file.unlink()
    result = scan(ws)
    assert not result.complete and not result.missing


def test_catalog_survives_oversized_disposable_cache(ws, tmp_path, monkeypatch) -> None:
    root = library(ws, tmp_path)
    (root / "Example Journal/a.pdf").write_bytes(pdf())
    scan(ws)
    monkeypatch.setattr("cairn.library.index.MAX_FILE_BYTES", 1)
    assert len(papers(ws, scope="research", query="   ")) == 1
    assert not ws.fs.files("cache/library")
