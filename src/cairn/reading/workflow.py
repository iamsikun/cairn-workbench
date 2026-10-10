"""Owner packet boundary for automatic Finch capture, staging and validation."""

from __future__ import annotations

import base64
from pathlib import Path

from pydantic import TypeAdapter

from cairn.adapters.protocol import Candidate, Job, Page, Result
from cairn.errors import Conflict, Denied
from cairn.ingest.service import capture_bytes, extract, load_extraction, read_source_file
from cairn.policies.models import LEVEL
from cairn.presentation.service import output_bytes
from cairn.presentation.writing_models import ExportReceipt
from cairn.proposals.models import JobEnvelope
from cairn.proposals.service import check_reference, stage_result, validate
from cairn.reading.contract import guidance, guidance_hash
from cairn.reading.models import FinchGuard, FinchPacket, FinchReceipt, FinchResponse
from cairn.records.models import (
    ID,
    Assertion,
    EvidenceRef,
    Labels,
    Processing,
    Record,
    canonical,
    digest,
    now,
)
from cairn.storage.workspace import Workspace

PREFIX = "receipts/finch"


def identity(packet: FinchPacket) -> str:
    value = packet.model_dump(mode="json")
    value["id"] = "finch_pending"
    return "finch_" + digest(canonical(value))[:32]


def packet_path(session_id: str) -> str:
    TypeAdapter(ID).validate_python(session_id)
    return f"{PREFIX}/jobs/{session_id}.json"


def authorize(ws: Workspace, packet: FinchPacket) -> None:
    scope = ws.policy.scope(packet.scope)
    for operation in ("generation", "client_export"):
        ws.policy.authorize_route(
            scope,
            [packet.source, *(p.record for p in packet.related)],
            route="cloud",
            provider=packet.provider,
            destination=packet.destination,
            operation=operation,
            question=packet.request_labels,
        )


def load_packet(ws: Workspace, session_id: str) -> FinchPacket:
    packet = FinchPacket.model_validate_json(ws.fs.read(packet_path(session_id)))
    if packet.id != session_id or identity(packet) != session_id:
        raise Denied("Finch packet identity mismatch")
    if packet.policy_hash != ws.policy_hash or packet.guidance_hash != guidance_hash():
        raise Conflict("Finch policy or guidance changed; prepare a new packet")
    guard_raw = ws.fs.read(f"{PREFIX}/guards/{session_id}.json")
    if digest(guard_raw) != packet.guard_hash:
        raise Conflict("Finch owner guard changed")
    guard = FinchGuard.model_validate_json(guard_raw)
    for path, checksum in {**packet.input_hashes, **guard.protected_hashes}.items():
        if not ws.fs.exists(path) or digest(ws.fs.read(path)) != checksum:
            raise Conflict("Finch evidence, context or human notes changed")
    extraction, key = load_extraction(ws, packet.source)
    if key != packet.evidence_hash or canonical(extraction) != canonical(packet.extraction):
        raise Conflict("Finch paper extraction changed")
    authorize(ws, packet)
    return packet


def check_export(ws: Workspace, session_id: str) -> FinchPacket:
    packet = load_packet(ws, session_id)
    receipt = ExportReceipt.model_validate_json(ws.fs.read(f"{PREFIX}/exports/{session_id}.json"))
    if (
        receipt.input_hash != digest(canonical(packet))
        or receipt.job_id != packet.id
        or receipt.policy_hash != packet.policy_hash
        or receipt.provider != packet.provider
        or receipt.destination != packet.destination
    ):
        raise Conflict("Finch export binding changed")
    return packet


def begin(
    ws: Workspace,
    source_id: str,
    output: Path,
    *,
    scope_name: str,
    request: str,
    request_labels: Labels | None,
    provider: str,
    destination: str,
    related_ids: list[str] | None = None,
    inline_synthetic: bool = False,
) -> dict[str, str]:
    extract(ws, source_id, scope_name=scope_name, inline_synthetic=inline_synthetic)
    with ws.lock(write=True):
        scope = ws.policy.scope(scope_name)
        source_path, source, _ = ws.record(source_id, scope)
        if source.domain != "research":
            raise Denied("Finch requires selected research evidence")
        extraction, key = load_extraction(ws, source)
        if extraction.coverage == "failed" or not extraction.segments:
            raise Denied("Finch has no extractable evidence")
        related = [ws.record(i, scope) for i in (related_ids or [])]
        inputs = {source_path: digest(ws.fs.read(source_path)), f"evidence/{key}.json": key}
        inputs.update({path: digest(ws.fs.read(path)) for path, _, _ in related})
        guard_raw = canonical(FinchGuard(protected_hashes=ws.protected_hashes()))
        packet = FinchPacket(
            id="finch_pending",
            source=source,
            extraction=extraction,
            evidence_hash=key,
            related=[Page(record=record, body=body) for _, record, body in related],
            scope=scope_name,
            policy_hash=ws.policy_hash,
            input_hashes=inputs,
            guard_hash=digest(guard_raw),
            request=request,
            request_labels=request_labels or Labels(domain="research", classification="restricted"),
            provider=provider,
            destination=destination,
            guidance_hash=guidance_hash(),
        )
        authorize(ws, packet)
        packet.id = identity(packet)
        guard_path = f"{PREFIX}/guards/{packet.id}.json"
        if not ws.fs.exists(guard_path):
            ws.fs.write(guard_path, guard_raw, exclusive=True)
        job_path = packet_path(packet.id)
        if not ws.fs.exists(job_path):
            ws.fs.write(job_path, canonical(packet), exclusive=True)
        export_path = f"{PREFIX}/exports/{packet.id}.json"
        if not ws.fs.exists(export_path):
            ws.fs.write(
                export_path,
                canonical(
                    ExportReceipt(
                        job_id=packet.id,
                        input_hash=digest(canonical(packet)),
                        policy_hash=packet.policy_hash,
                        provider=provider,
                        destination=destination,
                        at=now(),
                    )
                ),
                exclusive=True,
            )
        assert source.source is not None
        payload = canonical(
            {
                "packet": packet,
                "input_hash": digest(canonical(packet)),
                "guidance": guidance(),
                "source_bytes_base64": base64.b64encode(ws.fs.read(source.source.blob)).decode(),
                "response_schema": FinchResponse.model_json_schema(),
            }
        )
        output_bytes(ws, output, payload)
    return {
        "session_id": packet.id,
        "source_id": source.id,
        "input_hash": digest(canonical(packet)),
        "path": str(output.absolute()),
    }


def finish(ws: Workspace, file: Path, *, inline_synthetic: bool = False) -> FinchReceipt:
    raw = read_source_file(file)
    response = FinchResponse.model_validate_json(raw)
    checksum = digest(raw)
    receipt_path = f"{PREFIX}/imports/{response.session_id}.json"
    with ws.lock(write=True):
        packet = check_export(ws, response.session_id)
        if response.input_hash != digest(canonical(packet)):
            raise Denied("Finch response does not match its prepared packet")
        for claim in response.claims:
            for ref in claim.sources:
                if ref.id != packet.source.id:
                    raise Denied("Finch claim cites evidence outside the selected paper")
                check_reference(ws, ref, packet.scope)
        if ws.fs.exists(receipt_path):
            receipt = FinchReceipt.model_validate_json(ws.fs.read(receipt_path))
            if receipt.response_hash != checksum:
                raise Conflict("Finch session already imported different response bytes")
            return receipt
        response_path = f"{PREFIX}/responses/{response.session_id}.json"
        if ws.fs.exists(response_path) and digest(ws.fs.read(response_path)) != checksum:
            raise Conflict("Finch session already preserved different response bytes")
        if not ws.fs.exists(response_path):
            ws.fs.write(response_path, raw, exclusive=True)
        labels = [packet.source, packet.request_labels, *(p.record for p in packet.related)]
        classification = max((label.classification for label in labels), key=LEVEL.__getitem__)
        processing: Processing = (
            "local_only"
            if any(label.processing == "local_only" for label in labels)
            else "cloud_eligible"
        )
        compartments = set().union(*(label.compartments | {label.domain} for label in labels)) - {
            "research"
        }
        project_ids = list(
            dict.fromkeys(
                [
                    *packet.source.project_ids,
                    *(p.record.id for p in packet.related if p.record.type == "project"),
                ]
            )
        )
    source = capture_bytes(
        ws,
        raw,
        origin=f"finch:{packet.id}",
        domain="research",
        title=f"Finch discussion: {packet.source.title}"[:500],
        identity=f"finch-session:{packet.id}",
        source_type="conversation",
        version=checksum,
        classification=classification,
        processing=processing,
        compartments=compartments,
        project_ids=project_ids,
        scope_name=packet.scope,
    )
    extract(ws, source.id, scope_name=packet.scope, inline_synthetic=inline_synthetic)
    with ws.lock(write=True):
        packet = check_export(ws, packet.id)
        source_path, source, _ = ws.record(source.id, ws.policy.scope(packet.scope))
        extraction, key = load_extraction(ws, source)
        if extraction.coverage == "failed":
            raise Denied("Finch discussion has no extractable messages")
        inputs = {
            **packet.input_hashes,
            f"{PREFIX}/guards/{packet.id}.json": packet.guard_hash,
            packet_path(packet.id): digest(ws.fs.read(packet_path(packet.id))),
            f"{PREFIX}/exports/{packet.id}.json": digest(
                ws.fs.read(f"{PREFIX}/exports/{packet.id}.json")
            ),
            response_path: checksum,
            source_path: digest(ws.fs.read(source_path)),
            f"evidence/{key}.json": key,
        }
        job = Job(
            id="job_finch_" + packet.id.removeprefix("finch_"),
            policy_hash=packet.policy_hash,
            scope_name=packet.scope,
            route="cloud",
            provider="finch-v0.2.0",
            source=source,
            extraction=extraction,
            evidence_hash=key,
            related=[Page(record=packet.source, body=""), *packet.related],
            max_changes=1,
        )
        envelope = JobEnvelope(
            job=job,
            scope=ws.policy.scope(packet.scope),
            input_hashes=inputs,
            protected_hashes=ws.protected_hashes(),
        )
        envelope_path = f"proposals/jobs/{job.id}.json"
        if not ws.fs.exists(envelope_path):
            ws.fs.write(envelope_path, canonical(envelope), exclusive=True)
        else:
            existing = JobEnvelope.model_validate_json(ws.fs.read(envelope_path))
            if canonical(existing.job) != canonical(job):
                raise Conflict("Finch proposal job changed")
            envelope = existing
        session_refs = [
            EvidenceRef(
                id=source.id,
                source_hash=extraction.source_hash,
                evidence_hash=key,
                locator=segment.locator,
            )
            for segment in extraction.segments
        ]
        paper_ref = EvidenceRef(
            id=packet.source.id,
            source_hash=packet.extraction.source_hash,
            evidence_hash=packet.evidence_hash,
            locator=packet.extraction.segments[0].locator,
        )
        record = Record(
            id="concept_finch_" + packet.id.removeprefix("finch_"),
            type="concept",
            title=f"Finch reading: {packet.source.title}"[:500],
            domain="research",
            classification=classification,
            processing=processing,
            compartments=compartments,
            project_ids=project_ids,
            created_at=source.created_at,
            updated_at=source.created_at,
            sources=[paper_ref, *session_refs],
            assertions=[
                Assertion(
                    id=f"assert_finch_{packet.id.removeprefix('finch_')}_{i}",
                    text=claim.text,
                    kind=claim.kind,
                    sources=claim.sources,
                    rationale="Finch interpretation; unreviewed and not independent evidence",
                )
                for i, claim in enumerate(response.claims)
            ],
        )
        body = "# Unreviewed Finch reading\n\n" + response.summary + "\n\n"
        body += f"Source coverage: {packet.extraction.coverage}; "
        body += "manual processing and message authorship are unverified.\n\n"
        for title, entries in (
            ("Limitations", response.limitations),
            ("Unresolved", response.unresolved),
        ):
            if entries:
                body += f"## {title}\n\n" + "\n".join(f"- {text}" for text in entries) + "\n\n"
        result = Result(
            job_id=job.id,
            input_hash=digest(canonical(job)),
            provider=job.provider,
            candidates=[
                Candidate(
                    record=record,
                    body=body,
                    rationale="Automatic Finch handoff; owner review required",
                )
            ],
        )
    proposal = stage_result(ws, result)
    if proposal is None:
        raise Conflict("Finch handoff did not stage a proposal")
    validate(ws, proposal.id)
    receipt = FinchReceipt(
        session_id=packet.id, response_hash=checksum, source_id=source.id, proposal_id=proposal.id
    )
    with ws.lock(write=True):
        check_export(ws, packet.id)
        if ws.fs.exists(receipt_path):
            existing_receipt = FinchReceipt.model_validate_json(ws.fs.read(receipt_path))
            if existing_receipt != receipt:
                raise Conflict("Finch concurrent handoff differs")
            return existing_receipt
        ws.fs.write(receipt_path, canonical(receipt), exclusive=True)
    return receipt


def check_proposal_binding(ws: Workspace, job: Job) -> None:
    packet = check_export(ws, "finch_" + job.id.removeprefix("job_finch_"))
    if (
        job.policy_hash != packet.policy_hash
        or job.route != "cloud"
        or job.provider != "finch-v0.2.0"
    ):
        raise Denied("Finch proposal route binding mismatch")
