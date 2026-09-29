from __future__ import annotations

from pathlib import Path

from cairn.adapters.protocol import Candidate, Result
from cairn.errors import Conflict, Denied
from cairn.ingest.service import capture, extract
from cairn.proposals.models import Proposal
from cairn.proposals.service import prepare_job, stage_result, target_path
from cairn.records.models import canonical, digest
from cairn.storage.files import RootFS
from cairn.storage.markdown import decode
from cairn.storage.workspace import Workspace


def edit_from_file(
    ws: Workspace,
    record_id: str,
    edited_file: Path,
    *,
    expected_hash: str,
    inline_synthetic: bool = False,
) -> Proposal | None:
    """Stage an owner-authored revision. Normal review/approval/apply still follows."""
    raw = RootFS(edited_file.parent).read(edited_file.name)
    candidate, body = decode(raw)
    with ws.lock():
        path, original, _ = ws.record(record_id)
        if original.type == "source" or candidate.id != record_id or target_path(candidate) != path:
            raise Denied("edit cannot alter source manifests or record identity")
        if digest(ws.fs.read(path)) != expected_hash:
            raise Conflict("owner edit base is stale")
        if raw == ws.fs.read(path):
            return None
    source = capture(
        ws,
        edited_file,
        domain=original.domain,
        title=f"Owner revision: {original.title}",
        identity=f"owner-edit:{record_id}:{digest(raw)}",
        classification=original.classification,
        processing=original.processing,
        compartments=original.compartments,
        source_type="markdown",
    )
    extract(ws, source.id, inline_synthetic=inline_synthetic)
    envelope = prepare_job(
        ws, source.id, scope_name="owner", related_ids=[record_id], provider="owner-edit"
    )
    if envelope.input_hashes[path] != expected_hash:
        raise Conflict("canonical record changed while the owner edited")
    return stage_result(
        ws,
        Result(
            job_id=envelope.job.id,
            input_hash=digest(canonical(envelope.job)),
            provider="owner-edit",
            candidates=[
                Candidate(record=candidate, body=body, rationale="Owner-authored staged revision.")
            ],
        ),
    )
