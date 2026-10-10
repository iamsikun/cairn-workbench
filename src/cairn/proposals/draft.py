"""Draft packets: the owner's agent drafts pages from one source; Cairn validates.

`begin` seals an ingest job (source extraction, scoped related pages, change budget)
for a granted cloud route and records the export before any bytes leave. `finish`
treats the agent's `Result` as untrusted, refuses owner-only states, and stages it
through the ordinary proposal checks. Approval and apply remain owner operations.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from cairn.adapters.protocol import Candidate, Job, Result
from cairn.errors import Conflict, Denied
from cairn.ingest.service import extract, read_source_file
from cairn.presentation.service import output_bytes
from cairn.presentation.writing_models import ExportReceipt
from cairn.proposals.models import DraftReceipt, JobEnvelope
from cairn.proposals.service import (
    authorize_export,
    load_job,
    prepare_job,
    review_flags,
    stage_result,
    validate,
)
from cairn.records.models import canonical, digest, now
from cairn.storage.workspace import Workspace

PREFIX = "receipts/drafts"
CONTRACT = Path(__file__).with_name("contract.md")
OWNER_ONLY = {"owner_adoption", "verification_change"}


def guidance() -> str:
    return CONTRACT.read_text()


def check_export(ws: Workspace, job: Job) -> ExportReceipt:
    """The packet's export receipt still matches and its grant still applies."""
    if not job.id.startswith("job_draft_") or job.route != "cloud":
        raise Denied("not a draft packet")
    receipt = ExportReceipt.model_validate_json(ws.fs.read(f"{PREFIX}/exports/{job.id}.json"))
    if (
        receipt.job_id != job.id
        or receipt.input_hash != digest(canonical(job))
        or receipt.policy_hash != job.policy_hash
        or receipt.provider != job.provider
    ):
        raise Conflict("draft export binding changed")
    if job.policy_hash != ws.policy_hash:
        raise Conflict("policy changed; prepare a new draft packet")
    authorize_export(ws, job, receipt.destination)
    return receipt


def check_proposal_binding(ws: Workspace, job: Job) -> None:
    check_export(ws, job)


def begin(
    ws: Workspace,
    source_id: str,
    output: Path | None,
    *,
    scope_name: str,
    provider: str,
    destination: str,
    related_ids: list[str] | None = None,
    inline_synthetic: bool = False,
    attempt: str | None = None,
) -> dict[str, str]:
    extract(ws, source_id, scope_name=scope_name, inline_synthetic=inline_synthetic)
    envelope = prepare_job(
        ws,
        source_id,
        scope_name=scope_name,
        related_ids=related_ids,
        provider=provider,
        destination=destination,
        attempt=attempt,
    )
    job = envelope.job
    input_hash = digest(canonical(job))
    with ws.lock(write=True):
        export_path = f"{PREFIX}/exports/{job.id}.json"
        if ws.fs.exists(export_path):
            if check_export(ws, job).destination != destination:
                raise Conflict("draft packet was already exported to another destination")
        else:
            authorize_export(ws, job, destination)
            ws.fs.write(
                export_path,
                canonical(
                    ExportReceipt(
                        job_id=job.id,
                        input_hash=input_hash,
                        policy_hash=job.policy_hash,
                        provider=provider,
                        destination=destination,
                        at=now(),
                    )
                ),
                exclusive=True,
            )
        if output is None:
            return {"job_id": job.id, "source_id": job.source.id, "input_hash": input_hash}
        payload = canonical(
            {
                "packet": job,
                "input_hash": input_hash,
                "guidance": guidance(),
                "response_schema": Result.model_json_schema(),
            }
        )
        output_bytes(ws, output, payload)
    return {
        "job_id": job.id,
        "source_id": job.source.id,
        "input_hash": input_hash,
        "path": str(output.absolute()),
    }


def finish(ws: Workspace, file: Path) -> DraftReceipt:
    return finish_bytes(ws, read_source_file(file))


def submit(
    ws: Workspace,
    source_id: str,
    candidates: list[Candidate],
    *,
    scope_name: str,
    provider: str,
    destination: str,
    related_ids: list[str] | None = None,
    warnings: list[str] | None = None,
    inline_synthetic: bool = False,
) -> DraftReceipt:
    """Seal the source and chosen related pages, then stage the agent's pages."""
    sealed = begin(
        ws,
        source_id,
        None,
        scope_name=scope_name,
        provider=provider,
        destination=destination,
        related_ids=related_ids or [],
        inline_synthetic=inline_synthetic,
        attempt=digest(canonical({"candidates": candidates, "warnings": warnings or []})),
    )
    result = Result(
        job_id=sealed["job_id"],
        input_hash=sealed["input_hash"],
        provider=provider,
        candidates=candidates,
        warnings=warnings or [],
    )
    return finish_bytes(ws, canonical(result))


def finish_bytes(ws: Workspace, raw: bytes) -> DraftReceipt:
    result = Result.model_validate_json(raw)
    checksum = digest(raw)
    receipt_path = f"{PREFIX}/finished/{result.job_id}.json"
    with ws.lock(write=True):
        job = load_job(ws, result.job_id).job
        check_export(ws, job)
        if result.input_hash != digest(canonical(job)) or result.provider != job.provider:
            raise Denied("draft does not match its prepared packet")
        if ws.fs.exists(receipt_path):
            existing = DraftReceipt.model_validate_json(ws.fs.read(receipt_path))
            if existing.response_hash != checksum:
                raise Conflict("draft packet already finished with a different response")
            return existing
        current = {record.id: record for _, record, _ in ws.records()}
        for candidate in result.candidates:
            flags = review_flags(candidate.record, current.get(candidate.record.id))
            if flags & OWNER_ONLY:
                raise Denied("drafts cannot adopt decisions or mark evidence reviewed")
        response_path = f"{PREFIX}/responses/{job.id}.json"
        if ws.fs.exists(response_path) and digest(ws.fs.read(response_path)) != checksum:
            raise Conflict("draft packet already preserved a different response")
        if not ws.fs.exists(response_path):
            ws.fs.write(response_path, raw, exclusive=True)
    proposal = stage_result(ws, result)
    if proposal is not None:
        validate(ws, proposal.id)
    receipt = DraftReceipt(
        job_id=job.id,
        response_hash=checksum,
        proposal_id=proposal.id if proposal else None,
        workflow_stage="validated" if proposal else "unchanged",
    )
    with ws.lock(write=True):
        if ws.fs.exists(receipt_path):
            existing = DraftReceipt.model_validate_json(ws.fs.read(receipt_path))
            if existing != receipt:
                raise Conflict("concurrent draft handoff differs")
            return existing
        ws.fs.write(receipt_path, canonical(receipt), exclusive=True)
    return receipt


def validate_drafts(payloads: Mapping[str, bytes]) -> None:
    """Restore-time checks that every draft artifact binds to its sealed job."""
    for path, raw in payloads.items():
        if not path.startswith(f"{PREFIX}/"):
            continue
        category, name = path.removeprefix(f"{PREFIX}/").split("/", 1)
        job_id = name.removesuffix(".json")
        job_raw = payloads.get(f"proposals/jobs/{job_id}.json")
        if job_raw is None:
            raise Conflict("saved draft artifact has no job")
        job = JobEnvelope.model_validate_json(job_raw).job
        if category == "exports":
            exported = ExportReceipt.model_validate_json(raw)
            if exported.job_id != job_id or exported.input_hash != digest(canonical(job)):
                raise Conflict("saved draft export mismatch")
        elif category == "responses":
            if Result.model_validate_json(raw).job_id != job_id:
                raise Conflict("saved draft response mismatch")
        elif category == "finished":
            receipt = DraftReceipt.model_validate_json(raw)
            response = payloads.get(f"{PREFIX}/responses/{job_id}.json")
            if (
                receipt.job_id != job_id
                or response is None
                or digest(response) != receipt.response_hash
                or (
                    receipt.proposal_id is not None
                    and f"proposals/{receipt.proposal_id}.json" not in payloads
                )
            ):
                raise Conflict("saved draft handoff binding mismatch")
        else:
            raise Conflict("unknown saved draft artifact")
