"""Explicit schemas 1–3 conversion, retaining legacy bytes and pending proposals."""

import fcntl
import json
import os
from pathlib import Path
from typing import Any

from cairn.errors import Conflict, Denied, RecoveryRequired
from cairn.ingest.notes import _front_matter
from cairn.records.models import Domain, Extraction, canonical, digest, new_id
from cairn.saving.backup import inventory, read_archive, validate, write_archive
from cairn.saving.models import (
    Citation,
    KnowledgeRecord,
    Observation,
    Relationship,
    SavedNote,
    SaveReceipt,
    SourceInfo,
    WorkspaceConfigV4,
)
from cairn.saving.workspace import check_root, encode
from cairn.storage.files import RootFS, disjoint
from cairn.storage.markdown import decode as legacy_decode
from cairn.storage.workspace import parse_config


def _crash(synthetic: bool, point: str) -> None:
    if synthetic and os.environ.get("CAIRN_MIGRATION_CRASH_AT") == point:
        os._exit(78)


def _convert(payloads: dict[str, bytes], mapping: dict[str, Domain]) -> dict[str, bytes]:
    config = parse_config(payloads["workspace.json"])
    additions: dict[str, bytes] = {}
    records = {}
    for path, raw in payloads.items():
        if path.startswith(("vault/sources/", "vault/wiki/", "vault/decisions/")) and path.endswith(
            ".md"
        ):
            old, body = legacy_decode(raw)
            if old.id in records:
                raise Conflict("duplicate legacy identity")
            info = None
            if old.source:
                source = old.source
                text, locators = None, {}
                if source.extraction:
                    extraction = Extraction.model_validate_json(
                        payloads[f"evidence/{source.extraction.evidence_hash}.json"]
                    )
                    locators = {s.locator: s.text for s in extraction.segments}
                    text = "\n".join(locators.values())
                info = SourceInfo(
                    identity=source.identity,
                    title=old.title,
                    origin=source.origin,
                    version=source.version,
                    authors=source.authors,
                    text=text,
                    original_blob=source.blob,
                    original_hash=source.content_hash,
                    coverage=source.extraction.coverage if source.extraction else "unknown",
                    extraction_status="extracted" if text is not None else "unavailable",
                    locators=locators,
                )
            refs = [
                *old.sources,
                *(ref for assertion in old.assertions for ref in assertion.sources),
            ]
            record = KnowledgeRecord(
                id=old.id,
                type=old.type,
                title=old.title,
                collection=old.domain,
                kind="source" if info else "paper" if old.primary_source_id else "note",
                source=info,
                created_at=old.created_at,
                updated_at=old.updated_at,
                aliases=old.aliases,
                primary_source_id=old.primary_source_id,
                source_versions=[old.primary_source_id] if old.primary_source_id else [],
                citations=[Citation(id=c.id, locator=c.locator, quote=c.quote) for c in refs],
                relationships=[
                    Relationship(
                        target=t,
                        explanation="Imported legacy related link; its rationale was not recorded.",
                    )
                    for t in old.related
                ],
                legacy_path=path,
                legacy_hash=digest(raw),
                legacy_state=old.status,
                coverage=info.coverage if info else "unknown",
                enrichment="pending",
            )
            records[record.id] = (record, body)
        elif path.startswith(("vault/notes/", "vault/inbox/")) and path.endswith(".md"):
            meta, body = _front_matter(raw.decode())
            parts = path.split("/")
            domain = (
                mapping.get(path) or meta.get("domain") or (parts[2] if len(parts) > 3 else None)
            )
            if domain not in ("research", "finance", "life", "shared"):
                raise Denied(f"explicit collection mapping required for {path}")
            record = KnowledgeRecord(
                id="concept_human_" + digest(path.encode())[:24],
                type="concept",
                title=str(meta.get("title") or parts[-1].removesuffix(".md"))[:500],
                collection=domain,
                legacy_path=path,
                legacy_hash=digest(raw),
                legacy_state="human_note",
                observations=[
                    Observation(
                        id="observation_" + digest(canonical([path, i]))[:24],
                        text=body[i : i + 20000],
                    )
                    for i in range(0, len(body), 20000)
                ],
            )
            records[record.id] = (record, body)
    for record, body in records.values():
        visible = {key for key, (r, _) in records.items() if r.collection == record.collection}
        hidden = any(r.target not in visible for r in record.relationships) or any(
            c.id not in visible for c in record.citations
        )
        record.relationships = [r for r in record.relationships if r.target in visible]
        record.citations = [c for c in record.citations if c.id in visible]
        if record.primary_source_id not in visible:
            record.primary_source_id = None
            record.source_versions = []
        if hidden:
            record.unresolved.append(
                "Cross-collection legacy links remain in the original archive."
            )
        if record.primary_source_id:
            primary = records[record.primary_source_id][0].source
            if primary:
                from cairn.saving.service import normalize_identity

                record.paper_identity = normalize_identity(primary.identity)
        additions[f"vault/collections/{record.collection}/{record.id}.md"] = encode(record, body)
    additions[f"legacy/workspace-v{config.schema_version}.json"] = payloads["workspace.json"]
    additions["workspace.json"] = canonical(
        WorkspaceConfigV4(id=config.id, synthetic=config.synthetic)
    )
    return additions


def migrate(root: Path, backup: Path, mapping: dict[str, Domain] | None = None) -> dict[str, Any]:
    root = check_root(root)
    if not disjoint(root, backup.absolute()):
        raise Denied("migration backup must be outside the workspace")
    fs = RootFS(root)
    with fs.parent("workspace.lock") as (parent, name):
        fd = os.open(name, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600, dir_fd=parent)
    try:
        fs._regular(os.fstat(fd))
        fcntl.flock(fd, fcntl.LOCK_EX)
        if fs.exists("migration.pending"):
            tx = json.loads(fs.read("migration.pending"))
            if tx["backup"] != str(backup.absolute()):
                raise Conflict("resume with the original backup path")
        else:
            raw = fs.read("workspace.json")
            if json.loads(raw).get("schema_version") == 4:
                return {"status": "already_current"}
            config = parse_config(raw)
            for path in [*fs.files("journal"), *fs.files("migrations")]:
                if path.endswith("transaction.json") and json.loads(fs.read(path)).get(
                    "status"
                ) not in ("committed", "rolled_back"):
                    raise RecoveryRequired(
                        "resolve legacy transactions with the legacy runtime before migration"
                    )
            if fs.exists("restore.pending"):
                raise RecoveryRequired("finish the legacy restore first")
            payloads = inventory(fs)
            additions = _convert(payloads, mapping or {})
            validate({**payloads, **additions})
            manifest = write_archive(payloads, backup)
            identity = new_id("migration")
            for collection in ("research", "finance", "life", "shared"):
                notes = []
                from cairn.saving.workspace import decode

                for path, raw in additions.items():
                    if path.startswith(f"vault/collections/{collection}/"):
                        record, _ = decode(raw)
                        notes.append(
                            SavedNote(
                                id=record.id,
                                path=path,
                                revision=digest(raw),
                                enrichment=record.enrichment,
                            )
                        )
                if notes:
                    key = digest(canonical([identity, collection]))
                    receipt = SaveReceipt(
                        id=new_id("revision"),
                        operation_hash=key,
                        payload_hash=digest(canonical(manifest)),
                        collection=collection,
                        notes=notes,
                        client="legacy-migration",
                    )
                    additions[f"revisions/{collection}/{key}.json"] = canonical(receipt)
            tx = {
                "id": identity,
                "status": "prepared",
                "synthetic": config.synthetic,
                "backup": str(backup.absolute()),
                "backup_hash": digest(backup.read_bytes()),
                "inventory": manifest.files,
                "additions": {p: v.decode() for p, v in additions.items()},
            }
            fs.write("migration.pending", canonical(tx), exclusive=True)
            _crash(config.synthetic, "prepared")
        if digest(backup.read_bytes()) != tx["backup_hash"]:
            raise Conflict("migration backup changed; conversion stopped")
        _, manifest = read_archive(backup)
        if manifest.files != tx["inventory"]:
            raise Conflict("migration inventory differs from verified backup")
        additions = {p: v.encode() for p, v in tx["additions"].items()}
        for path, checksum in tx["inventory"].items():
            current = fs.read(path)
            if digest(current) != checksum and current != additions.get(path):
                raise Conflict(
                    "legacy bytes changed during migration; preserved for reconciliation"
                )
        for path, raw in additions.items():
            if path != "workspace.json" and fs.exists(path) and fs.read(path) != raw:
                raise Conflict("conversion target changed; preserved for reconciliation")
        # Config switches last; old executables reject schema 4 and cannot rebind it.
        for index, (path, raw) in enumerate(additions.items()):
            if path != "workspace.json":
                fs.write(path, raw)
                _crash(tx["synthetic"], f"write:{index}")
        fs.write("workspace.json", additions["workspace.json"])
        _crash(tx["synthetic"], "config")
        validate(inventory(fs))
        tx["status"] = "committed"
        fs.write(f"legacy/migrations/{tx['id']}.json", canonical(tx))
        fs.remove("migration.pending")
        return {
            "status": "migrated",
            "id": tx["id"],
            "backup": str(backup),
            "original_files": len(tx["inventory"]),
            "converted_files": len(additions),
        }
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
