import zipfile
from pathlib import Path

import pytest
from test_library_catalog import library, pdf

from cairn.errors import Conflict, Denied
from cairn.library import feed
from cairn.library.update import update
from cairn.records.models import digest
from cairn.storage import backup as legacy
from cairn.storage.streaming_backup import backup, restore
from cairn.storage.workspace import Workspace


def test_weekly_baseline_additions_deduplicate_and_recover(ws: Workspace, tmp_path: Path) -> None:
    root = library(ws, tmp_path)
    (root / "Example Journal/a.pdf").write_bytes(pdf("Old"))
    first = update(ws, read_budget=0)
    assert first["baseline"] and not feed.history(ws, "research")[0].entries
    (root / "Example Journal/b.pdf").write_bytes(pdf("Added"))
    second = update(ws, read_budget=0)
    assert second["digest"]
    values = feed.history(ws, "research")
    assert len(values[0].entries) == 1 and values[0].entries[0].event.kind == "box_addition"
    assert update(ws, read_budget=0)["digest"] is None
    with pytest.raises(Denied):
        update(ws, scope="finance")


def test_streaming_backup_exceeds_legacy_limit(ws: Workspace, tmp_path: Path, monkeypatch) -> None:
    # Lower the old limit to exercise the boundary without a 256MiB fixture.
    monkeypatch.setattr(legacy, "MAX_BACKUP_BYTES", 1024)
    for i in range(8):
        data = bytes([i]) * (128 * 1024)
        ws.fs.write(f"blobs/{digest(data)}", data)
    archive = tmp_path / "library.zip"
    report = backup(ws, archive)
    assert report["payload_bytes"] > legacy.MAX_BACKUP_BYTES
    restored = restore(
        archive,
        tmp_path / "restored",
        code_roots=[tmp_path / "public-code"],
        synthetic=True,
        expected_sha256=report["sha256"],
    )
    assert restored.config.id == ws.config.id
    assert restored.fs.files("blobs") == ws.fs.files("blobs")
    with pytest.raises(Conflict):
        restore(
            archive,
            tmp_path / "wrong",
            code_roots=[tmp_path / "public-code"],
            synthetic=True,
            expected_sha256="0" * 64,
        )


def test_streaming_restore_rejects_bad_members(ws: Workspace, tmp_path: Path) -> None:
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("../escape", "bad")
    with pytest.raises(Denied):
        restore(
            archive, tmp_path / "restore", code_roots=[tmp_path / "public-code"], synthetic=True
        )
    assert not (tmp_path / "restore").exists()
