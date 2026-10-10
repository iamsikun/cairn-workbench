"""Read-only import of owner-selected CSL-JSON exports; never a live library database."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import Field, JsonValue, TypeAdapter

from cairn.errors import CairnError, Conflict
from cairn.ingest.service import capture_bytes, read_source_file
from cairn.records.json import read_json
from cairn.records.models import ID, Model, canonical, digest
from cairn.storage.workspace import Workspace


class BibliographyImport(Model):
    schema_version: Literal[1] = 1
    library_alias: ID
    export_source_id: ID
    item_source_ids: list[ID] = Field(max_length=10000)


def bibliographic_fields(item: dict[str, JsonValue]) -> tuple[str, str, list[str], date | None]:
    external = item.get("id")
    if isinstance(external, bool) or not isinstance(external, (str, int)) or not str(external):
        raise CairnError("bibliography items require a stable string or integer ID")
    if not isinstance(item.get("type"), str):
        raise CairnError("bibliography item type is required")
    for key in ("title", "abstract", "citation-key", "version"):
        if key in item and not isinstance(item[key], str):
            raise CairnError("invalid bibliography text field")
    title = item.get("title") or "Untitled bibliography item"
    if not isinstance(title, str) or len(title) > 500 or len(str(external)) > 500:
        raise CairnError("bibliography title or ID exceeds limit")
    authors: list[str] = []
    names = item.get("author", [])
    if not isinstance(names, list):
        raise CairnError("bibliography authors must be a list")
    for author in names:
        if not isinstance(author, dict):
            raise CairnError("invalid bibliography author")
        for key in ("literal", "family", "given", "non-dropping-particle", "suffix"):
            if key in author and not isinstance(author[key], str):
                raise CairnError("invalid bibliography author name")
        name = author.get("literal") or " ".join(
            str(author[key])
            for key in ("given", "non-dropping-particle", "family", "suffix")
            if author.get(key)
        )
        if name:
            authors.append(str(name))
    source_date = None
    issued = item.get("issued")
    if isinstance(issued, dict):
        parts = issued.get("date-parts")
        if isinstance(parts, list) and len(parts) == 1 and isinstance(parts[0], list):
            values = parts[0]
            # CSL allows integer or digit-string parts. A year or year-month alone stays
            # unknown here; the raw item preserves it.
            if len(values) == 3 and all(
                type(value) is int or (isinstance(value, str) and value.isdecimal())
                for value in values
            ):
                try:
                    source_date = date(*[int(str(value)) for value in values])
                except ValueError as exc:
                    raise CairnError(f"bibliography item {external} has an invalid date") from exc
    return str(external), title, authors, source_date


def _check_versions(
    ws: Workspace,
    items: list[dict[str, JsonValue]],
    fields: list[tuple[str, str, list[str], date | None]],
    library_alias: str,
    classification: str,
    processing: str,
    compartments: set[str],
    project_id: str | None,
) -> None:
    """Reject declared-version conflicts before capturing any part of the export."""
    existing: dict[tuple[str, str], str] = {}
    for _, record, _ in ws.records():
        meta = record.source
        if (
            meta is not None
            and meta.version is not None
            and record.domain == "research"
            and record.classification == classification
            and record.processing == processing
            and record.compartments == compartments
            and record.project_ids == ([project_id] if project_id else [])
        ):
            existing[(meta.identity, meta.version)] = meta.content_hash
    for item, (external, *_) in zip(items, fields, strict=True):
        version = item.get("version")
        if not isinstance(version, str):
            continue
        key = (f"bibliography-item:{library_alias}:{external}", version)
        if key in existing and existing[key] != digest(canonical(item)):
            raise Conflict(
                f"bibliography item {external} version {version} has different bytes; "
                "nothing was imported"
            )


def import_bibliography(
    ws: Workspace,
    file: Path,
    *,
    library_alias: str,
    scope_name: str,
    project_id: str | None = None,
) -> BibliographyImport:
    TypeAdapter(ID).validate_python(library_alias)
    data = read_source_file(file)
    items = TypeAdapter(list[dict[str, JsonValue]]).validate_python(read_json(data))
    if not items or len(items) > 10000:
        raise CairnError("bibliography export must contain 1–10000 items")
    fields = [bibliographic_fields(item) for item in items]
    if len({field[0] for field in fields}) != len(fields):
        raise CairnError("duplicate external IDs in bibliography export")
    with ws.lock():
        scope = ws.policy.scope(scope_name)
        if project_id:
            _, project, _ = ws.record(project_id, scope)
            if project.type != "project" or project.domain != "research":
                raise CairnError("bibliography imports require a research project")
            classification, processing, compartments = (
                project.classification,
                project.processing,
                project.compartments,
            )
        else:
            classification, processing, compartments = "private", "local_only", set()
        # Check the prospective source before recording anything.
        from cairn.records.models import Record, now

        probe = Record(
            id="concept_probe",
            type="concept",
            title="Scope check",
            domain="research",
            classification=classification,
            processing=processing,
            compartments=compartments,
            project_ids=[project_id] if project_id else [],
            created_at=now(),
            updated_at=now(),
        )
        scope.require(probe)
        _check_versions(
            ws, items, fields, library_alias, classification, processing, compartments, project_id
        )
    export = capture_bytes(
        ws,
        data,
        origin=file.name,
        domain="research",
        title="Selected bibliography export",
        identity=f"bibliography-export:{library_alias}",
        source_type="text",
        classification=classification,
        processing=processing,
        compartments=compartments,
        project_ids=[project_id] if project_id else [],
        scope_name=scope_name,
    )
    ids = []
    for item, (external, title, authors, source_date) in zip(items, fields, strict=True):
        version = item.get("version")
        citation = item.get("citation-key")
        source = capture_bytes(
            ws,
            canonical(item),
            origin=f"CSL-JSON:{library_alias}",
            domain="research",
            title=title,
            identity=f"bibliography-item:{library_alias}:{external}",
            source_type="bibliography",
            classification=classification,
            processing=processing,
            compartments=compartments,
            project_ids=[project_id] if project_id else [],
            external_id=external,
            citation_key=citation if isinstance(citation, str) else None,
            version=version if isinstance(version, str) else None,
            authors=authors,
            source_date=source_date,
            bibliography=item,
            library_alias=library_alias,
            scope_name=scope_name,
        )
        ids.append(source.id)
    result = BibliographyImport(
        library_alias=library_alias, export_source_id=export.id, item_source_ids=ids
    )
    with ws.lock(write=True):
        path = f"receipts/bibliography/{digest(canonical(result))}.json"
        if not ws.fs.exists(path):
            ws.fs.write(path, canonical(result), exclusive=True)
    return result
