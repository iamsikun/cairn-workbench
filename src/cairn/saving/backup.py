"""Checksummed archives. Restore always targets a fresh directory, never newer saves."""

import io
import json
import os
import tempfile
import zipfile
from pathlib import Path
from typing import Literal

from cairn.errors import Conflict, Denied
from cairn.records.models import ID, Digest, Model, canonical, digest
from cairn.saving.models import SaveReceipt, SaveTransaction, WorkspaceConfigV4
from cairn.saving.workspace import Book, check_root, decode, sync_directory
from cairn.storage.files import RootFS, components, disjoint

ROOTS = {
    "vault",
    "blobs",
    "evidence",
    "policy",
    "proposals",
    "approvals",
    "receipts",
    "journal",
    "migrations",
    "history.git",
    "legacy",
    "revisions",
    "recovery",
    "views",
}
LIMIT = 512 * 1024 * 1024


class ArchiveManifest(Model):
    schema_version: Literal[2] = 2
    workspace_id: ID
    files: dict[str, Digest]


def inventory(fs: RootFS) -> dict[str, bytes]:
    return {
        p: fs.read(p) for p in ["workspace.json", *(p for root in ROOTS for p in fs.files(root))]
    }


def validate(payloads: dict[str, bytes]) -> None:
    seen: set[str] = set()
    for path in payloads:
        parts = components(path)
        if path != "workspace.json" and (len(parts) < 2 or parts[0] not in ROOTS):
            raise Denied("unauthorized archive path")
        folded = path.casefold()
        if folded in seen:
            raise Denied("ambiguous archive path")
        seen.add(folded)
    if any(
        "/".join(p.split("/")[:i]).casefold() in seen
        for p in payloads
        for i in range(1, len(p.split("/")))
    ):
        raise Denied("archive file/directory collision")
    raw_config = payloads.get("workspace.json", b"{}")
    if json.loads(raw_config).get("schema_version") != 4:
        from cairn.storage.backup import validate_payloads

        validate_payloads(payloads)
        return
    config = WorkspaceConfigV4.model_validate_json(raw_config)
    rows = {}
    for path, raw in payloads.items():
        if path.startswith("vault/collections/") and path.endswith(".md"):
            record, _ = decode(raw)
            if (
                path != f"vault/collections/{record.collection}/{record.id}.md"
                or record.collection not in config.collections
            ):
                raise Denied("archive record path mismatch")
            rows[(record.collection, record.id)] = record
        elif path.startswith("blobs/") and path != "blobs/" + digest(raw):
            raise Denied("archive source checksum mismatch")
        elif path.startswith("revisions/"):
            receipt = SaveReceipt.model_validate_json(raw)
            if path != f"revisions/{receipt.collection}/{receipt.operation_hash}.json":
                raise Denied("archive receipt identity mismatch")
        elif path.startswith("journal/saves/"):
            tx = SaveTransaction.model_validate_json(raw)
            if tx.status != "committed" or path != f"journal/saves/{tx.id}.json":
                raise Denied("archive contains an incomplete save")
    from cairn.saving.references import validate_references

    for collection in config.collections:
        selected = {key: record for (domain, key), record in rows.items() if domain == collection}
        for record in selected.values():
            if not record.archived:
                validate_references(record, selected)
            if record.source:
                source = record.source
                for blob, checksum in [
                    (source.blob, source.content_hash),
                    (source.original_blob, source.original_hash),
                ]:
                    if blob and (blob not in payloads or digest(payloads[blob]) != checksum):
                        raise Denied("archive omits immutable source bytes")
            if (
                record.legacy_path
                and digest(payloads.get(record.legacy_path, b"")) != record.legacy_hash
            ):
                raise Denied("archive changed legacy provenance")


def write_archive(payloads: dict[str, bytes], destination: Path) -> ArchiveManifest:
    validate(payloads)
    if sum(map(len, payloads.values())) > LIMIT:
        raise Denied("backup exceeds size budget")
    manifest = ArchiveManifest(
        workspace_id=json.loads(payloads["workspace.json"])["id"],
        files={p: digest(v) for p, v in payloads.items()},
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", canonical(manifest))
        for path, raw in sorted(payloads.items()):
            archive.writestr(path, raw)
    fs = RootFS(destination.absolute().parent)
    if fs.exists(destination.name):
        prior, checked = read_archive(destination)
        if checked == manifest and prior == payloads:
            return manifest
        raise Conflict("backup destination contains different content")
    fs.write(destination.name, buffer.getvalue(), exclusive=True, limit=LIMIT + 16 * 1024 * 1024)
    restored, checked = read_archive(destination)
    if checked != manifest or restored != payloads:
        raise Conflict("backup verification failed")
    return manifest


def read_archive(path: Path) -> tuple[dict[str, bytes], ArchiveManifest]:
    raw = RootFS(path.absolute().parent).read(path.name, limit=LIMIT + 16 * 1024 * 1024)
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        infos = archive.infolist()
        if (
            len(infos) > 100000
            or len({i.filename for i in infos}) != len(infos)
            or sum(i.file_size for i in infos) > LIMIT
        ):
            raise Denied("invalid archive inventory or size")
        for info in infos:
            components(info.filename)
            if info.is_dir() or (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise Denied("archive contains a non-regular member")
        manifest_raw = archive.read("manifest.json")
        if json.loads(manifest_raw).get("schema_version") == 1:
            from cairn.storage.backup import BackupManifest

            old = BackupManifest.model_validate_json(manifest_raw)
            manifest = ArchiveManifest(workspace_id=old.workspace_id, files=old.files)
        else:
            manifest = ArchiveManifest.model_validate_json(manifest_raw)
        payloads = {i.filename: archive.read(i) for i in infos if i.filename != "manifest.json"}
    if manifest.files != {p: digest(v) for p, v in payloads.items()}:
        raise Denied("archive checksum mismatch")
    validate(payloads)
    if json.loads(payloads["workspace.json"])["id"] != manifest.workspace_id:
        raise Denied("archive workspace mismatch")
    return payloads, manifest


def backup(book: Book, destination: Path) -> ArchiveManifest:
    if not disjoint(book.root, destination.absolute()):
        raise Denied("backup must be outside the workspace")
    with book.lock():
        return write_archive(inventory(book.fs), destination)


def restore(archive: Path, destination: Path) -> dict[str, str]:
    payloads, manifest = read_archive(archive)
    destination = check_root(destination)
    if destination.exists():
        raise Conflict("restore requires a new destination; newer saves are never overwritten")
    destination.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".cairn-restore-", dir=destination.parent))
    fs = RootFS(stage)
    for path, raw in payloads.items():
        fs.write(path, raw, exclusive=True)
    if {p: digest(v) for p, v in inventory(fs).items()} != manifest.files:
        raise Conflict("restore verification failed; staging directory preserved")
    os.rename(stage, destination)
    sync_directory(destination.parent)
    return {"workspace": str(destination), "workspace_id": manifest.workspace_id}
