from __future__ import annotations

from typing import Any

from cairn.errors import Conflict, Denied
from cairn.records.models import Domain, canonical, digest, new_id, now
from cairn.saving.models import (
    Capture,
    Entry,
    KnowledgeRecord,
    NoteChange,
    SavedNote,
    SaveNote,
    SaveReading,
    SaveReceipt,
    SaveTransaction,
    SourceInfo,
    SourceInput,
)
from cairn.saving.references import validate_references
from cairn.saving.workspace import Book, decode, encode
from cairn.transactions.writer import commit, operation_hash


def normalize_identity(value: str) -> str:
    value = value.strip()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if value.lower().startswith(prefix):
            return "doi:" + value[len(prefix) :].strip().lower()
    return "doi:" + value.lower() if value.startswith("10.") and "/" in value else value


def source_record(source: SourceInput, collection: Domain) -> tuple[KnowledgeRecord, str]:
    source = source.model_copy(update={"identity": normalize_identity(source.identity)})
    identity = (
        "source_"
        + digest(
            canonical(
                [
                    collection,
                    source.identity,
                    source.version,
                    source.text,
                ]
            )
        )[:32]
    )
    text = source.text
    info = SourceInfo(
        **source.model_dump(), extraction_status="supplied" if text else "unavailable"
    )
    if text is not None:
        info.content_hash = digest(text.encode())
        info.blob = f"blobs/{info.content_hash}"
    return KnowledgeRecord(
        id=identity,
        type="source",
        kind="source",
        title=source.title,
        collection=collection,
        source=info,
        coverage=source.coverage,
        enrichment="complete",
    ), text or "External source; local content unavailable.\n"


def _path(record: KnowledgeRecord) -> str:
    return f"vault/collections/{record.collection}/{record.id}.md"


def _merge(
    old: KnowledgeRecord | None, change: NoteChange, identity: str, collection: Domain
) -> KnowledgeRecord:
    if change.type == "source":
        raise Denied("use capture for immutable sources")
    if old and (old.type != change.type or old.source or old.archived):
        raise Denied("target cannot be changed by this save")
    record = (
        old.model_copy(deep=True)
        if old
        else KnowledgeRecord(
            id=identity,
            type=change.type,
            title=change.title,
            collection=collection,
        )
    )
    record.title = change.title
    record.kind = change.kind or record.kind
    record.enrichment = change.enrichment
    record.aliases = change.aliases if change.aliases is not None else record.aliases
    record.resources = change.resources if change.resources is not None else record.resources
    record.unresolved = change.unresolved if change.unresolved is not None else record.unresolved
    record.coverage = change.coverage if change.coverage is not None else record.coverage
    observations = {item.id: item for item in record.observations}
    for observation in change.observations:
        if observation.id in observations and observations[observation.id] != observation:
            raise Conflict("original observations are immutable; append a correction")
        observations[observation.id] = observation
    record.observations = list(observations.values())
    links = {(r.kind, r.target): r for r in record.relationships}
    for link in change.relationships:
        previous = links.get((link.kind, link.target))
        if previous and previous.state == "rejected" and link.state == "active":
            raise Conflict("relationship was rejected; an ordinary save cannot reinstate it")
        links[(link.kind, link.target)] = link
    record.relationships = list(links.values())
    citations = {canonical(c): c for c in [*record.citations, *change.citations]}
    record.citations = list(citations.values())
    return KnowledgeRecord.model_validate(record.model_dump())


def _result(book: Book, receipt: SaveReceipt) -> dict[str, Any]:
    from cairn.saving.retrieval import rebuild

    value: dict[str, Any] = receipt.model_dump(mode="json")
    try:
        rebuild(book, receipt.collection)
        value["index"] = "current"
    except Exception:  # Derived maintenance must never obscure a committed save.
        value["index"] = "pending"
    value["html"] = "not_requested"
    if not book.fs.files(f"views/{receipt.collection}"):
        return value
    try:
        from cairn.saving.views import maintain

        value["html"] = maintain(book, receipt.collection)
    except Exception:  # The authoritative receipt remains usable after renderer failures.
        value["html"] = "pending"
    return value


def save(
    book: Book, collection: Domain, request: SaveNote | SaveReading | Capture
) -> dict[str, Any]:
    book.collection(collection)
    op = operation_hash(collection, request.operation_key)
    payload = digest(canonical(request))
    with book.lock():
        receipt_path = f"revisions/{collection}/{op}.json"
        if book.fs.exists(receipt_path):
            receipt = SaveReceipt.model_validate_json(book.fs.read(receipt_path))
            if receipt.payload_hash != payload:
                raise Conflict("operation key already used for different content")
            return _result(book, receipt)
        rows = book.records(collection)
        available = {k: v[1] for k, v in rows.items()}
        drafts: list[tuple[KnowledgeRecord, str]] = []
        source = None
        if isinstance(request, (SaveReading, Capture)):
            source, text = source_record(
                request.paper if isinstance(request, SaveReading) else request.source,
                collection,
            )
            if isinstance(request, Capture) and request.pdf_base64 is not None:
                from cairn.saving.sources import attach_pdf

                source, text = attach_pdf(book, source, request.pdf_base64)
            if isinstance(request, SaveReading) and request.source_id:
                existing = rows.get(request.source_id)
                if existing is None or existing[1].source is None:
                    raise Denied("source unavailable in this collection")
                if normalize_identity(existing[1].source.identity) != normalize_identity(
                    request.paper.identity
                ):
                    raise Conflict("source identity differs from the paper identity")
                source, text = existing[1], existing[2]
            if source.id not in rows:
                drafts.append((source, text))
            else:
                source = rows[source.id][1]
        if isinstance(request, SaveNote):
            changes = [request.note, *(request.topics if isinstance(request, SaveReading) else [])]
            seen: set[str] = set()
            for index, change in enumerate(changes):
                identity = change.id or f"{change.type}_" + digest(canonical([op, index]))[:32]
                if isinstance(request, SaveReading) and index == 0:
                    paper_identity = normalize_identity(request.paper.identity)
                    paper_id = (
                        "concept_paper_" + digest(canonical([collection, paper_identity]))[:32]
                    )
                    matches = [
                        r.id for r in available.values() if r.paper_identity == paper_identity
                    ]
                    if len(matches) > 1 and change.id is None:
                        raise Conflict("multiple paper notes; choose a target revision")
                    if matches and change.id is not None and change.id not in matches:
                        raise Conflict("paper already has a note; update its current revision")
                    identity = change.id or (matches[0] if matches else paper_id)
                if identity in seen:
                    raise Conflict("duplicate target in save")
                seen.add(identity)
                old_row = rows.get(identity)
                if old_row and book.revision(old_row[0]) != change.expected_revision:
                    book.fs.write(f"recovery/{collection}/{op}.json", canonical(request))
                    raise Conflict("note changed; retrieve its current revision and reconcile")
                if old_row is None and change.expected_revision is not None:
                    raise Conflict("expected revision supplied for a missing record")
                old = old_row[1] if old_row else None
                record = _merge(old, change, identity, collection)
                if isinstance(request, SaveReading) and index == 0:
                    assert source is not None
                    if old and old.paper_identity not in (None, paper_identity):
                        raise Denied("target belongs to a different paper")
                    record.kind = "paper"
                    record.primary_source_id = source.id
                    record.source_versions = list(
                        dict.fromkeys([*record.source_versions, source.id])
                    )
                    record.paper_identity = paper_identity
                    record.coverage = request.paper.coverage
                drafts.append((record, change.markdown))
        available.update({record.id: record for record, _ in drafts})
        for record, _ in drafts:
            validate_references(record, available)
        entries = []
        notes = []
        for record, body in drafts:
            path = _path(record)
            before = book.fs.read(path).decode() if book.fs.exists(path) else None
            after = encode(record, body).decode()
            if before is not None and before != after:
                record.updated_at = now()
                after = encode(record, body).decode()
            if before != after:
                entries.append(Entry(path=path, before=before, after=after))
            notes.append(
                SavedNote(
                    id=record.id,
                    path=path,
                    revision=digest(after.encode()),
                    enrichment=record.enrichment,
                )
            )
            if record.source and record.source.text is not None and record.source.blob:
                raw = record.source.text.encode()
                if book.fs.exists(record.source.blob):
                    if book.fs.read(record.source.blob) != raw:
                        raise Conflict("source blob checksum mismatch")
                else:
                    book.fs.write(record.source.blob, raw, exclusive=True)
        if isinstance(request, Capture) and not drafts and source:
            path = rows[source.id][0]
            notes.append(
                SavedNote(
                    id=source.id,
                    path=path,
                    revision=book.revision(path),
                    enrichment=source.enrichment,
                )
            )
        receipt = SaveReceipt(
            id=new_id("revision"),
            operation_hash=op,
            payload_hash=payload,
            collection=collection,
            notes=notes,
            status="saved" if entries else "unchanged",
            client=request.client if isinstance(request, SaveNote) else None,
            model=request.model if isinstance(request, SaveNote) else None,
        )
        if entries:
            commit(
                book,
                SaveTransaction(
                    id=receipt.id, collection=collection, entries=entries, receipt=receipt
                ),
            )
        else:
            book.fs.write(receipt_path, canonical(receipt), exclusive=True)
        return _result(book, receipt)


def recent(book: Book, collection: Domain, limit: int = 20) -> list[SaveReceipt]:
    book.collection(collection)
    with book.lock():
        receipts = [
            SaveReceipt.model_validate_json(book.fs.read(p))
            for p in book.fs.files(f"revisions/{collection}")
        ]
        return sorted(
            (r for r in receipts if r.status == "saved"), key=lambda r: r.at, reverse=True
        )[: max(1, min(limit, 100))]


def undo(book: Book, collection: Domain, revision: str, key: str) -> dict[str, Any]:
    op = operation_hash(collection, key)
    payload = digest(canonical(["undo", revision]))
    with book.lock():
        receipt_path = f"revisions/{collection}/{op}.json"
        if book.fs.exists(receipt_path):
            receipt = SaveReceipt.model_validate_json(book.fs.read(receipt_path))
            if receipt.payload_hash != payload:
                raise Conflict("operation key already used")
            return _result(book, receipt)
        path = f"journal/saves/{revision}.json"
        if not book.fs.exists(path):
            raise Denied("revision unavailable")
        tx = SaveTransaction.model_validate_json(book.fs.read(path))
        if tx.collection != collection:
            raise Denied("revision unavailable")
        entries, notes = [], []
        for entry in tx.entries:
            if not book.fs.exists(entry.path) or book.fs.read(entry.path).decode() != entry.after:
                raise Conflict("undo conflicts with later work on a touched record")
            current, _ = decode(entry.after.encode())
            if current.type == "source":
                continue  # Captured evidence is retained, including after undo.
            if entry.before is None:
                current.archived = True
                current.updated_at = now()
                after = encode(current, decode(entry.after.encode())[1]).decode()
            else:
                restored, body = decode(entry.before.encode())
                # Undo cannot erase observations captured by subsequent reading checkpoints.
                obs = {o.id: o for o in [*restored.observations, *current.observations]}
                restored.observations = list(obs.values())
                restored.updated_at = now()
                after = encode(restored, body).decode()
            entries.append(Entry(path=entry.path, before=entry.after, after=after))
            notes.append(
                SavedNote(
                    id=current.id,
                    path=entry.path,
                    revision=digest(after.encode()),
                    enrichment=current.enrichment,
                )
            )
        removed = {
            decode(e.after.encode())[0].id for e in entries if decode(e.after.encode())[0].archived
        }
        touched = {decode(e.after.encode())[0].id for e in entries}
        for _, record, _ in book.records(collection).values():
            if (
                record.id not in touched
                and not record.archived
                and any(r.target in removed and r.state == "active" for r in record.relationships)
            ):
                raise Conflict("newer links refer to a created note; remove those links first")
        receipt = SaveReceipt(
            id=new_id("revision"),
            operation_hash=op,
            payload_hash=payload,
            collection=collection,
            notes=notes,
            undo_of=revision,
        )
        commit(
            book,
            SaveTransaction(id=receipt.id, collection=collection, entries=entries, receipt=receipt),
        )
        return _result(book, receipt)
