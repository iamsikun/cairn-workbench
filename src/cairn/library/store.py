"""Library observations and owner actions use the workspace lock and crash journal.

The journal is owner-only. Model proposals cannot write these entities or receipts.
No library transaction can write evidence, human notes, policy, or approvals.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from cairn.errors import Conflict, Denied
from cairn.library.models import metadata
from cairn.records.models import ID, Digest, Model, Record, canonical, digest, new_id, now
from cairn.storage.markdown import decode, encode
from cairn.storage.workspace import Workspace
from cairn.transactions.apply import Entry, _crash


class LibraryTransaction(Model):
    schema_version: Literal[1] = 1
    kind: Literal["library"] = "library"
    id: ID
    workspace_id: ID
    policy_hash: Digest
    operation: str
    at: datetime
    status: Literal["prepared", "committed"] = "prepared"
    entries: list[Entry]


def record_path(record: Record) -> str:
    if metadata(record) is None:
        raise Denied("not a library entity")
    return f"vault/wiki/research/{record.id}.md"


def validate_entry(entry: Entry) -> None:
    if digest(entry.after.encode()) != entry.after_hash or (
        entry.before is not None and digest(entry.before.encode()) != entry.before_hash
    ):
        raise Conflict("library journal checksum mismatch")
    if entry.path.startswith("vault/wiki/research/"):
        record, _ = decode(entry.after.encode())
        if record_path(record) != entry.path:
            raise Denied("library journal identity mismatch")
        if entry.before is not None:
            old, _ = decode(entry.before.encode())
            if metadata(old) is None or old.id != record.id:
                raise Denied("library cannot overwrite other records")
    elif entry.path.startswith("receipts/library/"):
        from cairn.records.json import read_json

        read_json(entry.after.encode())
    else:
        raise Denied("library transaction target denied")


def complete_unlocked(ws: Workspace, tx: LibraryTransaction) -> None:
    if tx.workspace_id != ws.config.id or tx.policy_hash != ws.policy_hash:
        raise Conflict("library transaction workspace or policy changed")
    for entry in tx.entries:
        validate_entry(entry)
        current = digest(ws.fs.read(entry.path)) if ws.fs.exists(entry.path) else None
        if current not in (entry.before_hash, entry.after_hash):
            raise Conflict("library recovery conflicts with owner bytes")
    for index, entry in enumerate(tx.entries):
        ws.fs.write(entry.path, entry.after.encode())
        _crash(ws, f"library_write:{index}")
    tx.status = "committed"
    ws.fs.write(f"journal/{tx.id}/transaction.json", canonical(tx))


def commit_unlocked(ws: Workspace, outputs: dict[str, bytes], operation: str) -> str | None:
    entries = []
    for path, after in outputs.items():
        before = ws.fs.read(path) if ws.fs.exists(path) else None
        if before == after:
            continue
        entry = Entry(
            path=path,
            before=before.decode() if before is not None else None,
            before_hash=digest(before) if before is not None else None,
            after=after.decode(),
            after_hash=digest(after),
        )
        validate_entry(entry)
        entries.append(entry)
    if not entries:
        return None
    # Bounded transactions keep a large scan from becoming one oversized journal.
    # Scan/discovery checkpoints are inserted last and publish only after all batches.
    for offset in range(0, len(entries), 64):
        tx = LibraryTransaction(
            id=new_id("librarytx"),
            workspace_id=ws.config.id,
            policy_hash=ws.policy_hash,
            operation=operation,
            at=now(),
            entries=entries[offset : offset + 64],
        )
        ws.fs.write(f"journal/{tx.id}/transaction.json", canonical(tx), exclusive=True)
        _crash(ws, "library_prepared")
        complete_unlocked(ws, tx)
    from cairn.errors import CairnError
    from cairn.storage.history import snapshot

    try:
        snapshot(ws, f"Library {operation}")
    except CairnError:
        ws.fs.write(f"receipts/library/history/{tx.id}.json", canonical({"history": "pending"}))
    return tx.id


def entity_bytes(record: Record) -> bytes:
    return encode(record, f"# {record.title}\n\nOwner-maintained library catalog entry.\n")


def entities_unlocked(ws: Workspace, scope_name: str) -> list[Record]:
    scope = ws.policy.scope(scope_name)
    return [record for _, record, _ in ws.records(scope) if metadata(record) is not None]


def recover_library_unlocked(ws: Workspace) -> list[str]:
    recovered = []
    for path in ws.fs.files("journal"):
        if not path.endswith("/transaction.json"):
            continue
        from cairn.records.json import read_json

        data = read_json(ws.fs.read(path))
        if data.get("kind") != "library":
            continue
        tx = LibraryTransaction.model_validate(data)
        if tx.status != "committed":
            complete_unlocked(ws, tx)
            recovered.append(tx.id)
    return recovered
