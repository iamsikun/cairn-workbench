from __future__ import annotations

from pathlib import Path

from cairn.adapters.protocol import Candidate, Result
from cairn.ingest.service import capture_bytes, extract, read_source_file
from cairn.policies.models import require_inheritance
from cairn.proposals.models import Proposal
from cairn.proposals.service import check_reference, prepare_job, stage_result
from cairn.records.domains import LifeDossier
from cairn.records.json import read_json
from cairn.records.models import Assertion, EvidenceRef, Labels, Period, Record, canonical, digest
from cairn.storage.workspace import Workspace


def import_dossier(
    ws: Workspace, file: Path, *, scope_name: str, inline_synthetic: bool = False
) -> Proposal | None:
    data = read_source_file(file)
    dossier = LifeDossier.model_validate(read_json(data))
    refs = [
        *dossier.authoritative_documents,
        *dossier.procedures,
        *(ref for event in dossier.service_history for ref in event.sources),
        *(ref for term in dossier.terms for ref in term.sources),
    ]
    with ws.lock():
        scope = ws.policy.scope(scope_name)
        labels = Labels(domain="life")
        for ref in refs:
            check_reference(ws, ref, scope_name)
            _, cited, _ = ws.record(ref.id, scope)
            require_inheritance(labels, [cited])
    source = capture_bytes(
        ws,
        data,
        origin=file.name,
        domain="life",
        title=dossier.title,
        identity=f"life-dossier:{dossier.entity_alias}",
        source_type="life_dossier",
        scope_name=scope_name,
    )
    extract(ws, source.id, scope_name=scope_name, inline_synthetic=inline_synthetic)
    record_id = "entity_" + digest(dossier.entity_alias.encode())[:32]
    with ws.lock():
        existing = next((r for _, r, _ in ws.records(scope) if r.id == record_id), None)
    envelope = prepare_job(
        ws,
        source.id,
        scope_name=scope_name,
        related_ids=[record_id] if existing else [],
        provider="life-dossier-v1",
    )
    job = envelope.job

    def reference(locator: str) -> EvidenceRef:
        return EvidenceRef(
            id=source.id,
            source_hash=job.extraction.source_hash,
            evidence_hash=job.evidence_hash,
            locator=locator,
        )

    assertions = []
    for i, event in enumerate(dossier.service_history, 1):
        assertions.append(
            Assertion(
                id="assert_" + digest(f"{source.id}:event:{i}".encode())[:32],
                text=event.description,
                kind="reported_result",
                period=Period(as_of=event.date),
                sources=[reference(f"service event {i}"), *event.sources],
            )
        )
    for i, term in enumerate(dossier.terms, 1):
        assertions.append(
            Assertion(
                id="assert_" + digest(f"{source.id}:term:{i}".encode())[:32],
                text=f"{term.kind}: {term.description}",
                kind="reported_result",
                period=Period(valid_until=term.date),
                sources=[reference(f"term {i}"), *term.sources],
            )
        )
    previous = job.related[0].record if job.related else None
    if previous:
        # Append source-backed history; a later dossier cannot erase earlier service
        # events or decisions. Conflicting terms remain visible for explicit review.
        assertions = [
            *previous.assertions,
            *(a for a in assertions if a.id not in {old.id for old in previous.assertions}),
        ]
        refs = [*previous.sources, *(r for r in refs if r not in previous.sources)]
    record = (
        previous.model_copy(deep=True)
        if previous
        else Record(
            id=record_id,
            type="entity",
            title=dossier.title,
            domain="life",
            aliases=[dossier.entity_alias],
            created_at=source.created_at,
            updated_at=source.created_at,
        )
    )
    record.title = dossier.title
    record.updated_at = source.created_at
    record.review_date = dossier.review_date
    record.assertions = assertions
    record.sections["entity_kind"] = dossier.entity_kind
    record.sections["reminders"] = (
        "Review-date metadata only; external calendar/task systems remain authoritative."
    )
    record.sources = [*refs, reference("entity metadata")]
    if previous and any(r.id == source.id for r in previous.sources):
        return None
    return stage_result(
        ws,
        Result(
            job_id=job.id,
            input_hash=digest(canonical(job)),
            provider=job.provider,
            candidates=[
                Candidate(
                    record=record,
                    body=job.related[0].body if previous else "",
                    rationale="Preserve dated history, source documents and terms; no scheduling.",
                )
            ],
        ),
    )
