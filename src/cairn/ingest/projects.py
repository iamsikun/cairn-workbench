from __future__ import annotations

from cairn.adapters.protocol import Candidate, Result
from cairn.errors import CairnError
from cairn.ingest.service import capture_bytes, extract
from cairn.proposals.models import Proposal
from cairn.proposals.service import prepare_job, stage_result
from cairn.records.models import EvidenceRef, Record, canonical, digest, new_id
from cairn.storage.workspace import Workspace


def create_project(
    ws: Workspace,
    *,
    title: str,
    question: str,
    objective: str,
    constraints: str,
    scope_name: str,
    inline_synthetic: bool = False,
) -> Proposal:
    if not all(value.strip() for value in (title, question, objective, constraints)):
        raise CairnError("project framing fields cannot be empty")
    project_id = new_id("project")
    framing = {"question": question, "objective": objective, "constraints": constraints}
    source = capture_bytes(
        ws,
        canonical(framing),
        origin="owner-project-framing.json",
        domain="research",
        title=title,
        identity=f"project-framing:{project_id}",
        source_type="text",
        scope_name=scope_name,
    )
    extract(ws, source.id, scope_name=scope_name, inline_synthetic=inline_synthetic)
    envelope = prepare_job(
        ws, source.id, scope_name=scope_name, related_ids=[], provider="owner-project-v1"
    )
    job = envelope.job
    reference = EvidenceRef(
        id=source.id,
        source_hash=job.extraction.source_hash,
        evidence_hash=job.evidence_hash,
        locator="line 1",
    )
    project = Record(
        id=project_id,
        type="project",
        title=title,
        domain="research",
        created_at=source.created_at,
        updated_at=source.created_at,
        status="active",
        sections=framing,
        sources=[reference],
    )
    proposal = stage_result(
        ws,
        Result(
            job_id=job.id,
            input_hash=digest(canonical(job)),
            provider=job.provider,
            candidates=[
                Candidate(
                    record=project,
                    body="",
                    rationale="Owner-supplied project framing; no generated conclusions.",
                )
            ],
        ),
    )
    assert proposal is not None
    return proposal
