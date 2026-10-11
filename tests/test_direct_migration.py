import json
import os
import subprocess
import sys

import pytest

from cairn.errors import Conflict, Denied, RecoveryRequired
from cairn.records.models import canonical, digest
from cairn.saving.backup import backup, inventory, read_archive, restore
from cairn.saving.migration import migrate
from cairn.saving.models import NoteChange, SaveNote
from cairn.saving.retrieval import search
from cairn.saving.service import save
from cairn.saving.workspace import Book
from cairn.storage.markdown import encode
from cairn.storage.workspace import Workspace


def legacy(ws, record, version):
    ws.fs.write("vault/wiki/research/concept_demo.md", encode(record, "Legacy synthesis"))
    ws.fs.write("vault/notes/research/human.md", b"# My observation\nRetain this wording.")
    config = json.loads(ws.fs.read("workspace.json"))
    config["schema_version"] = version
    if version < 3:
        config.pop("code_repository", None)
    if version == 1:
        config.pop("record_schema_version", None)
    ws.fs.write("workspace.json", canonical(config))
    return inventory(ws.fs)


@pytest.mark.parametrize("version", [1, 2, 3])
def test_all_legacy_versions_preserve_inventory_backup_and_human_notes(
    ws, record, tmp_path, version
):
    before = legacy(ws, record, version)
    archive = tmp_path / "before.zip"
    result = migrate(ws.root, archive)
    book = Book(ws.root)
    assert result["status"] == "migrated"
    for path, raw in before.items():
        if path != "workspace.json":
            assert book.fs.read(path) == raw
    assert read_archive(archive)[0] == before
    assert book.record(record.id, "research")[1].legacy_hash == digest(
        before["vault/wiki/research/concept_demo.md"]
    )
    human = search(book, "research", "Retain")[0]
    assert book.record(human["id"], "research")[1].observations[0].text.endswith("wording.")
    assert search(book, "finance", "Legacy") == []
    with pytest.raises(Denied):
        Workspace(ws.root)
    snapshot = tmp_path / "after.zip"
    backup(book, snapshot)
    restored = tmp_path / "restored"
    restore(snapshot, restored)
    assert inventory(Book(restored).fs) == inventory(book.fs)
    save(
        book,
        "research",
        SaveNote(operation_key="newer", note=NoteChange(title="New", markdown="Newer save")),
    )
    with pytest.raises(Conflict):
        restore(archive, book.root)
    assert search(book, "research", "Newer")


def test_ambiguous_mapping_and_pending_legacy_transaction(ws, record, tmp_path):
    legacy(ws, record, 3)
    ws.fs.write("vault/notes/unclear.md", b"Human note")
    archive = tmp_path / "backup.zip"
    with pytest.raises(Denied, match="explicit collection"):
        migrate(ws.root, archive)
    ws.fs.write("journal/example/transaction.json", canonical({"status": "prepared"}))
    with pytest.raises(RecoveryRequired):
        migrate(ws.root, archive, {"vault/notes/unclear.md": "research"})
    ws.fs.remove("journal/example/transaction.json")
    migrate(ws.root, archive, {"vault/notes/unclear.md": "research"})
    assert search(Book(ws.root), "research", "Human")


@pytest.mark.parametrize("point", ["prepared", "write:0", "config"])
def test_process_interrupted_conversion_can_resume(ws, record, tmp_path, point):
    before = legacy(ws, record, 3)
    archive = tmp_path / "backup.zip"
    program = """
import sys
from pathlib import Path
from cairn.saving.migration import migrate
migrate(Path(sys.argv[1]), Path(sys.argv[2]))
"""
    result = subprocess.run(
        [sys.executable, "-c", program, str(ws.root), str(archive)],
        env={**os.environ, "CAIRN_MIGRATION_CRASH_AT": point},
        check=False,
    )
    assert result.returncode == 78
    assert migrate(ws.root, archive)["status"] == "migrated"
    assert read_archive(archive)[0] == before
    assert Book(ws.root).record(record.id, "research")


def test_archive_tampering_and_external_edit_during_migration_preserved(
    ws, record, tmp_path, monkeypatch
):
    from cairn.saving import migration

    legacy(ws, record, 3)
    archive = tmp_path / "backup.zip"

    def stop(*args):
        raise RuntimeError("interruption")

    monkeypatch.setattr(migration, "_crash", stop)
    with pytest.raises(RuntimeError):
        migrate(ws.root, archive)
    path = "vault/wiki/research/concept_demo.md"
    ws.fs.write(path, ws.fs.read(path) + b"\nExternal change")
    monkeypatch.setattr(migration, "_crash", lambda *args: None)
    with pytest.raises(Conflict):
        migrate(ws.root, archive)
    assert ws.fs.read(path).endswith(b"External change")
    assert archive.exists()


def test_sources_pending_proposals_and_history_remain_recoverable(ws, tmp_path):
    from cairn.ingest.service import capture, extract
    from cairn.proposals.service import ingest
    from cairn.records.references import all_refs
    from cairn.storage.backup import backup as old_backup

    document = tmp_path / "paper.txt"
    document.write_text("Synthetic architecture evidence.")
    source = capture(ws, document, domain="research")
    extract(ws, source.id, inline_synthetic=True)
    proposal = ingest(ws, source.id, scope_name="research", inline_synthetic=True)
    assert proposal
    pending = ws.fs.read(f"proposals/{proposal.id}.json")
    before = inventory(ws.fs)
    old_archive = tmp_path / "legacy-format.zip"
    old_backup(ws, old_archive)
    assert read_archive(old_archive)[0] == before
    migrate(ws.root, tmp_path / "migration.zip")
    book = Book(ws.root)
    assert book.fs.read(f"proposals/{proposal.id}.json") == pending
    source_note = book.record(source.id, "research")[1]
    assert source_note.source and source_note.source.original_blob
    assert book.fs.read(source_note.source.original_blob) == document.read_bytes()
    assert not any(r.type != "source" for _, r, _ in book.records("research").values())
    assert all_refs(source) == []


def test_library_inventory_and_reading_marks_preserved(ws, tmp_path):
    from test_library_catalog import library, pdf

    from cairn.library.catalog import mark, scan

    root = library(ws, tmp_path)
    (root / "Example Journal" / "paper.pdf").write_bytes(pdf("Synthetic library paper"))
    identity = scan(ws).added[0]
    mark(ws, identity, "read", scope="research")
    before = inventory(ws.fs)
    migrate(ws.root, tmp_path / "library-migration.zip")
    book = Book(ws.root)
    for path, original in before.items():
        if path != "workspace.json":
            assert book.fs.read(path) == original
    record = book.record(identity, "research")[1]
    assert record.legacy_path and book.fs.read(record.legacy_path) == before[record.legacy_path]
