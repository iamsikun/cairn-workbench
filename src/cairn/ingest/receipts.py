from __future__ import annotations

from pathlib import Path

from cairn.adapters.protocol import Candidate, Result
from cairn.errors import CairnError, Denied
from cairn.ingest.service import capture_bytes, extract, read_source_file
from cairn.policies.models import require_inheritance
from cairn.proposals.models import Proposal
from cairn.proposals.service import check_reference, prepare_job, stage_result
from cairn.records.continuity import SessionReceipt
from cairn.records.json import read_json
from cairn.records.models import Assertion, EvidenceRef, Record, canonical, digest, now
from cairn.storage.workspace import Workspace


def import_receipt(
    ws: Workspace,
    file: Path,
    *,
    scope_name: str,
    inline_synthetic: bool = False,
) -> Proposal | None:
    data = read_source_file(file)
    receipt = SessionReceipt.model_validate(read_json(data))
    with ws.lock():
        _, project, _ = ws.record(receipt.project_id, ws.policy.scope(scope_name))
        if project.type != "project":
            raise CairnError("session receipt requires a project")
        entries = [
            *receipt.tried,
            *receipt.proposed_decisions,
            *receipt.failures,
            *receipt.unresolved,
            *([receipt.next_action] if receipt.next_action else []),
        ]
        refs = [*receipt.produced_evidence, *(ref for entry in entries for ref in entry.sources)]
        for ref in refs:
            check_reference(ws, ref, scope_name)
            _, cited, _ = ws.record(ref.id, ws.policy.scope(scope_name))
            require_inheritance(project, [cited])
        if 1 + len(receipt.proposed_decisions) > ws.policy.max_changes:
            raise CairnError("receipt decisions exceed proposal change budget")
    source = capture_bytes(
        ws,
        data,
        origin=file.name,
        domain=project.domain,
        title=f"Session receipt {receipt.session_id}",
        identity=f"session-receipt:{receipt.project_id}:{receipt.session_id}",
        source_type="receipt",
        version="1",
        classification=project.classification,
        processing=project.processing,
        compartments=project.compartments,
        project_ids=[project.id],
        scope_name=scope_name,
    )
    extract(ws, source.id, scope_name=scope_name, inline_synthetic=inline_synthetic)
    envelope = prepare_job(
        ws, source.id, scope_name=scope_name, related_ids=[project.id], provider="receipt-v1"
    )
    job = envelope.job
    project = job.related[0].record.model_copy(deep=True)
    if any(ref.id == source.id for ref in project.sources):
        return None

    def reference(locator: str) -> EvidenceRef:
        segment = next(s for s in job.extraction.segments if s.locator == locator)
        return EvidenceRef(
            id=source.id,
            source_hash=job.extraction.source_hash,
            evidence_hash=job.evidence_hash,
            locator=locator,
            quote=segment.text if len(segment.text) <= 10000 else None,
        )

    project.sources.append(reference("session metadata"))
    project.sources.extend(ref for ref in receipt.produced_evidence if ref not in project.sources)
    project.updated_at = now()
    # Repository claims remain unverified until compared with an owner-selected checkout.
    if receipt.repository:
        project.repository = receipt.repository
    roles = {"tried": "tried", "failures": "failed_approaches", "unresolved": "open_issues"}
    for field, role in roles.items():
        for i, entry in enumerate(getattr(receipt, field), 1):
            ref = reference(f"{field} {i}")
            project.assertions.append(
                Assertion.model_validate(
                    {
                        "id": "assert_" + digest(f"{source.id}:{field}:{i}".encode())[:32],
                        "text": entry.text,
                        "kind": "reported_result",
                        "context_role": role,
                        "sources": [ref, *entry.sources],
                        "verification": "unreviewed",
                        "rationale": "Session report; approval preserves provenance, not proof.",
                    }
                )
            )
    if receipt.next_action:
        # Keep previous next actions in history without presenting all as current.
        for assertion in project.assertions:
            if assertion.context_role == "next_action":
                assertion.verification = "superseded"
        project.assertions.append(
            Assertion(
                id="assert_" + digest(f"{source.id}:next_action".encode())[:32],
                text=receipt.next_action.text,
                kind="hypothesis",
                context_role="next_action",
                sources=[reference("next_action"), *receipt.next_action.sources],
            )
        )
    candidates = [
        Candidate(
            record=project,
            body=job.related[0].body,
            rationale="Append attributed session observations and unresolved work.",
        )
    ]
    for i, entry in enumerate(receipt.proposed_decisions, 1):
        ref = reference(f"proposed_decisions {i}")
        decision = Record(
            id="decision_" + digest(f"{source.id}:{i}".encode())[:32],
            type="decision",
            title=entry.text[:500],
            status="draft",
            domain=project.domain,
            classification=project.classification,
            processing=project.processing,
            compartments=project.compartments,
            project_ids=[project.id],
            created_at=source.created_at,
            updated_at=source.created_at,
            sources=[ref, *entry.sources],
            assertions=[
                Assertion(
                    id="assert_" + digest(f"{source.id}:decision:{i}".encode())[:32],
                    text=entry.text,
                    kind="hypothesis",
                    sources=[ref, *entry.sources],
                    rationale="Session proposal; separate explicit adoption is required.",
                )
            ],
        )
        candidates.append(
            Candidate(
                record=decision,
                body="",
                rationale="Preserve a proposed decision without adopting it.",
            )
        )
    return stage_result(
        ws,
        Result(
            job_id=job.id,
            input_hash=digest(canonical(job)),
            provider=job.provider,
            candidates=candidates,
        ),
    )


def adopt_decision(
    ws: Workspace,
    decision_id: str,
    *,
    scope_name: str,
    statement: str,
) -> Proposal | None:
    if not statement.strip():
        raise CairnError("adoption requires an owner rationale")
    with ws.lock():
        _, decision, _ = ws.record(decision_id, ws.policy.scope(scope_name))
        if decision.type != "decision" or not decision.sources or not decision.assertions:
            raise Denied("adoption requires a sourced decision proposal")
    envelope = prepare_job(
        ws,
        decision.sources[0].id,
        scope_name=scope_name,
        related_ids=[decision_id],
        provider="owner-adoption-v1",
    )
    job = envelope.job
    decision = job.related[0].record.model_copy(deep=True)
    decision.status = "active"
    decision.updated_at = now()
    for assertion in decision.assertions:
        assertion.kind = "owner_decision"
        assertion.verification = "reviewed"
        assertion.rationale = statement
    decision.sections["owner_adoption"] = statement
    return stage_result(
        ws,
        Result(
            job_id=job.id,
            input_hash=digest(canonical(job)),
            provider=job.provider,
            candidates=[
                Candidate(
                    record=decision,
                    body=job.related[0].body,
                    rationale="Explicit owner adoption; still requires sealed approval and apply.",
                )
            ],
        ),
    )
