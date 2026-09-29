from __future__ import annotations

import base64
import os
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import JsonValue

from cairn.adapters.isolation import invoke_worker
from cairn.errors import Blocked, CairnError, Conflict
from cairn.ingest.extractors import extract_bytes
from cairn.policies.models import require_inheritance
from cairn.records.models import (
    Classification,
    Domain,
    Event,
    Extraction,
    ExtractionMetadata,
    Processing,
    Record,
    SourceMetadata,
    canonical,
    digest,
    new_id,
    now,
)
from cairn.storage.files import MAX_FILE_BYTES, RootFS
from cairn.storage.markdown import encode
from cairn.storage.workspace import Workspace

SourceType = Literal["text", "markdown", "pdf", "conversation", "bibliography", "receipt"]


def read_source_file(file: Path) -> bytes:
    fd = os.open(file, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        RootFS._regular(os.fstat(stream.fileno()))
        data = stream.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        raise CairnError("source exceeds capture limit")
    return data


def capture(
    ws: Workspace,
    file: Path,
    *,
    domain: Domain,
    title: str | None = None,
    identity: str | None = None,
    version: str | None = None,
    classification: Classification = "private",
    processing: Processing = "local_only",
    source_type: SourceType | None = None,
    project_ids: list[str] | None = None,
    compartments: set[str] | None = None,
) -> Record:
    data = read_source_file(file)
    kinds: dict[str, SourceType] = {
        ".md": "markdown",
        ".txt": "text",
        ".pdf": "pdf",
        ".json": "conversation",
        ".bib": "bibliography",
    }
    kind = source_type or kinds.get(file.suffix.lower())
    if kind is None:
        raise CairnError("unsupported capture format")
    return capture_bytes(
        ws,
        data,
        origin=file.name,
        domain=domain,
        title=title or file.name,
        identity=identity or file.name,
        version=version,
        classification=classification,
        processing=processing,
        source_type=kind,
        project_ids=project_ids,
        compartments=compartments,
    )


def capture_bytes(
    ws: Workspace,
    data: bytes,
    *,
    origin: str,
    domain: Domain,
    title: str,
    identity: str,
    source_type: SourceType,
    version: str | None = None,
    classification: Classification = "private",
    processing: Processing = "local_only",
    project_ids: list[str] | None = None,
    compartments: set[str] | None = None,
    source_date: date | None = None,
    external_id: str | None = None,
    citation_key: str | None = None,
    authors: list[str] | None = None,
    bibliography: dict[str, JsonValue] | None = None,
    library_alias: str | None = None,
    scope_name: str | None = None,
) -> Record:
    if len(data) > MAX_FILE_BYTES:
        raise CairnError("source exceeds capture limit")
    source_identity = identity
    checksum = digest(data)
    with ws.lock(write=True):
        scope = ws.policy.scope(scope_name) if scope_name else None
        projects = [ws.record(project_id, scope)[1] for project_id in (project_ids or [])]
        previous: list[str] = []
        for _, existing, _ in ws.records():
            meta = existing.source
            if (
                meta
                and meta.identity == source_identity
                and existing.domain == domain
                and existing.classification == classification
                and existing.processing == processing
                and existing.compartments == (compartments or set())
                and existing.project_ids == (project_ids or [])
            ):
                if meta.content_hash == checksum and meta.version == version:
                    if scope:
                        scope.require(existing)
                    require_inheritance(existing, projects)
                    if (
                        meta.source_type != source_type
                        or meta.source_date != source_date
                        or meta.external_id != external_id
                        or meta.citation_key != citation_key
                        or meta.authors != (authors or [])
                        or meta.bibliography != bibliography
                        or meta.library_alias != library_alias
                    ):
                        raise Conflict("source metadata changed for identical captured bytes")
                    return existing
                if version is not None and meta.version == version:
                    raise Conflict("declared source version has different bytes")
                previous.append(existing.id)
        timestamp = now()
        record = Record(
            id=new_id("source"),
            type="source",
            title=title,
            domain=domain,
            classification=classification,
            processing=processing,
            compartments=compartments or set(),
            project_ids=project_ids or [],
            created_at=timestamp,
            updated_at=timestamp,
            source=SourceMetadata(
                identity=source_identity,
                origin=origin,
                source_type=source_type,
                captured_at=timestamp,
                content_hash=checksum,
                blob=f"blobs/{checksum}",
                version=version,
                supersedes=previous,
                source_date=source_date,
                external_id=external_id,
                citation_key=citation_key,
                authors=authors or [],
                bibliography=bibliography,
                library_alias=library_alias,
            ),
        )
        if scope:
            scope.require(record)
        require_inheritance(record, projects)
        if ws.fs.exists(f"blobs/{checksum}"):
            if digest(ws.fs.read(f"blobs/{checksum}")) != checksum:
                raise Conflict("stored source blob is corrupt")
        else:
            ws.fs.write(f"blobs/{checksum}", data, exclusive=True)
        ws.fs.write(f"vault/sources/{record.id}.md", encode(record, ""), exclusive=True)
        ws.event(
            Event(
                id=new_id("event"),
                object_id=record.id,
                attempt_id=new_id("attempt"),
                stage="captured",
                at=timestamp,
                hashes={"source": checksum},
            )
        )
        return record


def load_extraction(ws: Workspace, source: Record) -> tuple[Extraction, str]:
    if source.source is None or source.source.extraction is None:
        raise Blocked("source has not been extracted")
    key = source.source.extraction.evidence_hash
    raw = ws.fs.read(f"evidence/{key}.json")
    if digest(raw) != key:
        raise Conflict("evidence checksum mismatch")
    extraction = Extraction.model_validate_json(raw)
    if (
        extraction.source_id != source.id
        or extraction.source_hash != source.source.content_hash
        or digest(ws.fs.read(source.source.blob)) != source.source.content_hash
    ):
        raise Conflict("source/evidence binding mismatch")
    return extraction, key


def extract(
    ws: Workspace,
    source_id: str,
    *,
    scope_name: str = "owner",
    inline_synthetic: bool = False,
) -> tuple[Extraction, str]:
    with ws.lock(write=True):
        path, source, body = ws.record(source_id, ws.policy.scope(scope_name))
        if source.source is None:
            raise CairnError("extraction requires a source")
        if source.source.extraction and source.source.extraction.coverage != "failed":
            return load_extraction(ws, source)
        data = ws.fs.read(source.source.blob)
        attempt = new_id("attempt")
        try:
            if inline_synthetic and ws.config.synthetic:
                result = extract_bytes(source, data)
            elif ws.config.worker_image:
                job = {
                    "operation": "extract",
                    "source": source.model_dump(mode="json"),
                    "data": base64.b64encode(data).decode(),
                }
                result = Extraction.model_validate_json(
                    invoke_worker(ws.config.worker_image, canonical(job))
                )
            else:
                raise Blocked("isolation_unavailable: configure a pinned worker image")
            if result.source_id != source.id or result.source_hash != source.source.content_hash:
                raise Conflict("worker returned evidence for another source")
            evidence_hash = digest(canonical(result))
            if not ws.fs.exists(f"evidence/{evidence_hash}.json"):
                ws.fs.write(f"evidence/{evidence_hash}.json", canonical(result), exclusive=True)
            source.source.extraction = ExtractionMetadata(
                evidence_hash=evidence_hash,
                method=result.method,
                method_version=result.method_version,
                coverage=result.coverage,
                images_inspected=result.images_inspected,
                tables_inspected=result.tables_inspected,
            )
            ws.fs.write(path, encode(source, body))
            if result.coverage == "failed":
                raise Blocked("no_extractable_text")
        except Exception as exc:
            ws.event(
                Event(
                    id=new_id("event"),
                    object_id=source_id,
                    attempt_id=attempt,
                    stage="captured",
                    outcome="blocked" if isinstance(exc, Blocked) else "failed",
                    reason=exc.code if isinstance(exc, CairnError) else "extraction_failed",
                    at=now(),
                )
            )
            if isinstance(exc, CairnError):
                raise
            raise CairnError("extraction failed; original capture preserved") from exc
        ws.event(
            Event(
                id=new_id("event"),
                object_id=source_id,
                attempt_id=attempt,
                stage="extracted",
                at=now(),
                hashes={"evidence": evidence_hash},
            )
        )
        return result, evidence_hash


def latest_stage(ws: Workspace, object_id: str) -> str | None:
    events = [
        Event.model_validate_json(ws.fs.read(path)) for path in ws.fs.files("receipts/events")
    ]
    succeeded = [
        event for event in events if event.object_id == object_id and event.outcome == "succeeded"
    ]
    if not succeeded:
        return None
    return max(succeeded, key=lambda event: event.at).stage
