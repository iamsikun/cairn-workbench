from __future__ import annotations

import io
import json
import os
import stat
import zipfile
from pathlib import Path

from cairn.errors import CairnError, Conflict, Denied
from cairn.records.models import canonical, digest
from cairn.storage.files import MAX_FILE_BYTES, RootFS, components, disjoint
from cairn.storage.workspace import Workspace, WorkspaceConfig, check_roots

DURABLE_DIRS = (
    "vault",
    "blobs",
    "evidence",
    "policy",
    "proposals",
    "approvals",
    "receipts",
    "journal",
    "history.git",
)
MAX_BACKUP_BYTES = 256 * 1024 * 1024


def backup(ws: Workspace, destination: Path) -> dict[str, str | int]:
    destination = destination.absolute()
    if not disjoint(destination, ws.root) or any(
        not disjoint(destination, Path(root)) for root in ws.config.code_roots
    ):
        raise Denied("backup destination must be outside workspace and public code")
    with ws.lock():
        contents = {"workspace.json": ws.fs.read("workspace.json")}
        for directory in DURABLE_DIRS:
            for path in ws.fs.files(directory):
                contents[path] = ws.fs.read(path)
        if sum(len(data) for data in contents.values()) > MAX_BACKUP_BYTES:
            raise CairnError("backup exceeds supported size; use documented filesystem backup")
        manifest = {
            "schema_version": 1,
            "workspace_id": ws.config.id,
            "files": {name: digest(data) for name, data in contents.items()},
        }
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", canonical(manifest))
            for path, data in sorted(contents.items()):
                archive.writestr(path, data)
        output = buffer.getvalue()
        destination.parent.mkdir(parents=True, exist_ok=True)
        RootFS(destination.parent).write(destination.name, output, exclusive=True)
        return {"workspace_id": ws.config.id, "files": len(contents), "sha256": digest(output)}


def restore(archive_path: Path, destination: Path, *, code_roots: list[Path]) -> Workspace:
    destination = check_roots(destination, code_roots)
    if destination.exists() and any(destination.iterdir()):
        raise Conflict("restore requires an empty destination")
    fd = os.open(archive_path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        RootFS._regular(os.fstat(stream.fileno()))
        raw = stream.read(MAX_BACKUP_BYTES + 1)
    if len(raw) > MAX_BACKUP_BYTES:
        raise CairnError("archive exceeds size limit")
    payloads: dict[str, bytes] = {}
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            members = archive.infolist()
            if (
                len(members) > 10000
                or sum(item.file_size for item in members) > MAX_BACKUP_BYTES
                or any(item.file_size > MAX_FILE_BYTES for item in members)
            ):
                raise CairnError("archive expands beyond limits")
            for item in members:
                parts = components(item.filename)
                mode = item.external_attr >> 16
                if (
                    item.is_dir()
                    or stat.S_ISLNK(mode)
                    or item.filename in payloads
                    or (
                        len(parts) == 1 and item.filename not in ("workspace.json", "manifest.json")
                    )
                    or (len(parts) > 1 and parts[0] not in DURABLE_DIRS)
                ):
                    raise Denied("archive contains an unauthorized member")
                payloads[item.filename] = archive.read(item)
    except (zipfile.BadZipFile, KeyError) as exc:
        raise CairnError("invalid backup archive") from exc
    manifest = json.loads(payloads.pop("manifest.json"))
    if manifest.get("schema_version") != 1 or manifest.get("files") != {
        path: digest(data) for path, data in payloads.items()
    }:
        raise Conflict("backup manifest checksum mismatch")
    config = WorkspaceConfig.model_validate_json(payloads["workspace.json"])
    if config.id != manifest["workspace_id"]:
        raise Conflict("backup workspace identity mismatch")
    if not config.synthetic:
        raise Denied("private restore requires a reviewed runtime activation")
    config.code_roots = [str(root.resolve()) for root in code_roots]
    payloads["workspace.json"] = canonical(config)
    from cairn.storage.markdown import decode

    for path, data in payloads.items():
        if path.startswith("vault/sources/") and path.endswith(".md"):
            source, _ = decode(data)
            if source.source is None or source.source.blob not in payloads:
                raise Conflict("backup omits referenced source bytes")
            if digest(payloads[source.source.blob]) != source.source.content_hash:
                raise Conflict("backup source checksum mismatch")
            if source.source.extraction:
                evidence_hash = source.source.extraction.evidence_hash
                evidence_path = f"evidence/{evidence_hash}.json"
                if (
                    evidence_path not in payloads
                    or digest(payloads[evidence_path]) != evidence_hash
                ):
                    raise Conflict("backup omits or corrupts accepted evidence")
    # All archive members and hashes are validated before any restored content is written.
    destination.mkdir(parents=True, mode=0o700, exist_ok=True)
    fs = RootFS(destination)
    for path, data in sorted(payloads.items()):
        fs.write(path, data, exclusive=True)
    ws = Workspace(destination)
    for _, record, _ in ws.records():
        if record.source and digest(ws.fs.read(record.source.blob)) != record.source.content_hash:
            raise Conflict("restored source blob checksum mismatch")
    return ws
