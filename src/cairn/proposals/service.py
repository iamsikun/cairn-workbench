from __future__ import annotations

import difflib

from cairn.adapters.fake import FakeProvider
from cairn.adapters.isolation import ClientPacketProvider
from cairn.adapters.protocol import Job, Page, Result
from cairn.errors import Blocked, CairnError, Conflict, Denied
from cairn.ingest.service import extract, load_extraction
from cairn.policies.audit import require_local_route_unlocked
from cairn.policies.models import require_inheritance
from cairn.proposals.models import Approval, Change, JobEnvelope, Proposal
from cairn.records.models import Event, EvidenceRef, Record, canonical, digest, new_id, now
from cairn.storage.markdown import decode, encode
from cairn.storage.workspace import Workspace


def target_path(record: Record) -> str:
    if record.type == "source":
        raise Denied("models cannot write source manifests")
    if record.type == "decision":
        return f"vault/decisions/{record.id}.md"
    return f"vault/wiki/{record.domain}/{record.id}.md"


def prepare_job(
    ws: Workspace,
    source_id: str,
    *,
    scope_name: str,
    related_ids: list[str] | None = None,
    provider: str = "fake-v1",
    execution_image: str | None = None,
) -> JobEnvelope:
    if not ws.config.synthetic and execution_image not in (None, ws.config.worker_image):
        raise Denied("client image is not bound to the approved runtime release")
    if related_ids is None:
        from cairn.retrieval.search import search

        with ws.lock():
            _, selected, _ = ws.record(source_id, ws.policy.scope(scope_name))
        related_ids = list(
            dict.fromkeys(
                hit.id
                for hit in search(
                    ws, selected.title, scope_name=scope_name, kind="synthesis", limit=3
                )
            )
        )
    with ws.lock(write=True):
        policy = ws.policy
        scope = policy.scope(scope_name)
        path, source, _ = ws.record(source_id, scope)
        evidence, evidence_hash = load_extraction(ws, source)
        if evidence.coverage == "failed":
            raise Blocked("no_extractable_text")
        related = [ws.record(object_id, scope) for object_id in (related_ids or [])]
        inputs = {path: digest(ws.fs.read(path)), f"evidence/{evidence_hash}.json": evidence_hash}
        inputs.update({path: digest(ws.fs.read(path)) for path, _, _ in related})
        cited = {ref.id for _, record, _ in related for ref in all_refs(record)}
        supporting = [ws.record(object_id, scope) for object_id in sorted(cited)]
        inputs.update({path: digest(ws.fs.read(path)) for path, _, _ in supporting})
        job = Job(
            id="job_pending",
            policy_hash=ws.policy_hash,
            scope_name=scope_name,
            provider=provider,
            execution_image=execution_image or ws.config.worker_image,
            source=source,
            extraction=evidence,
            evidence_hash=evidence_hash,
            related=[Page(record=record, body=body) for _, record, body in related],
            max_changes=policy.max_changes,
        )
        job.id = "job_" + digest(canonical(job))[:32]
        require_local_route_unlocked(
            ws,
            scope_name=scope_name,
            records=[source, *(item[1] for item in related), *(item[1] for item in supporting)],
            operation="generation",
            provider=provider,
            payload_hash=digest(canonical(job)),
        )
        if execution_image is not None:
            require_local_route_unlocked(
                ws,
                scope_name=scope_name,
                records=[source, *(item[1] for item in related), *(item[1] for item in supporting)],
                operation="client_export",
                provider=provider,
                payload_hash=digest(canonical(job)),
            )
        envelope = JobEnvelope(
            job=job, scope=scope, input_hashes=inputs, protected_hashes=ws.protected_hashes()
        )
        job_path = f"proposals/jobs/{job.id}.json"
        if not ws.fs.exists(job_path):
            ws.fs.write(job_path, canonical(envelope), exclusive=True)
        else:
            envelope = JobEnvelope.model_validate_json(ws.fs.read(job_path))
        return envelope


def load_job(ws: Workspace, job_id: str) -> JobEnvelope:
    return JobEnvelope.model_validate_json(ws.fs.read(f"proposals/jobs/{job_id}.json"))


def review_flags(record: Record) -> set[str]:
    flags: set[str] = {"evidence_and_interpretation"}
    if record.domain == "finance" or record.classification == "restricted":
        flags.add("sensitive_record")
    if record.type == "decision":
        flags.add("decision_review")
    if (record.type == "decision" and record.status == "active") or any(
        a.kind == "owner_decision" for a in record.assertions
    ):
        flags.add("owner_adoption")
    if any(a.kind in ("inference", "hypothesis") for a in record.assertions):
        flags.add("interpretation")
    if record.status in ("disputed", "superseded") or any(
        a.disputes or a.supersedes or a.verification == "disputed" for a in record.assertions
    ):
        flags.add("conflicting_evidence")
    return flags


def all_refs(record: Record) -> list[EvidenceRef]:
    return [
        *record.sources,
        *(ref for assertion in record.assertions for ref in assertion.sources),
        *(
            ref
            for assertion in record.assertions
            for amount in assertion.amounts
            for ref in amount.sources
        ),
    ]


def check_reference(ws: Workspace, ref: EvidenceRef, scope_name: str) -> None:
    _, source, _ = ws.record(ref.id, ws.policy.scope(scope_name))
    extraction, key = load_extraction(ws, source)
    if ref.source_hash != extraction.source_hash or ref.evidence_hash != key:
        raise CairnError("citation version/hash mismatch")
    segments = [segment for segment in extraction.segments if segment.locator == ref.locator]
    if not segments:
        raise CairnError("citation locator does not exist")
    if ref.quote is not None and not any(ref.quote in segment.text for segment in segments):
        raise CairnError("quoted text does not exist at the cited locator")


def _check_inputs(ws: Workspace, envelope: JobEnvelope) -> None:
    if envelope.job.route == "owner_device":
        from cairn.library.reader import check_binding, state_path
        from cairn.library.reader_models import ReadState

        state = ReadState.model_validate_json(
            ws.fs.read(state_path("read_" + envelope.job.id.removeprefix("job_")))
        )
        if state.status not in ("running", "completed"):
            raise Conflict("owner-device reading is no longer active")
        check_binding(ws, state.job)
    if ws.policy_hash != envelope.job.policy_hash:
        raise Conflict("policy changed; prepare a new job")
    current_scope = ws.policy.scope(envelope.job.scope_name)
    if canonical(current_scope) != canonical(envelope.scope):
        raise Conflict("scope changed")
    for path, expected in {**envelope.input_hashes, **envelope.protected_hashes}.items():
        if not ws.fs.exists(path) or digest(ws.fs.read(path)) != expected:
            raise Conflict("source, human note, or job input changed")


def stage_result(ws: Workspace, result: Result) -> Proposal | None:
    with ws.lock(write=True):
        envelope = load_job(ws, result.job_id)
        job = envelope.job
        _check_inputs(ws, envelope)
        if result.input_hash != digest(canonical(job)) or result.provider != job.provider:
            raise Denied("result does not match the sealed job")
        if len(result.candidates) > job.max_changes:
            raise CairnError("proposal exceeds change budget")
        existing = {record.id: (path, record) for path, record, _ in ws.records()}
        changes: list[Change] = []
        flags: set[str] = set()
        seen: set[str] = set()
        for candidate in result.candidates:
            record = candidate.record
            if "cairn_library_v1" in record.sections or (
                record.id in existing and "cairn_library_v1" in existing[record.id][1].sections
            ):
                raise Denied("library catalog and reading state are owner-controlled")
            if record.id in seen:
                raise CairnError("duplicate candidate ID")
            seen.add(record.id)
            envelope.scope.require(record)
            require_inheritance(record, [job.source, *(page.record for page in job.related)])
            path = target_path(record)
            if record.id in existing:
                old_path, old = existing[record.id]
                envelope.scope.require(old)
                if old_path != path or old.created_at != record.created_at:
                    raise Denied("record move or creation timestamp change is not permitted")
            content = encode(record, candidate.body)
            before = ws.fs.read(path) if ws.fs.exists(path) else None
            if before == content:
                continue
            flags |= review_flags(record)
            changes.append(
                Change(
                    id=record.id,
                    path=path,
                    base_hash=digest(before) if before is not None else None,
                    content=content.decode(),
                    content_hash=digest(content),
                    diff="".join(
                        difflib.unified_diff(
                            (before or b"").decode().splitlines(keepends=True),
                            content.decode().splitlines(keepends=True),
                            fromfile=f"before/{path}",
                            tofile=f"after/{path}",
                        )
                    ),
                    rationale=candidate.rationale,
                )
            )
        if not changes:
            return None
        proposal = Proposal(
            id="proposal_pending",
            workspace_id=ws.config.id,
            job_id=job.id,
            input_hash=result.input_hash,
            policy_hash=job.policy_hash,
            provider=job.provider,
            route=job.route,
            created_at=job.source.created_at,
            changes=changes,
            review_flags=flags,
        )
        proposal.id = "proposal_" + digest(canonical(proposal))[:32]
        path = f"proposals/{proposal.id}.json"
        if not ws.fs.exists(path):
            ws.fs.write(path, canonical(proposal), exclusive=True)
            ws.event(
                Event(
                    id=new_id("event"),
                    object_id=job.source.id,
                    attempt_id=job.id,
                    stage="proposed",
                    at=now(),
                    hashes={"proposal": digest(canonical(proposal))},
                )
            )
        return proposal


def load_proposal(ws: Workspace, proposal_id: str) -> Proposal:
    proposal = Proposal.model_validate_json(ws.fs.read(f"proposals/{proposal_id}.json"))
    if proposal.id != proposal_id or proposal.workspace_id != ws.config.id:
        raise Denied("proposal does not belong to this workspace")
    return proposal


def validate_unlocked(ws: Workspace, proposal: Proposal) -> JobEnvelope:
    if proposal.route == "owner_device":
        from cairn.library.verification import require_no_failed_checks

        require_no_failed_checks(ws, proposal.id)
    envelope = load_job(ws, proposal.job_id)
    job = envelope.job
    _check_inputs(ws, envelope)
    if (
        proposal.input_hash != digest(canonical(job))
        or proposal.policy_hash != job.policy_hash
        or proposal.provider != job.provider
        or proposal.route != job.route
        or proposal.workspace_id != ws.config.id
    ):
        raise Denied("proposal binding mismatch")
    if len(proposal.changes) > ws.policy.max_changes:
        raise CairnError("proposal exceeds change budget")
    current = {record.id: (path, record) for path, record, _ in ws.records()}
    candidate_ids = {change.id for change in proposal.changes}
    if len(candidate_ids) != len(proposal.changes):
        raise CairnError("duplicate candidate ID")
    candidate_records = {
        change.id: decode(change.content.encode())[0] for change in proposal.changes
    }
    final_records = {key: value[1] for key, value in current.items()} | candidate_records
    assertion_owners: dict[str, Record] = {}
    for candidate in final_records.values():
        for assertion in candidate.assertions:
            if assertion.id in final_records or assertion.id in assertion_owners:
                raise CairnError("ambiguous durable assertion ID")
            assertion_owners[assertion.id] = candidate
    expected_flags: set[str] = set()
    for change in proposal.changes:
        record, body = decode(change.content.encode())
        if "cairn_library_v1" in record.sections or (
            record.id in current and "cairn_library_v1" in current[record.id][1].sections
        ):
            raise Denied("library catalog and reading state are owner-controlled")
        if record.id != change.id or change.path != target_path(record):
            raise Denied("invalid target path or ID")
        envelope.scope.require(record)
        require_inheritance(record, [job.source, *(page.record for page in job.related)])
        if record.id in current:
            old_path, old = current[record.id]
            envelope.scope.require(old)
            if old_path != change.path or old.created_at != record.created_at:
                raise Denied("record identity changed")
        expected = digest(ws.fs.read(change.path)) if ws.fs.exists(change.path) else None
        if expected != change.base_hash:
            raise Conflict("proposal is stale: owner content changed")
        if digest(change.content.encode()) != change.content_hash:
            raise CairnError("candidate checksum mismatch")
        before = ws.fs.read(change.path).decode() if ws.fs.exists(change.path) else ""
        actual_diff = "".join(
            difflib.unified_diff(
                before.splitlines(keepends=True),
                change.content.splitlines(keepends=True),
                fromfile=f"before/{change.path}",
                tofile=f"after/{change.path}",
            )
        )
        if change.diff != actual_diff:
            raise CairnError("review diff does not match candidate bytes")
        for ref in all_refs(record):
            check_reference(ws, ref, job.scope_name)
            _, cited, _ = ws.record(ref.id, envelope.scope)
            require_inheritance(record, [cited])
        if record.domain == "finance":
            from cairn.ingest.finance import check_observed_money, validate_snapshot_record

            if record.finance_category is None:
                raise CairnError("finance records require an explicit knowledge category")
            for assertion in record.assertions:
                for amount in assertion.amounts:
                    check_observed_money(ws, amount, scope_name=job.scope_name)
            if record.finance_category == "account_snapshot":
                validate_snapshot_record(ws, record, body, scope_name=job.scope_name)
        for linked in [*record.related, *record.project_ids]:
            if linked not in candidate_ids:
                ws.record(linked, envelope.scope)
            if linked in record.project_ids and final_records[linked].type != "project":
                raise CairnError("project links must name project records")
        for assertion in record.assertions:
            for linked in [*assertion.supersedes, *assertion.disputes]:
                if linked in (record.id, assertion.id):
                    raise CairnError("assertion cannot supersede or dispute itself")
                target = final_records.get(linked) or assertion_owners.get(linked)
                if target is None:
                    raise Denied("conflict reference unavailable in this scope")
                envelope.scope.require(target)
                require_inheritance(record, [target])
        expected_flags |= review_flags(record)
    if expected_flags != proposal.review_flags:
        raise Denied("review flags do not match proposed content")
    return envelope


def validate(ws: Workspace, proposal_id: str) -> Proposal:
    with ws.lock(write=True):
        proposal = load_proposal(ws, proposal_id)
        envelope = validate_unlocked(ws, proposal)
        ws.event(
            Event(
                id=new_id("event"),
                object_id=envelope.job.source.id,
                attempt_id=proposal.id,
                stage="validated",
                at=now(),
                hashes={"proposal": digest(canonical(proposal))},
            )
        )
        return proposal


def approve(
    ws: Workspace, proposal_id: str, *, acknowledgements: set[str], statement: str
) -> Approval:
    with ws.lock(write=True):
        proposal = load_proposal(ws, proposal_id)
        envelope = validate_unlocked(ws, proposal)
        if not proposal.review_flags <= acknowledgements:
            raise Denied("all required review flags must be acknowledged")
        if proposal.route == "owner_device":
            from cairn.library.verification import require_ready_for_acceptance

            require_ready_for_acceptance(ws, proposal.id)
        ws.event(
            Event(
                id=new_id("event"),
                object_id=envelope.job.source.id,
                attempt_id=proposal.id,
                stage="validated",
                at=now(),
                hashes={"proposal": digest(canonical(proposal))},
            )
        )
        approval = Approval(
            proposal_id=proposal.id,
            workspace_id=ws.config.id,
            proposal_hash=digest(canonical(proposal)),
            policy_hash=ws.policy_hash,
            acknowledgements=acknowledgements,
            owner_statement=statement,
            at=now(),
        )
        ws.fs.write(f"approvals/{proposal.id}.json", canonical(approval))
        ws.event(
            Event(
                id=new_id("event"),
                object_id=envelope.job.source.id,
                attempt_id=proposal.id,
                stage="approved",
                at=now(),
                hashes={"proposal": approval.proposal_hash},
            )
        )
        return approval


def ingest(
    ws: Workspace,
    source_id: str,
    *,
    scope_name: str,
    related_ids: list[str] | None = None,
    inline_synthetic: bool = False,
) -> Proposal | None:
    extract(ws, source_id, scope_name=scope_name, inline_synthetic=inline_synthetic)
    envelope = prepare_job(ws, source_id, scope_name=scope_name, related_ids=related_ids)
    try:
        if inline_synthetic and ws.config.synthetic:
            result = FakeProvider().generate(envelope.job)
        elif ws.config.worker_image:
            result = ClientPacketProvider(ws.config.worker_image).generate(envelope.job)
        else:
            raise Blocked("isolation_unavailable")
    except Exception as exc:
        with ws.lock(write=True):
            ws.event(
                Event(
                    id=new_id("event"),
                    object_id=source_id,
                    attempt_id=envelope.job.id,
                    stage="extracted",
                    outcome="blocked" if isinstance(exc, Blocked) else "failed",
                    reason=exc.code if isinstance(exc, CairnError) else "generation_failed",
                    at=now(),
                )
            )
        if isinstance(exc, CairnError):
            raise
        raise CairnError("generation failed; source and job preserved") from exc
    return stage_result(ws, result)
