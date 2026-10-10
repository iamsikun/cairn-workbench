"""The owner's agent writes; Cairn says what and where, then formats a proposal.

`begin` seals one packet: instructions, one target (existing page or new record slot),
scoped evidence and Cairn's writing contract. `finish` checks the returned prose and claims,
preserves the response as a source, builds the record itself and stages a validated
proposal. Approval and apply remain separate owner operations (`cairn accept`).
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from pydantic import TypeAdapter

from cairn.adapters.protocol import Candidate, Job, Page, Result
from cairn.errors import Blocked, Conflict, Denied
from cairn.ingest.service import capture_bytes, extract, load_extraction, read_source_file
from cairn.policies.models import LEVEL
from cairn.presentation.service import output_bytes
from cairn.presentation.writing import PREFIX as PRESENTATION
from cairn.presentation.writing import guidance
from cairn.presentation.writing_models import (
    ExportReceipt,
    FeedbackReceipt,
    NewTarget,
    PageAnswer,
    QuillEvidence,
    QuillPacket,
    QuillReceipt,
    QuillResponse,
)
from cairn.proposals.models import JobEnvelope, Proposal
from cairn.proposals.service import check_reference, stage_result, validate
from cairn.records.models import (
    ID,
    Assertion,
    Classification,
    EvidenceRef,
    Labels,
    Processing,
    Record,
    canonical,
    digest,
    now,
)
from cairn.storage.files import components
from cairn.storage.workspace import Workspace

PREFIX = "receipts/quill"
PROVIDER = "quill-cairn-1"


def identity(packet: QuillPacket) -> str:
    value = packet.model_dump(mode="json")
    value["id"] = "quill_pending"
    return "quill_" + digest(canonical(value))[:32]


def packet_path(packet_id: str) -> str:
    TypeAdapter(ID).validate_python(packet_id)
    return f"{PREFIX}/packets/{packet_id}.json"


def _inputs(packet: QuillPacket) -> list[Labels]:
    pages = [packet.target] if packet.target else []
    return [*(p.record for p in [*pages, *packet.context]), *packet.sources]


def authorize(ws: Workspace, packet: QuillPacket) -> None:
    scope = ws.policy.scope(packet.scope)
    for operation in ("generation", "client_export"):
        ws.policy.authorize_route(
            scope,
            _inputs(packet),
            route="cloud",
            provider=packet.provider,
            destination=packet.destination,
            operation=operation,
            question=packet.request_labels,
        )


def load_packet(ws: Workspace, packet_id: str) -> QuillPacket:
    packet = QuillPacket.model_validate_json(ws.fs.read(packet_path(packet_id)))
    if packet.id != packet_id or identity(packet) != packet_id:
        raise Denied("Quill packet identity mismatch")
    if packet.policy_hash != ws.policy_hash:
        raise Conflict("policy changed; prepare a new writing packet")
    for path, checksum in packet.input_hashes.items():
        if not ws.fs.exists(path) or digest(ws.fs.read(path)) != checksum:
            raise Conflict("writing target, evidence or context changed")
    authorize(ws, packet)
    receipt = ExportReceipt.model_validate_json(ws.fs.read(f"{PREFIX}/exports/{packet.id}.json"))
    if (
        receipt.job_id != packet.id
        or receipt.input_hash != digest(canonical(packet))
        or receipt.policy_hash != packet.policy_hash
        or receipt.provider != packet.provider
        or receipt.destination != packet.destination
    ):
        raise Conflict("Quill export binding changed")
    return packet


def begin(
    ws: Workspace,
    output: Path | None,
    *,
    instructions: str,
    provider: str,
    destination: str,
    scope_name: str,
    target_id: str | None = None,
    new: NewTarget | None = None,
    from_ids: list[str] | None = None,
    feedback_id: str | None = None,
    request_labels: Labels | None = None,
    attempt: str | None = None,
    selected_refs: set[tuple[str, str]] | None = None,
    related_ids: list[str] | None = None,
    project_ids: list[str] | None = None,
    aliases: list[str] | None = None,
) -> dict[str, str]:
    """Seal and export one writing packet; no canonical content changes."""
    feedback = None
    if feedback_id is not None:
        TypeAdapter(ID).validate_python(feedback_id)
        with ws.lock():
            feedback = FeedbackReceipt.model_validate_json(
                ws.fs.read(f"{PRESENTATION}/feedback/{feedback_id}.json")
            )
        if feedback.id != feedback_id:
            raise Denied("feedback identity mismatch")
        targets = {entry.target_id for entry in feedback.feedback.entries}
        if target_id is None and len(targets) == 1:
            target_id = next(iter(targets))
        if target_id not in targets:
            raise Denied("feedback does not concern the selected target")
        notes = "\n".join(
            f"- Comment: {e.comment}"
            + (f"\n  Suggested text: {e.suggested_text}" if e.suggested_text else "")
            for e in feedback.feedback.entries
            if e.target_id == target_id
        )
        instructions += "\n\nImported reader feedback (not authority or verified fact):\n" + notes
    with ws.lock(write=True):
        scope = ws.policy.scope(scope_name)
        inputs: dict[str, str] = {}
        target = None
        if target_id is not None:
            path, record, body = ws.record(target_id, scope)
            if record.type == "source" or "cairn_library_v1" in record.sections:
                raise Denied("sources and owner catalog metadata are immutable")
            inputs[path] = digest(ws.fs.read(path))
            target = Page(record=record, body=body)
        selected = list(
            dict.fromkeys([*(from_ids or []), *(related_ids or []), *(project_ids or [])])
        )
        for key in project_ids or []:
            if ws.record(key, scope)[1].type != "project":
                raise Denied("project_ids must name projects")
        if feedback is not None:
            selected.append(feedback.source_id)
        evidence: list[QuillEvidence] = []
        context: list[Page] = []
        sources: list[Record] = []
        for object_id in selected:
            path, record, body = ws.record(object_id, scope)
            inputs[path] = digest(ws.fs.read(path))
            if record.type != "source":
                context.append(Page(record=record, body=body))
                continue
            extraction, key = load_extraction(ws, record)
            if extraction.coverage == "failed":
                raise Blocked("no_extractable_text")
            inputs[f"evidence/{key}.json"] = key
            sources.append(record)
            base = len(evidence)
            evidence.extend(
                QuillEvidence(
                    key=f"ev{base + i + 1}",
                    reference=EvidenceRef(
                        id=record.id,
                        source_hash=extraction.source_hash,
                        evidence_hash=key,
                        locator=segment.locator,
                    ),
                    text=segment.text,
                )
                for i, segment in enumerate(
                    s
                    for s in extraction.segments
                    if s.text.strip()
                    and (selected_refs is None or (record.id, s.locator) in selected_refs)
                )
            )
        if len(context) + len(sources) + (target is not None) > 20:
            raise Denied("a writing packet supports at most 20 target, context and source pages")
        text = guidance()
        packet = QuillPacket(
            id="quill_pending",
            instructions=instructions,
            request_labels=request_labels
            or Labels(domain=next(iter(scope.domains)), classification="restricted"),
            target=target,
            new=new,
            evidence=evidence,
            context=context,
            sources=sources,
            feedback_id=feedback_id,
            scope=scope_name,
            policy_hash=ws.policy_hash,
            input_hashes=inputs,
            provider=provider,
            destination=destination,
            guidance_hash=digest(text.encode()),
            attempt=attempt,
            related_ids=related_ids,
            project_ids=project_ids,
            aliases=aliases,
        )
        if new is not None and new.domain not in scope.domains:
            raise Denied("new record domain is outside the writing scope")
        authorize(ws, packet)
        packet.id = identity(packet)
        if not ws.fs.exists(packet_path(packet.id)):
            ws.fs.write(packet_path(packet.id), canonical(packet), exclusive=True)
        export_path = f"{PREFIX}/exports/{packet.id}.json"
        if not ws.fs.exists(export_path):
            # Record export intent before releasing bytes; it is not proof of execution.
            receipt = ExportReceipt(
                job_id=packet.id,
                input_hash=digest(canonical(packet)),
                policy_hash=packet.policy_hash,
                provider=provider,
                destination=destination,
                at=now(),
            )
            ws.fs.write(export_path, canonical(receipt), exclusive=True)
        if output is None:
            return {"packet_id": packet.id, "input_hash": digest(canonical(packet))}
        output_bytes(
            ws,
            output,
            canonical(
                {
                    "packet": packet,
                    "input_hash": digest(canonical(packet)),
                    "guidance": text,
                    "response_schema": QuillResponse.model_json_schema(),
                }
            ),
        )
    return {
        "packet_id": packet.id,
        "input_hash": digest(canonical(packet)),
        "path": str(output.absolute()),
    }


def check_response(packet: QuillPacket, response: QuillResponse) -> list[list[EvidenceRef]]:
    """Return each claim's evidence; fabricated keys or quotes are denied."""
    if response.packet_id != packet.id or response.input_hash != digest(canonical(packet)):
        raise Denied("Quill response does not match its prepared packet")
    supplied = {e.key: e for e in packet.evidence}
    cited = []
    for claim in response.claims:
        refs = []
        for key in claim.evidence_keys:
            if key not in supplied:
                raise Denied("Quill claim cites unavailable evidence")
            quotes: list[str | None] = [q.text for q in claim.quotations if q.evidence_key == key]
            for quote in quotes:
                if quote is not None and quote not in supplied[key].text:
                    raise Denied("Quill quote is not present in supplied evidence")
            refs += [
                supplied[key].reference.model_copy(update={"quote": quote})
                for quote in quotes or [None]
            ]
        cited.append(refs)
    return cited


def _labels(packet: QuillPacket) -> tuple[Classification, Processing, set[str]]:
    labels = [*_inputs(packet), packet.request_labels]
    classification = max((x.classification for x in labels), key=LEVEL.__getitem__)
    processing: Processing = (
        "local_only" if any(x.processing == "local_only" for x in labels) else "cloud_eligible"
    )
    compartments: set[str] = set().union(*(x.compartments | {x.domain} for x in labels))
    return classification, processing, compartments


def _record(
    packet: QuillPacket,
    response: QuillResponse,
    cited: list[list[EvidenceRef]],
    session: EvidenceRef,
) -> Record:
    suffix = packet.id.removeprefix("quill_")
    assertions = [
        Assertion(
            id=f"assert_quill_{suffix}_{i}",
            text=claim.text,
            kind=claim.kind,
            sources=refs,
            rationale="Quill draft; unreviewed and not independent evidence",
        )
        for i, (claim, refs) in enumerate(zip(response.claims, cited, strict=True))
    ]
    refs = [ref for group in cited for ref in group]
    from cairn.presentation.pages import page_record

    old = packet.target.record if packet.target else None
    destination = old or packet.new
    assert destination is not None
    classification, processing, compartments = _labels(packet)
    return page_record(
        old=old,
        record_id=old.id if old else f"{destination.type}_quill_{suffix}",
        record_type=destination.type,
        title=response.title or destination.title,
        labels=Labels(
            domain=destination.domain,
            classification=classification,
            processing=processing,
            compartments=compartments - {destination.domain},
        ),
        at=now(),
        sources=[*refs, session],
        assertions=assertions,
        related=packet.related_ids,
        project_ids=_projects(packet),
        aliases=packet.aliases,
    )


def _projects(packet: QuillPacket) -> list[str]:
    if packet.project_ids is not None:
        return packet.project_ids
    if packet.target:
        return packet.target.record.project_ids
    return sorted(
        {
            key
            for page in packet.context
            for key in (
                [page.record.id] if page.record.type == "project" else page.record.project_ids
            )
        }
        | {key for source in packet.sources for key in source.project_ids}
    )


def finish(ws: Workspace, file: Path, *, inline_synthetic: bool = False) -> QuillReceipt:
    return finish_bytes(ws, read_source_file(file), inline_synthetic=inline_synthetic)


def submit(
    ws: Workspace,
    answer: PageAnswer,
    *,
    instructions: str,
    provider: str,
    destination: str,
    scope_name: str,
    request_labels: Labels,
    target_id: str | None = None,
    new: NewTarget | None = None,
    from_ids: list[str] | None = None,
    feedback_id: str | None = None,
    base_hash: str | None = None,
    inline_synthetic: bool = False,
) -> QuillReceipt:
    """Seal the page's inputs and stage the agent's draft in one owner-side step.

    The agent cites sources by ID and locator; Cairn maps each citation to the sealed
    evidence, so a citation outside the supplied sources is refused.
    """
    cited = [ref.source_id for claim in answer.claims for ref in claim.sources]
    sealed = begin(
        ws,
        None,
        instructions=instructions,
        provider=provider,
        destination=destination,
        scope_name=scope_name,
        target_id=target_id,
        new=new,
        from_ids=list(dict.fromkeys([*(from_ids or []), *cited])),
        feedback_id=feedback_id,
        request_labels=request_labels,
        attempt=digest(canonical(answer)),
        selected_refs={
            (ref.source_id, ref.locator) for claim in answer.claims for ref in claim.sources
        },
        related_ids=answer.related,
        project_ids=answer.project_ids,
        aliases=answer.aliases,
    )
    with ws.lock():
        packet = load_packet(ws, sealed["packet_id"])
    if packet.target is not None:
        from cairn.proposals.service import target_path

        # The agent revised the version it read; a newer page must not be overwritten.
        if base_hash != packet.input_hashes.get(target_path(packet.target.record)):
            raise Conflict("the page changed since the agent read it; read it again")
    keys = {(e.reference.id, e.reference.locator): e.key for e in packet.evidence}
    claims = []
    for claim in answer.claims:
        evidence_keys, quotations = [], []
        for ref in claim.sources:
            key = keys.get((ref.source_id, ref.locator))
            if key is None:
                raise Denied("page claim cites a locator outside the supplied sources")
            evidence_keys.append(key)
            if ref.quote is not None:
                quotations.append({"evidence_key": key, "text": ref.quote})
        claims.append(
            {
                "text": claim.text,
                "kind": claim.kind,
                "evidence_keys": list(dict.fromkeys(evidence_keys)),
                "quotations": quotations,
            }
        )
    response = QuillResponse.model_validate(
        {
            "packet_id": packet.id,
            "input_hash": sealed["input_hash"],
            "title": answer.title,
            "body_markdown": answer.body_markdown,
            "claims": claims,
            "limitations": answer.limitations,
        }
    )
    return finish_bytes(ws, canonical(response), inline_synthetic=inline_synthetic)


def finish_bytes(ws: Workspace, raw: bytes, *, inline_synthetic: bool = False) -> QuillReceipt:
    """Gather the agent's output, format it and stage a validated proposal; never apply."""
    response = QuillResponse.model_validate_json(raw)
    checksum = digest(raw)
    receipt_path = f"{PREFIX}/finished/{response.packet_id}.json"
    response_path = f"{PREFIX}/responses/{response.packet_id}.json"
    with ws.lock(write=True):
        packet = load_packet(ws, response.packet_id)
        cited = check_response(packet, response)
        for refs in cited:
            for ref in refs:
                check_reference(ws, ref, packet.scope)
        if ws.fs.exists(receipt_path):
            receipt = QuillReceipt.model_validate_json(ws.fs.read(receipt_path))
            if receipt.response_hash != checksum:
                raise Conflict("writing packet already finished with a different response")
            return receipt
        if ws.fs.exists(response_path) and digest(ws.fs.read(response_path)) != checksum:
            raise Conflict("writing packet already preserved a different response")
        if not ws.fs.exists(response_path):
            ws.fs.write(response_path, raw, exclusive=True)
    classification, processing, compartments = _labels(packet)
    if packet.target is not None:
        domain, heading = packet.target.record.domain, packet.target.record.title
    else:
        assert packet.new is not None
        domain, heading = packet.new.domain, packet.new.title
    source = capture_bytes(
        ws,
        raw,
        origin=f"quill:{packet.id}",
        domain=domain,
        title=f"Quill draft: {response.title or heading}"[:500],
        identity=f"quill-packet:{packet.id}",
        source_type="text",
        version=checksum,
        classification=classification,
        processing=processing,
        compartments=compartments - {domain},
        project_ids=_projects(packet),
        scope_name=packet.scope,
    )
    extract(ws, source.id, scope_name=packet.scope, inline_synthetic=inline_synthetic)
    with ws.lock(write=True):
        packet = load_packet(ws, packet.id)
        source_path, source, _ = ws.record(source.id, ws.policy.scope(packet.scope))
        extraction, key = load_extraction(ws, source)
        if extraction.coverage == "failed" or not extraction.segments:
            raise Denied("Quill response has no extractable text")
        session = EvidenceRef(
            id=source.id,
            source_hash=extraction.source_hash,
            evidence_hash=key,
            locator=extraction.segments[0].locator,
        )
        record = _record(packet, response, cited, session)
        job = Job(
            id="job_quill_" + packet.id.removeprefix("quill_"),
            policy_hash=packet.policy_hash,
            scope_name=packet.scope,
            route="cloud",
            provider=PROVIDER,
            source=source,
            extraction=extraction,
            evidence_hash=key,
            related=[
                *([packet.target] if packet.target else []),
                *packet.context,
                *(Page(record=r, body="") for r in packet.sources),
            ],
            max_changes=1,
        )
        envelope = JobEnvelope(
            job=job,
            scope=ws.policy.scope(packet.scope),
            input_hashes={
                **packet.input_hashes,
                packet_path(packet.id): digest(ws.fs.read(packet_path(packet.id))),
                f"{PREFIX}/exports/{packet.id}.json": digest(
                    ws.fs.read(f"{PREFIX}/exports/{packet.id}.json")
                ),
                response_path: checksum,
                source_path: digest(ws.fs.read(source_path)),
                f"evidence/{key}.json": key,
            },
            protected_hashes=ws.protected_hashes(),
        )
        envelope_path = f"proposals/jobs/{job.id}.json"
        if not ws.fs.exists(envelope_path):
            ws.fs.write(envelope_path, canonical(envelope), exclusive=True)
        else:
            existing = JobEnvelope.model_validate_json(ws.fs.read(envelope_path))
            if canonical(existing.job) != canonical(job):
                raise Conflict("Quill proposal job changed")
            job = existing.job
        result = Result(
            job_id=job.id,
            input_hash=digest(canonical(job)),
            provider=job.provider,
            candidates=[
                Candidate(
                    record=record,
                    body=response.body_markdown.rstrip("\n") + "\n",
                    rationale="Quill draft from owner instructions; owner review required",
                )
            ],
        )
    proposal = stage_result(ws, result)
    if proposal is None:
        raise Conflict("Quill response does not change the target")
    validate(ws, proposal.id)
    receipt = QuillReceipt(
        packet_id=packet.id, response_hash=checksum, source_id=source.id, proposal_id=proposal.id
    )
    with ws.lock(write=True):
        load_packet(ws, packet.id)
        if ws.fs.exists(receipt_path):
            existing_receipt = QuillReceipt.model_validate_json(ws.fs.read(receipt_path))
            if existing_receipt != receipt:
                raise Conflict("concurrent Quill handoff differs")
            return existing_receipt
        ws.fs.write(receipt_path, canonical(receipt), exclusive=True)
    return receipt


def check_proposal_binding(ws: Workspace, job: Job) -> None:
    packet = load_packet(ws, "quill_" + job.id.removeprefix("job_quill_"))
    if job.policy_hash != packet.policy_hash or job.route != "cloud" or job.provider != PROVIDER:
        raise Denied("Quill proposal route binding mismatch")


def validate_writing(payloads: Mapping[str, bytes], records: dict[str, Record]) -> None:
    """Restore-time checks for writing artifacts; never authorizes execution."""
    packets = {}
    for path, raw in payloads.items():
        if path.startswith(f"{PREFIX}/packets/"):
            packet = QuillPacket.model_validate_json(raw)
            if path != packet_path(packet.id) or packet.id != identity(packet):
                raise Conflict("saved Quill packet identity mismatch")
            for name in packet.input_hashes:
                components(name)
            packets[packet.id] = packet
    for path, raw in payloads.items():
        if not path.startswith(f"{PREFIX}/") or path.startswith(f"{PREFIX}/packets/"):
            continue
        packet_id = path.rsplit("/", 1)[-1].removesuffix(".json")
        if packet_id not in packets:
            raise Conflict("saved Quill artifact has no packet")
        packet = packets[packet_id]
        category = path.removeprefix(f"{PREFIX}/").split("/", 1)[0]
        if category == "exports":
            exported = ExportReceipt.model_validate_json(raw)
            if exported.job_id != packet_id or exported.input_hash != digest(canonical(packet)):
                raise Conflict("saved Quill export mismatch")
        elif category == "responses":
            check_response(packet, QuillResponse.model_validate_json(raw))
        elif category == "finished":
            receipt = QuillReceipt.model_validate_json(raw)
            response_raw = payloads.get(f"{PREFIX}/responses/{packet_id}.json")
            proposal_raw = payloads.get(f"proposals/{receipt.proposal_id}.json")
            source = records.get(receipt.source_id)
            if (
                receipt.packet_id != packet_id
                or response_raw is None
                or digest(response_raw) != receipt.response_hash
                or proposal_raw is None
                or source is None
                or source.source is None
                or source.source.content_hash != receipt.response_hash
            ):
                raise Conflict("saved Quill handoff binding mismatch")
            proposal = Proposal.model_validate_json(proposal_raw)
            if proposal.job_id != "job_quill_" + packet_id.removeprefix("quill_"):
                raise Conflict("saved Quill proposal binding mismatch")
        else:
            raise Conflict("unknown saved Quill artifact")
