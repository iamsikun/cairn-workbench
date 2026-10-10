"""Shared formatting for untrusted page drafts; never chooses authority or paths."""

from datetime import datetime

from cairn.records.models import Assertion, EvidenceRef, Labels, Record, canonical


def page_record(
    *,
    old: Record | None,
    record_id: str,
    record_type: str,
    title: str,
    labels: Labels,
    at: datetime,
    sources: list[EvidenceRef],
    assertions: list[Assertion],
    related: list[str] | None = None,
    project_ids: list[str] | None = None,
    aliases: list[str] | None = None,
    primary_source_id: str | None = None,
) -> Record:
    values = (
        old.model_dump()
        if old
        else {
            **labels.model_dump(),
            "id": record_id,
            "type": record_type,
            "created_at": at,
            "updated_at": at,
        }
    )
    values.update(
        title=title,
        updated_at=max(at, old.updated_at) if old else at,
        sources=list({canonical(r): r for r in [*(old.sources if old else []), *sources]}.values()),
        assertions=[*(old.assertions if old else []), *assertions],
    )
    for field, value in (
        ("related", related),
        ("project_ids", project_ids),
        ("aliases", aliases),
        ("primary_source_id", primary_source_id),
    ):
        if value is not None:
            values[field] = value
    return Record.model_validate(values)
