"""Synthetic Finch integration and owner-boundary regression checks."""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from pydantic import ValidationError
from test_presentation import source

from cairn.errors import CairnError, Conflict, Denied
from cairn.policies.audit import revoke_grant, set_grant
from cairn.policies.models import RouteGrant
from cairn.proposals.service import approve, load_proposal, validate
from cairn.reading.contract import guidance_hash
from cairn.reading.models import FinchClaim, FinchPacket, FinchResponse
from cairn.reading.workflow import begin, finish
from cairn.records.continuity import ReceiptMessage
from cairn.records.models import EvidenceRef, Labels, Record, canonical, digest, now
from cairn.storage.backup import durable_contents, validate_payloads
from cairn.storage.markdown import decode, encode
from cairn.transactions.apply import apply


def grant(ws, *, operations=None, expiry=None):
    set_grant(
        ws,
        RouteGrant(
            id="grant_finch",
            scope="research",
            provider="synthetic-agent",
            destination="https://synthetic.invalid",
            operations=operations or {"generation", "client_export"},
            valid_until=expiry or now() + timedelta(days=1),
            owner_consent="Synthetic Finch packet consent",
        ),
        base_hash=ws.policy_hash,
        statement="Synthetic Finch packet consent",
    )


def prepare(ws, tmp_path, *, with_grant=True, request_labels=True):
    if with_grant:
        grant(ws)
    paper = source(ws, processing="cloud_eligible")
    output = tmp_path / "packet.json"
    result = begin(
        ws,
        paper.id,
        output,
        scope_name="research",
        request="Explain the synthetic result.",
        request_labels=Labels(
            domain="research", classification="public", processing="cloud_eligible"
        )
        if request_labels
        else None,
        provider="synthetic-agent",
        destination="https://synthetic.invalid",
        inline_synthetic=True,
    )
    payload = json.loads(output.read_bytes())
    packet = FinchPacket.model_validate(payload["packet"])
    assert result["session_id"] == packet.id
    return packet


def returned(packet):
    ref = EvidenceRef(
        id=packet.source.id,
        source_hash=packet.extraction.source_hash,
        evidence_hash=packet.evidence_hash,
        locator=packet.extraction.segments[0].locator,
        quote="42",
    )
    return FinchResponse(
        session_id=packet.id,
        input_hash=digest(canonical(packet)),
        summary="The synthetic paper reports 42 under condition C.",
        claims=[
            FinchClaim(text="42 under condition C", kind="reported_result", sources=[ref]),
            FinchClaim(text="Changing C may change the result", kind="hypothesis"),
        ],
        messages=[
            ReceiptMessage(role="user", content="Explain this synthetic paper."),
            ReceiptMessage(role="assistant", content="42 under condition C; unreviewed."),
        ],
        unresolved=["Does this extend beyond C?"],
        limitations=["Synthetic excerpt only"],
    )


def response_file(tmp_path, value):
    path = tmp_path / "response.json"
    path.write_bytes(canonical(value))
    return path


def test_automatic_capture_proposal_validation_and_owner_apply(ws, tmp_path):
    ws.fs.write("vault/notes/research/owner.md", b"Immutable synthetic human note")
    packet = prepare(ws, tmp_path)
    exported = (tmp_path / "packet.json").read_bytes()
    assert b"owner.md" not in exported and b"protected_hashes" not in exported
    original_source = ws.fs.read(ws.record(packet.source.id)[0])
    file = response_file(tmp_path, returned(packet))
    receipt = finish(ws, file, inline_synthetic=True)
    proposal = load_proposal(ws, receipt.proposal_id)
    assert receipt.workflow_stage == "validated" and not receipt.processing_verified
    assert proposal.route == "cloud" and "interpretation" in proposal.review_flags
    assert ws.fs.read(f"blobs/{receipt.response_hash}") == file.read_bytes()
    assert ws.fs.read(ws.record(packet.source.id)[0]) == original_source
    assert ws.fs.read("vault/notes/research/owner.md") == b"Immutable synthetic human note"
    assert not ws.fs.files("approvals")
    assert not ws.fs.exists(proposal.changes[0].path)
    before = durable_contents(ws)
    assert finish(ws, file, inline_synthetic=True) == receipt
    assert durable_contents(ws) == before
    validate_payloads(before)
    with pytest.raises(Denied, match="approval"):
        apply(ws, proposal.id)
    approve(
        ws, proposal.id, acknowledgements=proposal.review_flags, statement="Synthetic owner review"
    )
    apply(ws, proposal.id)
    note, body = decode(ws.fs.read(proposal.changes[0].path))
    assert note.assertions[0].verification == "unreviewed"
    assert note.assertions[1].kind == "hypothesis"
    assert "condition C" in body
    validate_payloads(durable_contents(ws))


@pytest.mark.parametrize("mode", ["no_grant", "private_question", "export_only", "expired"])
def test_complete_request_grants_fail_closed(ws, tmp_path, mode, monkeypatch):
    if mode == "export_only":
        grant(ws, operations={"client_export"})
    elif mode == "expired":
        grant(ws)
        future = now() + timedelta(days=2)
        monkeypatch.setattr("cairn.policies.models.now", lambda: future)
    with pytest.raises(Denied):
        prepare(
            ws,
            tmp_path,
            with_grant=mode == "private_question",
            request_labels=mode != "private_question",
        )
    assert not (tmp_path / "packet.json").exists()


@pytest.mark.parametrize("mode", ["quote", "foreign_source", "authority", "input_hash"])
def test_bad_model_response_rejected_before_capture(ws, tmp_path, mode):
    packet = prepare(ws, tmp_path)
    value = returned(packet).model_dump(mode="json")
    if mode == "quote":
        value["claims"][0]["sources"][0]["quote"] = "fabricated 99"
    elif mode == "foreign_source":
        value["claims"][0]["sources"][0]["id"] = "source_foreign"
    elif mode == "authority":
        value["approved"] = True
    else:
        value["input_hash"] = "0" * 64
    before = durable_contents(ws)
    with pytest.raises((CairnError, ValidationError)):
        finish(ws, response_file(tmp_path, value), inline_synthetic=True)
    assert durable_contents(ws) == before


@pytest.mark.parametrize("mode", ["policy", "human_note", "source_blob"])
def test_stale_inputs_fail_at_handoff(ws, tmp_path, mode):
    ws.fs.write("vault/notes/research/owner.md", b"Synthetic human note")
    packet = prepare(ws, tmp_path)
    if mode == "policy":
        revoke_grant(ws, "grant_finch", base_hash=ws.policy_hash, statement="Synthetic revoke")
    elif mode == "human_note":
        ws.fs.write("vault/notes/research/owner.md", b"Owner revision")
    else:
        ws.fs.write(packet.source.source.blob, b"Changed immutable blob")
    with pytest.raises(Conflict):
        finish(ws, response_file(tmp_path, returned(packet)), inline_synthetic=True)
    assert not ws.fs.files("receipts/finch/imports")


def test_revocation_after_handoff_blocks_owner_approval(ws, tmp_path):
    packet = prepare(ws, tmp_path)
    receipt = finish(ws, response_file(tmp_path, returned(packet)), inline_synthetic=True)
    revoke_grant(ws, "grant_finch", base_hash=ws.policy_hash, statement="Synthetic revoke")
    with pytest.raises(Conflict):
        validate(ws, receipt.proposal_id)
    with pytest.raises(Conflict):
        approve(
            ws,
            receipt.proposal_id,
            acknowledgements={"interpretation"},
            statement="Synthetic review",
        )


def test_interrupted_handoff_retries_original_bytes(ws, tmp_path, monkeypatch):
    import cairn.reading.workflow as workflow

    packet = prepare(ws, tmp_path)
    original = returned(packet)
    file = response_file(tmp_path, original)
    real_stage = workflow.stage_result
    monkeypatch.setattr(
        workflow,
        "stage_result",
        lambda *args: (_ for _ in ()).throw(RuntimeError("Synthetic interruption")),
    )
    with pytest.raises(RuntimeError):
        finish(ws, file, inline_synthetic=True)
    changed = original.model_copy(update={"summary": "Different text"})
    with pytest.raises(Conflict, match="different response"):
        finish(ws, response_file(tmp_path, changed), inline_synthetic=True)
    monkeypatch.setattr(workflow, "stage_result", real_stage)
    receipt = finish(ws, response_file(tmp_path, original), inline_synthetic=True)
    assert receipt.response_hash == digest(canonical(original))


def test_concurrent_handoff_is_idempotent(ws, tmp_path):
    packet = prepare(ws, tmp_path)
    file = response_file(tmp_path, returned(packet))
    with ThreadPoolExecutor(max_workers=2) as executor:
        receipts = list(executor.map(lambda _: finish(ws, file, inline_synthetic=True), range(2)))
    assert receipts[0] == receipts[1]
    assert len(ws.fs.files("receipts/finch/imports")) == 1


def test_related_projects_inherit_labels_and_remain_immutable(ws, tmp_path):
    grant(ws)
    paper = source(ws, processing="cloud_eligible")
    project = Record(
        id="project_synthetic",
        type="project",
        domain="research",
        title="Synthetic study",
        classification="private",
        processing="cloud_eligible",
        created_at=now(),
        updated_at=now(),
    )
    path = "vault/wiki/research/project_synthetic.md"
    original = encode(project, "Owner project framing")
    ws.fs.write(path, original)
    output = tmp_path / "packet.json"
    begin(
        ws,
        paper.id,
        output,
        scope_name="research",
        request="Explain the result.",
        request_labels=Labels(
            domain="research", classification="public", processing="cloud_eligible"
        ),
        provider="synthetic-agent",
        destination="https://synthetic.invalid",
        related_ids=[project.id],
        inline_synthetic=True,
    )
    packet = FinchPacket.model_validate(json.loads(output.read_bytes())["packet"])
    receipt = finish(ws, response_file(tmp_path, returned(packet)), inline_synthetic=True)
    proposal = load_proposal(ws, receipt.proposal_id)
    note, _ = decode(proposal.changes[0].content.encode())
    assert note.classification == "private" and note.project_ids == [project.id]
    assert ws.fs.read(path) == original


def test_out_of_scope_related_context_denied(ws, tmp_path):
    grant(ws)
    paper = source(ws, processing="cloud_eligible")
    hidden = Record(
        id="project_hidden",
        type="project",
        domain="finance",
        title="Synthetic hidden",
        classification="public",
        processing="cloud_eligible",
        created_at=now(),
        updated_at=now(),
    )
    ws.fs.write("vault/wiki/finance/project_hidden.md", encode(hidden, "Hidden synthetic context"))
    with pytest.raises(Denied, match="unavailable"):
        begin(
            ws,
            paper.id,
            tmp_path / "denied.json",
            scope_name="research",
            request="Explain.",
            request_labels=Labels(
                domain="research", classification="public", processing="cloud_eligible"
            ),
            provider="synthetic-agent",
            destination="https://synthetic.invalid",
            related_ids=[hidden.id],
            inline_synthetic=True,
        )
    assert not (tmp_path / "denied.json").exists()


def test_backup_rejects_finch_receipt_corruption(ws, tmp_path):
    packet = prepare(ws, tmp_path)
    receipt = finish(ws, response_file(tmp_path, returned(packet)), inline_synthetic=True)
    payloads = durable_contents(ws)
    path = f"receipts/finch/imports/{packet.id}.json"
    payloads[path] = canonical(receipt.model_copy(update={"response_hash": "0" * 64}))
    with pytest.raises(Conflict, match="Finch import"):
        validate_payloads(payloads)


def test_submit_seals_and_stages_one_reading(ws, tmp_path):
    from cairn.reading.models import ReadingAnswer
    from cairn.reading.workflow import submit

    packet = prepare(ws, tmp_path)
    paper = packet.source
    answer = ReadingAnswer.model_validate(
        returned(packet).model_dump(include=set(ReadingAnswer.model_fields))
    )
    options = {
        "scope_name": "research",
        "request": "Explain the synthetic result.",
        "request_labels": Labels(domain="research", processing="cloud_eligible"),
        "provider": "synthetic-agent",
        "destination": "https://synthetic.invalid",
        "inline_synthetic": True,
    }
    receipt = submit(ws, paper.id, answer, **options)
    assert receipt.workflow_stage == "validated"
    assert submit(ws, paper.id, answer, **options) == receipt
    assert packet.skill_version == "cairn-1" and packet.guidance_hash == guidance_hash()


def test_contract_changes_never_strand_staged_proposals(ws, tmp_path, monkeypatch):
    packet = prepare(ws, tmp_path)
    receipt = finish(ws, response_file(tmp_path, returned(packet)), inline_synthetic=True)
    # A later release edits the contract; the staged proposal stays approvable.
    monkeypatch.setattr("cairn.reading.contract.guidance", lambda: "A different contract")
    proposed = validate(ws, receipt.proposal_id)
    approve(ws, proposed.id, acknowledgements=proposed.review_flags, statement="Owner review")
