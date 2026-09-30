import io
import json
import zipfile
from pathlib import Path

import pytest

from cairn.errors import Conflict, Denied
from cairn.ingest.service import capture, extract
from cairn.retrieval.search import search
from cairn.storage.backup import backup, restore
from cairn.storage.workspace import Workspace


def test_restore_text_blobs_and_evidence(ws: Workspace, tmp_path: Path) -> None:
    file = tmp_path / "source.txt"
    file.write_text("Synthetic evidence survives restore.")
    source = capture(ws, file, domain="research")
    extract(ws, source.id, inline_synthetic=True)
    ws.fs.write("vault/notes/thought.md", b"Human-authored hypothesis.\n")
    before = search(ws, "evidence", scope_name="research")
    archive = tmp_path / "backups" / "workspace.zip"
    result = backup(ws, archive)
    assert result["files"] > 4
    restored = restore(
        archive, tmp_path / "restored", code_roots=[tmp_path / "public-code"], synthetic=True
    )
    assert restored.config.id == ws.config.id
    assert restored.fs.read("vault/notes/thought.md") == b"Human-authored hypothesis.\n"
    assert search(restored, "evidence", scope_name="research") == before
    assert not any(path.startswith("cache/") for path in zipfile.ZipFile(archive).namelist())
    with pytest.raises(Conflict):
        restore(archive, restored.root, code_roots=[tmp_path / "public-code"], synthetic=True)


def test_archive_traversal_and_hash_tamper_rejected(ws: Workspace, tmp_path: Path) -> None:
    evil = tmp_path / "evil.zip"
    with zipfile.ZipFile(evil, "w") as archive:
        archive.writestr("../outside", "do not write")
    with pytest.raises(Denied):
        restore(evil, tmp_path / "out", code_roots=[tmp_path / "public-code"], synthetic=True)
    assert not (tmp_path / "outside").exists()
    good = tmp_path / "backup.zip"
    backup(ws, good)
    buffer = io.BytesIO()
    with zipfile.ZipFile(good) as original, zipfile.ZipFile(buffer, "w") as changed:
        for name in original.namelist():
            value = original.read(name)
            if name == "workspace.json":
                document = json.loads(value)
                document["id"] = "workspace_forged"
                value = json.dumps(document).encode()
            changed.writestr(name, value)
    evil.write_bytes(buffer.getvalue())
    with pytest.raises(Conflict):
        restore(evil, tmp_path / "out", code_roots=[tmp_path / "public-code"], synthetic=True)
    assert not (tmp_path / "out").exists()
