"""Restore-time validation for durable view and writing artifacts."""

from collections.abc import Mapping

from cairn.errors import Conflict, Denied
from cairn.presentation.models import ViewBundle
from cairn.presentation.service import identity
from cairn.presentation.writing import job_identity, validate_explanation
from cairn.presentation.writing_models import (
    ExplanationResponse,
    ExportReceipt,
    FeedbackReceipt,
    WritingJob,
)
from cairn.records.models import Extraction, Record, canonical, digest
from cairn.storage.files import components


def validate_presentation(
    payloads: Mapping[str, bytes], records: dict[str, Record], workspace_id: str
) -> None:
    def bundle(value: ViewBundle) -> None:
        if value.workspace_id != workspace_id or value.id != identity(value):
            raise Conflict("saved view identity mismatch")
        for path in value.input_hashes:
            components(path)
        if any(key not in records for key in value.record_ids):
            raise Conflict("saved view references an absent record")
        for e in value.evidence:
            if e.reference.id not in value.record_ids:
                raise Conflict("saved view evidence outside the bound record set")
            if e.support.startswith("Unsupported"):
                if value.payload.kind != "proposal":
                    raise Conflict("unsupported evidence outside proposal review")
                continue
            path = f"evidence/{e.reference.evidence_hash}.json"
            if path not in payloads:
                raise Conflict("saved view evidence unavailable")
            if digest(payloads[path]) != e.reference.evidence_hash:
                raise Conflict("saved view evidence checksum mismatch")
            extraction = Extraction.model_validate_json(payloads[path])
            if extraction.source_hash != e.reference.source_hash:
                raise Conflict("saved view source version mismatch")
            segments = [s.text for s in extraction.segments if s.locator == e.reference.locator]
            expected = e.reference.quote or "\n".join(segments)
            if (
                not segments
                or e.text != expected
                or (e.reference.quote is not None and not any(e.text in s for s in segments))
            ):
                raise Conflict("saved view evidence text or locator mismatch")

    jobs = {}
    for path, raw in payloads.items():
        if path.startswith("receipts/presentation/jobs/"):
            job = WritingJob.model_validate_json(raw)
            if job.id != job_identity(job) or path != f"receipts/presentation/jobs/{job.id}.json":
                raise Conflict("writing job identity mismatch")
            bundle(job.bundle)
            jobs[job.id] = job
    for path, raw in payloads.items():
        if not path.startswith("receipts/presentation/"):
            continue
        if path.startswith("receipts/presentation/views/"):
            value = ViewBundle.model_validate_json(raw)
            if path != f"receipts/presentation/views/{value.id}.json":
                raise Conflict("saved view path mismatch")
            bundle(value)
        elif path.startswith("receipts/presentation/jobs/"):
            continue
        elif path.startswith("receipts/presentation/feedback/"):
            feedback = FeedbackReceipt.model_validate_json(raw)
            expected = "feedback_" + digest(canonical(feedback.feedback))[:32]
            if (
                feedback.id != expected
                or path != f"receipts/presentation/feedback/{expected}.json"
                or feedback.source_id not in records
            ):
                raise Conflict("feedback identity mismatch")
        elif path.startswith("receipts/presentation/exports/"):
            receipt = ExportReceipt.model_validate_json(raw)
            if (
                receipt.job_id not in jobs
                or receipt.input_hash != digest(canonical(jobs[receipt.job_id]))
                or path != f"receipts/presentation/exports/{receipt.job_id}.json"
            ):
                raise Conflict("writing export binding mismatch")
        elif path.startswith("receipts/presentation/explanations/"):
            response = ExplanationResponse.model_validate_json(raw)
            if response.job_id not in jobs or response.input_hash != digest(
                canonical(jobs[response.job_id])
            ):
                raise Conflict("explanation binding mismatch")
            filename = f"{response.job_id}-{digest(canonical(response))}.json"
            expected = f"receipts/presentation/explanations/{filename}"
            if path != expected:
                raise Conflict("explanation path mismatch")
            validate_explanation(jobs[response.job_id], response)
        else:
            raise Denied("unknown presentation receipt")
