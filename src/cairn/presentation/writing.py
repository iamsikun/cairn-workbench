"""Owner-managed writing packets. Returned prose and actor labels have no authority."""

from __future__ import annotations

from pathlib import Path

from cairn.errors import Blocked, Conflict, Denied
from cairn.ingest.service import capture_bytes, extract, read_source_file
from cairn.presentation.models import ViewBlock, ViewSection
from cairn.presentation.render import document, run_renderer
from cairn.presentation.service import load_view, output_bytes, recheck, remember
from cairn.presentation.writing_models import (
    ExplanationAnswer,
    ExplanationResponse,
    ExportReceipt,
    Feedback,
    FeedbackReceipt,
    WritingJob,
)
from cairn.records.models import Labels, canonical, digest, now
from cairn.storage.workspace import Workspace

PREFIX = "receipts/presentation"


def job_identity(job: WritingJob) -> str:
    value = job.model_dump(mode="json")
    value["id"] = "writing_pending"
    return "writing_" + digest(canonical(value))[:32]


CONTRACT = Path(__file__).with_name("contract.md")


def guidance() -> str:
    """Cairn's writing contract; how to write is the owner's agent's own business."""
    return CONTRACT.read_text()


def prepare(
    ws: Workspace,
    view_id: str,
    *,
    provider: str,
    route: str = "local",
    destination: str = "local",
    request: str = "",
    request_labels: Labels | None = None,
) -> WritingJob:
    bundle = load_view(ws, view_id)
    remember(ws, bundle, save=True)
    instructions = guidance()
    labels = request_labels or Labels(
        domain=bundle.domain,
        classification="restricted" if request else "public",
        processing="local_only" if request else "cloud_eligible",
    )
    job = WritingJob.model_validate(
        {
            "id": "writing_pending",
            "purpose": "explanation",
            "bundle": bundle,
            "request": request or "Explain the supplied evidence for the reader's question.",
            "request_labels": labels,
            "guidance": instructions,
            "guidance_hash": digest(instructions.encode()),
            "route": route,
            "provider": provider,
            "destination": destination,
        }
    )
    return _save_job(ws, job)


def _save_job(ws: Workspace, job: WritingJob) -> WritingJob:
    job.id = job_identity(job)
    with ws.lock(write=True):
        recheck(ws, job.bundle)
        path = f"{PREFIX}/jobs/{job.id}.json"
        if not ws.fs.exists(path):
            ws.fs.write(path, canonical(job), exclusive=True)
    return job


def load_job(ws: Workspace, job_id: str) -> WritingJob:
    from pydantic import TypeAdapter

    from cairn.records.models import ID

    TypeAdapter(ID).validate_python(job_id)
    job = WritingJob.model_validate_json(ws.fs.read(f"{PREFIX}/jobs/{job_id}.json"))
    if job.id != job_id or job_identity(job) != job_id:
        raise Denied("writing job identity mismatch")
    recheck(ws, job.bundle)
    return job


def authorize_export(ws: Workspace, job: WritingJob) -> None:
    if job.route != "cloud":
        raise Blocked(
            "manual packets cannot establish local execution; use a reviewed local adapter"
        )
    scope = ws.policy.scope(job.bundle.scope)
    records = [ws.record(k, scope)[1] for k in job.bundle.record_ids]
    # Include feedback and revision pages, not merely the original rendered view.
    if job.revision:
        from cairn.proposals.service import _check_inputs
        from cairn.proposals.service import load_job as load_revision

        envelope = load_revision(ws, job.revision.id)
        if canonical(envelope.job) != canonical(job.revision):
            raise Denied("revision job binding mismatch")
        _check_inputs(ws, envelope)
        records.extend([job.revision.source, *(p.record for p in job.revision.related)])
    for operation in ("generation", "client_export"):
        ws.policy.authorize_route(
            scope,
            [*records, job.bundle],
            route="cloud",
            provider=job.provider,
            destination=job.destination,
            operation=operation,
            question=job.request_labels,
        )


def export_packet(ws: Workspace, job_id: str, output: Path | None) -> dict[str, str]:
    with ws.lock(write=True):
        job = load_job(ws, job_id)
        authorize_export(ws, job)
        if job.purpose != "explanation":
            raise Denied("revision packets are retired; use cairn write --feedback")
        response = ExplanationResponse
        doc = document(job.bundle)
        payload = canonical(
            {
                "job": job,
                "input_hash": digest(canonical(job)),
                "response_schema": response.model_json_schema(),
                "document": doc,
                "document_hash": digest(canonical(doc)),
            }
        )
        receipt = ExportReceipt(
            job_id=job.id,
            input_hash=digest(canonical(job)),
            policy_hash=ws.policy_hash,
            provider=job.provider,
            destination=job.destination,
            at=now(),
        )
        # Record export intent before releasing any bytes. A missing output can be retried;
        # a file reaching an agent is never mistaken for a proven execution receipt.
        ws.fs.write(f"{PREFIX}/exports/{job.id}.json", canonical(receipt))
        if output is not None:
            output_bytes(ws, output, payload)
    return {"job_id": job.id, "path": str(output), "input_hash": digest(canonical(job))}


def _returned(ws: Workspace, job_id: str, input_hash: str) -> WritingJob:
    job = load_job(ws, job_id)
    if input_hash != digest(canonical(job)):
        raise Denied("response does not match sealed writing job")
    authorize_export(ws, job)
    path = f"{PREFIX}/exports/{job.id}.json"
    if not ws.fs.exists(path):
        raise Denied("writing packet was not exported through the owner boundary")
    exported = ExportReceipt.model_validate_json(ws.fs.read(path))
    if exported.input_hash != input_hash or exported.policy_hash != ws.policy_hash:
        raise Conflict("writing export is stale")
    return job


def validate_explanation(job: WritingJob, response: ExplanationResponse) -> None:
    if job.purpose != "explanation":
        raise Denied("response kind does not match writing job")
    evidence = {e.key: e for e in job.bundle.evidence if not e.support.startswith("Unsupported")}
    for block in response.blocks:
        if any(k not in evidence for k in block.evidence_keys):
            raise Denied("explanation cites unavailable evidence")
        for quote in block.quotations:
            if quote.text not in evidence[quote.evidence_key].text:
                raise Denied("explanation quote is not present in supplied evidence")


def import_explanation(ws: Workspace, file: Path) -> ExplanationResponse:
    return import_explanation_bytes(ws, read_source_file(file))


def submit_explanation(
    ws: Workspace,
    view_id: str,
    answer: ExplanationAnswer,
    *,
    request: str,
    request_labels: Labels,
    provider: str,
    destination: str,
) -> dict[str, str]:
    """Seal a saved view for the owner's agent and keep its unreviewed explanation."""
    job = prepare(
        ws,
        view_id,
        provider=provider,
        route="cloud",
        destination=destination,
        request=request,
        request_labels=request_labels,
    )
    sealed = export_packet(ws, job.id, None)
    response = ExplanationResponse(
        job_id=job.id, input_hash=sealed["input_hash"], **dict(answer)
    )
    import_explanation_bytes(ws, canonical(response))
    return {"job_id": job.id, "explanation": digest(canonical(response))}


def stored_explanation(ws: Workspace, job_id: str, key: str | None = None) -> ExplanationResponse:
    """A kept explanation for a writing job; name its digest when there are several."""
    from pydantic import TypeAdapter

    from cairn.records.models import ID

    TypeAdapter(ID).validate_python(job_id)
    with ws.lock():
        paths = [
            path
            for path in ws.fs.files(f"{PREFIX}/explanations")
            if path.rsplit("/", 1)[-1].startswith(f"{job_id}-")
            and (key is None or path.endswith(f"-{key}.json"))
        ]
        if len(paths) != 1:
            raise Conflict(f"{len(paths)} matching explanations; name one with --digest")
        return ExplanationResponse.model_validate_json(ws.fs.read(paths[0]))


def import_explanation_bytes(ws: Workspace, raw: bytes) -> ExplanationResponse:
    response = ExplanationResponse.model_validate_json(raw)
    with ws.lock(write=True):
        job = _returned(ws, response.job_id, response.input_hash)
        validate_explanation(job, response)
        key = digest(canonical(response))
        path = f"{PREFIX}/explanations/{job.id}-{key}.json"
        if not ws.fs.exists(path):
            ws.fs.write(path, canonical(response), exclusive=True)
    return response


def explanation_html(
    ws: Workspace, response: ExplanationResponse, output: Path, *, inline_synthetic: bool = False
) -> dict[str, str]:
    from cairn.adapters.legacy import retired

    if not (inline_synthetic and ws.config.synthetic):
        retired("Legacy explanation HTML worker")
    with ws.lock():
        job = _returned(ws, response.job_id, response.input_hash)
        validate_explanation(job, response)
    doc = document(job.bundle)
    doc.sections.insert(
        0,
        ViewSection(
            title="Generated explanation — unreviewed",
            blocks=[
                ViewBlock(
                    title=b.title,
                    text=b.text,
                    citations=b.evidence_keys,
                    labels=[
                        b.kind,
                        "Unreviewed interpretation",
                        "Processing not independently verified",
                    ],
                )
                for b in response.blocks
            ],
        ),
    )
    doc.sections.append(
        ViewSection(
            title="Writer's limitations", blocks=[ViewBlock(text=t) for t in response.limitations]
        )
    )
    html = run_renderer(doc)
    with ws.lock(write=True):
        _returned(ws, response.job_id, response.input_hash)
        output_bytes(ws, output, html)
    return {"path": str(output), "bundle_id": job.bundle.id, "sha256": digest(html)}


def import_feedback(
    ws: Workspace, file: Path, *, inline_synthetic: bool = False
) -> FeedbackReceipt:
    raw = read_source_file(file)
    value = Feedback.model_validate_json(raw)
    bundle = load_view(ws, value.bundle_id)
    if value.bundle_hash != digest(canonical(bundle)):
        raise Denied("feedback bundle hash mismatch")
    if any(entry.target_id not in bundle.record_ids for entry in value.entries):
        raise Denied("feedback target is outside this view")
    feedback_id = "feedback_" + digest(canonical(value))[:32]
    path = f"{PREFIX}/feedback/{feedback_id}.json"
    with ws.lock():
        if ws.fs.exists(path):
            return FeedbackReceipt.model_validate_json(ws.fs.read(path))
    remember(ws, bundle, save=True)
    source = capture_bytes(
        ws,
        canonical(value),
        origin="imported-feedback.json",
        domain=bundle.domain,
        title="Imported view feedback",
        identity=feedback_id,
        source_type="text",
        classification=bundle.classification,
        processing=bundle.processing,
        compartments=bundle.compartments,
        scope_name=bundle.scope,
    )
    extract(ws, source.id, scope_name=bundle.scope, inline_synthetic=inline_synthetic)
    receipt = FeedbackReceipt(id=feedback_id, feedback=value, source_id=source.id)
    with ws.lock(write=True):
        recheck(ws, bundle)
        ws.fs.write(path, canonical(receipt))
    return receipt
