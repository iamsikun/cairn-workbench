"""ZIP64 backup/restore with bounded file buffers and independently verified digests."""

from __future__ import annotations

import hashlib
import os
import stat
import tempfile
import zipfile
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager, nullcontext
from pathlib import Path
from typing import BinaryIO
from uuid import uuid4

from cairn.errors import CairnError, Conflict, Denied
from cairn.records.models import canonical, digest
from cairn.records.runtime import ReviewAcknowledgement
from cairn.storage.activation import prepare_activation
from cairn.storage.backup import DURABLE_DIRS, BackupManifest, _paths, validate_payloads
from cairn.storage.files import MAX_FILE_BYTES, RootFS, disjoint, sync
from cairn.storage.workspace import Workspace, check_roots

MAX_TOTAL = 1024**4
MAX_MEMBERS = 1_000_000
MAX_MANIFEST = 256 * 1024 * 1024


class FileMap(Mapping[str, bytes]):
    def __init__(self, names: list[str], read: Callable[[str], bytes]):
        self.names = dict.fromkeys(names)
        self.read = read

    def __getitem__(self, key: str) -> bytes:
        if key not in self.names:
            raise KeyError(key)
        return self.read(key)

    def __iter__(self) -> Iterator[str]:
        return iter(self.names)

    def __len__(self) -> int:
        return len(self.names)


def stream_hash(stream: object) -> str:
    # BinaryIO is expressed structurally here to support both disk and ZIP readers.
    from typing import BinaryIO, cast

    source = cast(BinaryIO, stream)
    hasher = hashlib.sha256()
    for block in iter(lambda: source.read(1024 * 1024), b""):
        hasher.update(block)
    return hasher.hexdigest()


def durable_contents(ws: Workspace) -> FileMap:
    names = [
        "workspace.json",
        *(path for directory in DURABLE_DIRS for path in ws.fs.files(directory)),
    ]
    if len(names) > MAX_MEMBERS:
        raise Denied("backup member budget exceeded")
    return FileMap(names, ws.fs.read)


def backup(
    ws: Workspace, destination: Path, *, include_pending: bool = False
) -> dict[str, str | int]:
    return _backup(ws, destination, include_pending=include_pending)


def backup_unlocked(ws: Workspace, destination: Path) -> dict[str, str | int]:
    return _backup(ws, destination, already_locked=True)


def _backup(
    ws: Workspace, destination: Path, *, include_pending: bool = False, already_locked: bool = False
) -> dict[str, str | int]:
    destination = destination.absolute()
    if (
        any(p.is_symlink() for p in (destination, *destination.parents))
        or not disjoint(destination, ws.root)
        or any(not disjoint(destination, Path(root)) for root in ws.config.code_roots)
    ):
        raise Denied("backup destination must be outside workspace/public code with no symlinks")
    with nullcontext() if already_locked else ws.lock(recovery=include_pending):
        ws.require_no_pending_migration()
        names = [
            "workspace.json",
            *(path for directory in DURABLE_DIRS for path in ws.fs.files(directory)),
        ]
        if len(names) > MAX_MEMBERS:
            raise Denied("backup member budget exceeded")
        _paths(names)
        payloads = FileMap(names, ws.fs.read)
        validate_payloads(payloads)
        hashes = {}
        size = 0
        for name in names:
            raw = payloads[name]
            size += len(raw)
            if size > MAX_TOTAL:
                raise Denied("backup exceeds one-terabyte safety budget")
            hashes[name] = digest(raw)
        manifest = canonical(BackupManifest(workspace_id=ws.config.id, files=hashes))
        if len(manifest) > MAX_MANIFEST:
            raise Denied("backup manifest budget exceeded")
        destination.parent.mkdir(parents=True, exist_ok=True)
        fs = RootFS(destination.parent)
        with fs.parent(destination.name) as (fd, name):
            temporary = ".cairn-backup-" + uuid4().hex
            file_fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600, dir_fd=fd)
            try:
                with os.fdopen(file_fd, "w+b") as stream:
                    with zipfile.ZipFile(
                        stream, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True
                    ) as archive:
                        for item in sorted(names):
                            data = payloads[item]
                            if digest(data) != hashes[item]:
                                raise Conflict("source changed during backup")
                            archive.writestr(item, data)
                        archive.writestr("manifest.json", manifest)
                    stream.flush()
                    sync(stream.fileno())
                    stream.seek(0)
                    checksum = stream_hash(stream)
                # Hard-link publication is atomic and refuses an existing destination.
                try:
                    os.link(temporary, name, src_dir_fd=fd, dst_dir_fd=fd, follow_symlinks=False)
                except FileExistsError as exc:
                    raise Conflict("backup destination already exists") from exc
                os.unlink(temporary, dir_fd=fd)
                sync(fd)
            finally:
                try:
                    os.unlink(temporary, dir_fd=fd)
                except FileNotFoundError:
                    pass
    return {
        "workspace_id": ws.config.id,
        "files": len(names),
        "sha256": checksum,
        "payload_bytes": size,
        "format": "zip64",
    }


@contextmanager
def _private_copy(archive_path: Path, directory: Path) -> Iterator[tuple[BinaryIO, str]]:
    """Hash the archive while copying it once into an owner-only file; yield the copy."""
    fd = os.open(archive_path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as source:
        RootFS._regular(os.fstat(source.fileno()))
        if os.fstat(source.fileno()).st_size > MAX_TOTAL:
            raise Denied("archive exceeds one-terabyte safety budget")
        directory.chmod(0o700)
        copy = directory / "archive.zip"
        hasher = hashlib.sha256()
        size = 0
        out = os.open(copy, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(out, "wb") as target:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                size += len(block)
                if size > MAX_TOTAL:
                    raise Denied("archive exceeds one-terabyte safety budget")
                hasher.update(block)
                target.write(block)
    with copy.open("rb") as stream:
        yield stream, hasher.hexdigest()


def restore(
    archive_path: Path,
    destination: Path,
    *,
    code_roots: list[Path],
    expected_sha256: str | None = None,
    synthetic: bool = False,
    release: Path | None = None,
    release_sha256: str | None = None,
    statement: str | None = None,
    acknowledgements: set[ReviewAcknowledgement] | None = None,
) -> Workspace:
    destination = check_roots(destination, code_roots)
    if destination.exists() and any(destination.iterdir()):
        raise Conflict("restore requires an empty destination")
    if synthetic and any((release, release_sha256, statement, acknowledgements)):
        raise Denied("synthetic restore cannot record private release approval")
    if not synthetic and expected_sha256 is None:
        raise Denied("private restore requires an independently recorded archive digest")
    activation = (
        None
        if synthetic
        else prepare_activation(
            release,
            expected_sha256=release_sha256,
            statement=statement,
            acknowledgements=acknowledgements,
        )
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    with (
        tempfile.TemporaryDirectory(prefix=".cairn-archive-", dir=destination.parent) as private,
        _private_copy(archive_path, Path(private)) as (stream, checksum),
    ):
        # Restore reads only this owner-private copy, so the archive cannot be swapped
        # between the digest check and extraction.
        if expected_sha256 is not None and checksum != expected_sha256:
            raise Conflict("archive differs from independently recorded digest")
        try:
            with zipfile.ZipFile(stream) as archive:
                members = archive.infolist()
                if len(members) > MAX_MEMBERS or sum(m.file_size for m in members) > MAX_TOTAL:
                    raise Denied("archive expands beyond safety budget")
                _paths([m.filename for m in members])
                for member in members:
                    cap = MAX_MANIFEST if member.filename == "manifest.json" else MAX_FILE_BYTES
                    if (
                        member.is_dir()
                        or member.file_size > cap
                        or member.flag_bits & 1
                        or stat.S_IFMT(member.external_attr >> 16) not in (0, stat.S_IFREG)
                    ):
                        raise Denied("unsupported or oversized archive member")
                manifest = BackupManifest.model_validate_json(archive.read("manifest.json"))
                names = [m.filename for m in members if m.filename != "manifest.json"]
                if set(names) != set(manifest.files):
                    raise Conflict("backup manifest namespace mismatch")
                for name in names:
                    with archive.open(name) as member_stream:
                        if stream_hash(member_stream) != manifest.files[name]:
                            raise Conflict("backup member checksum mismatch")
                payloads = FileMap(names, archive.read)
                config = validate_payloads(payloads)
                if config.id != manifest.workspace_id or config.synthetic != synthetic:
                    raise Denied("backup workspace identity or mode mismatch")
                additions = {}
                if activation:
                    if config.runtime_release_hash != digest(activation.raw_manifest):
                        raise Denied(
                            "restore requires the original reviewed release; upgrade separately"
                        )
                    approval = activation.approval(config.id, "restore", archive_hash=checksum)
                    config.runtime_approval_id = approval.id
                    additions[f"receipts/runtime/{approval.id}.json"] = canonical(approval)
                config.code_roots = [str(root.resolve()) for root in code_roots]
                additions["workspace.json"] = canonical(config)
                with tempfile.TemporaryDirectory(
                    prefix=".cairn-restore-", dir=destination.parent
                ) as temporary:
                    staging = Path(temporary) / "workspace"
                    staging.mkdir(mode=0o700)
                    fs = RootFS(staging)
                    fs.write(
                        "restore.pending", canonical({"archive_sha256": checksum}), exclusive=True
                    )
                    for name in names:
                        data = additions.pop(name, None)
                        if data is None:
                            data = payloads[name]
                            if digest(data) != manifest.files[name]:
                                raise Conflict("archive changed during restore")
                        fs.write(name, data, exclusive=True)
                        if digest(fs.read(name)) != digest(data):
                            raise Conflict("restored file checksum mismatch")
                    for name, data in additions.items():
                        fs.write(name, data, exclusive=True)
                    fs.remove("restore.pending")
                    Workspace(staging)
                    if destination.is_symlink() or (
                        destination.exists() and any(destination.iterdir())
                    ):
                        raise Conflict("restore destination changed during staging")
                    os.replace(staging, destination)
                    parent_fd = os.open(
                        destination.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
                    )
                    try:
                        sync(parent_fd)
                    finally:
                        os.close(parent_fd)
        except (zipfile.BadZipFile, KeyError, RuntimeError, NotImplementedError) as exc:
            raise CairnError("invalid backup archive") from exc
    return Workspace(destination)
