import os
import stat
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from cairn.errors import CairnError, Conflict, Denied, RecoveryRequired
from cairn.ingest.service import capture
from cairn.proposals.service import approve, ingest
from cairn.records.models import Record, canonical, digest, now
from cairn.retrieval.search import search
from cairn.storage.backup import BackupManifest, backup, restore
from cairn.storage.files import RootFS
from cairn.storage.history import snapshot
from cairn.storage.markdown import encode
from cairn.storage.workspace import Workspace
from cairn.transactions.apply import apply, recover


def archive_with(ws: Workspace, file: Path, changes: dict[str, bytes | None]) -> None:
    backup(ws, file)
    with zipfile.ZipFile(file) as archive:
        contents = {
            name: archive.read(name) for name in archive.namelist() if name != "manifest.json"
        }
    for name, value in changes.items():
        if value is None:
            contents.pop(name, None)
        else:
            contents[name] = value
    manifest = BackupManifest(
        workspace_id=ws.config.id, files={name: digest(value) for name, value in contents.items()}
    )
    with zipfile.ZipFile(file, "w") as archive:
        archive.writestr("manifest.json", canonical(manifest))
        for name, value in contents.items():
            archive.writestr(name, value)


@pytest.mark.parametrize(
    "names",
    [
        ["vault/notes/A.md", "vault/notes/a.md"],
        ["vault/notes/Folder/a.md", "vault/notes/folder/b.md"],
        ["vault/notes/e\u0301.md"],
        ["vault/notes/item", "vault/notes/item/child.md"],
        ["vault/.git/config"],
        ["history.git/objects/info/alternates"],
    ],
)
def test_restore_namespace_preflight_writes_nothing(
    ws: Workspace, tmp_path: Path, names: list[str]
) -> None:
    file = tmp_path / "bad.zip"
    archive_with(ws, file, {name: b"Untrusted bytes" for name in names})
    destination = tmp_path / "restored"
    with pytest.raises(Denied):
        restore(file, destination, code_roots=[tmp_path / "public-code"])
    assert not destination.exists()
    assert not list(tmp_path.glob(".cairn-restore-*"))


def test_restore_rejects_special_files_missing_manifest_and_bad_records(
    ws: Workspace,
    tmp_path: Path,
) -> None:
    file = tmp_path / "bad.zip"
    member = zipfile.ZipInfo("vault/notes/pipe")
    member.create_system = 3
    member.external_attr = (stat.S_IFIFO | 0o600) << 16
    with zipfile.ZipFile(file, "w") as archive:
        archive.writestr(member, b"")
    with pytest.raises(Denied):
        restore(file, tmp_path / "restored", code_roots=[tmp_path / "public-code"])
    with zipfile.ZipFile(file, "w") as archive:
        archive.writestr("workspace.json", ws.fs.read("workspace.json"))
    with pytest.raises(CairnError, match="omits manifest"):
        restore(file, tmp_path / "restored", code_roots=[tmp_path / "public-code"])
    file.unlink()
    archive_with(ws, file, {"vault/wiki/research/concept_bad.md": b"Not a canonical record"})
    with pytest.raises(CairnError):
        restore(file, tmp_path / "restored", code_roots=[tmp_path / "public-code"])
    assert not (tmp_path / "restored").exists()


def test_restore_copy_failure_does_not_publish_partial_workspace(
    ws: Workspace,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = tmp_path / "good.zip"
    report = backup(ws, archive)
    with pytest.raises(Conflict, match="independently recorded"):
        restore(
            archive,
            tmp_path / "restored",
            code_roots=[tmp_path / "public-code"],
            expected_sha256="0" * 64,
        )
    original = RootFS.write

    def fail(
        self: RootFS,
        path: str,
        data: bytes,
        *,
        exclusive: bool = False,
        limit: int = 32 * 1024 * 1024,
    ) -> None:
        if ".cairn-restore-" in str(self.root) and path.startswith("vault/"):
            raise OSError("Synthetic disk failure")
        original(self, path, data, exclusive=exclusive, limit=limit)

    monkeypatch.setattr(RootFS, "write", fail)
    with pytest.raises(OSError):
        restore(
            archive,
            tmp_path / "restored",
            code_roots=[tmp_path / "public-code"],
            expected_sha256=str(report["sha256"]),
        )
    assert not (tmp_path / "restored").exists()
    assert not list(tmp_path.glob(".cairn-restore-*"))


def test_history_configuration_cannot_execute_filters(ws: Workspace, tmp_path: Path) -> None:
    snapshot(ws, "Synthetic initial history")
    marker = tmp_path / "must-not-exist"
    ws.fs.write("vault/.gitattributes", b"*.md filter=untrusted\n")
    config = (
        ws.fs.read("history.git/config")
        + (f'\n[filter "untrusted"]\n clean = touch {marker}\n').encode()
    )
    ws.fs.write("history.git/config", config)
    with pytest.raises(Denied, match="history configuration"):
        snapshot(ws, "Reject executable settings")
    assert not marker.exists()
    ws.fs.write(
        "history.git/config", b"[core]\nrepositoryformatversion=0\nfilemode=true\nbare=true\n"
    )
    archive = tmp_path / "malicious-history.zip"
    archive_with(ws, archive, {"history.git/config": config})
    with pytest.raises(Denied):
        restore(archive, tmp_path / "restored", code_roots=[tmp_path / "public-code"])
    assert not marker.exists() and not (tmp_path / "restored").exists()


def test_large_archive_crosses_old_single_file_limit(ws: Workspace, tmp_path: Path) -> None:
    file = tmp_path / "synthetic-binary.txt"
    source_ids = []
    for index in range(2):
        file.write_bytes(os.urandom(17 * 1024 * 1024))
        source_ids.append(
            capture(ws, file, domain="research", identity=f"synthetic-blob-{index}").id
        )
    file.unlink()
    archive = tmp_path / "large.zip"
    backup(ws, archive)
    assert archive.stat().st_size > 32 * 1024 * 1024
    restored = restore(archive, tmp_path / "restored", code_roots=[tmp_path / "public-code"])
    for source_id in source_ids:
        meta = restored.record(source_id)[1].source
        assert meta and digest(restored.fs.read(meta.blob)) == meta.content_hash


def test_pending_transaction_backup_restores_then_requires_recovery(
    ws: Workspace, tmp_path: Path
) -> None:
    file = tmp_path / "paper.txt"
    file.write_text("Synthetic result survives a restored interrupted apply.")
    source = capture(ws, file, domain="research")
    timestamp = now()
    project = Record(
        id="project_backup",
        type="project",
        title="Synthetic restore project",
        domain="research",
        created_at=timestamp,
        updated_at=timestamp,
    )
    ws.fs.write("vault/wiki/research/project_backup.md", encode(project, "Original owner framing."))
    proposal = ingest(
        ws, source.id, scope_name="research", related_ids=[project.id], inline_synthetic=True
    )
    assert proposal and len(proposal.changes) == 2
    approve(
        ws, proposal.id, acknowledgements=proposal.review_flags, statement="Synthetic owner review."
    )
    env = dict(os.environ, CAIRN_TEST_CRASH_AT="write:0")
    code = (
        "from cairn.storage.workspace import Workspace; "
        "from cairn.transactions.apply import apply; from pathlib import Path; import sys; "
        "apply(Workspace(Path(sys.argv[1])),sys.argv[2])"
    )
    result = subprocess.run([sys.executable, "-c", code, str(ws.root), proposal.id], env=env)
    assert result.returncode == 77
    archive = tmp_path / "pending.zip"
    with pytest.raises(RecoveryRequired):
        backup(ws, archive)
    backup(ws, archive, include_pending=True)
    restored = restore(archive, tmp_path / "restored", code_roots=[tmp_path / "public-code"])
    with pytest.raises(RecoveryRequired):
        search(restored, "result", scope_name="research")
    assert len(recover(restored)) == 1
    assert apply(restored, proposal.id).proposal_id == proposal.id
    assert search(restored, "result", scope_name="research")
    assert restored.record(project.id)[2] == "Original owner framing."


def test_restore_staging_marker_blocks_open(ws: Workspace) -> None:
    ws.fs.write("restore.pending", b"synthetic interrupted restore")
    with pytest.raises(RecoveryRequired, match="restore staging"):
        Workspace(ws.root)
