from datetime import timedelta

import pytest
from pydantic import ValidationError
from test_presentation import source

from cairn.errors import Blocked, Conflict, Denied
from cairn.policies.audit import revoke_grant, set_grant
from cairn.policies.models import RouteGrant
from cairn.presentation.service import assemble, remember
from cairn.presentation.writing import (
    explanation_html,
    export_packet,
    import_explanation,
    import_feedback,
    prepare,
    prepare_feedback,
    stage_feedback,
)
from cairn.presentation.writing_models import (
    ExplanationBlock,
    ExplanationResponse,
    Feedback,
    FeedbackEntry,
)
from cairn.records.models import EvidenceRef, Labels, Record, canonical, digest, now
from cairn.storage.backup import durable_contents, validate_payloads
from cairn.storage.markdown import encode


def grant(ws, operations=None):
    set_grant(
        ws,
        RouteGrant(
            id="grant_writing",
            scope="research",
            provider="synthetic-agent",
            destination="https://synthetic.invalid",
            operations=operations or {"generation", "client_export"},
            valid_until=now() + timedelta(days=1),
            owner_consent="Synthetic export consent",
        ),
        base_hash=ws.policy_hash,
        statement="Synthetic export consent",
    )


def prepared(ws, tmp_path):
    grant(ws)
    record = source(ws, processing="cloud_eligible")
    bundle = assemble(ws, "evidence", scope="research", object_id=record.id)
    remember(ws, bundle)
    job = prepare(
        ws,
        bundle.id,
        provider="synthetic-agent",
        route="cloud",
        destination="https://synthetic.invalid",
    )
    export_packet(ws, job.id, tmp_path / "packet.json")
    return job


def response(job):
    return ExplanationResponse(
        job_id=job.id,
        input_hash=digest(canonical(job)),
        blocks=[
            ExplanationBlock(
                text="The reported value is 42 under condition C.",
                kind="reported_result",
                evidence_keys=[job.bundle.evidence[0].key],
            )
        ],
    )


def test_quill_packet_roundtrip_and_no_canonical_changes(ws, tmp_path):
    job = prepared(ws, tmp_path)
    assert "Preserve scientific" in job.guidance and "supplied evidence" in job.guidance
    before = {p: b for p, b in durable_contents(ws).items() if p.startswith("vault/")}
    file = tmp_path / "response.json"
    file.write_bytes(canonical(response(job)))
    imported = import_explanation(ws, file)
    output = tmp_path / "explanation.html"
    explanation_html(ws, imported, output, inline_synthetic=True)
    assert "Generated explanation" in output.read_text() and "Unreviewed" in output.read_text()
    assert before == {p: b for p, b in durable_contents(ws).items() if p.startswith("vault/")}
    validate_payloads(durable_contents(ws))
    assert import_explanation(ws, file) == imported


def test_bad_quotes_references_and_authority_fields(ws, tmp_path):
    job = prepared(ws, tmp_path)
    value = response(job).model_dump(mode="json")
    value["blocks"][0]["quotations"] = [
        {"evidence_key": job.bundle.evidence[0].key, "text": "Fabricated 99"}
    ]
    file = tmp_path / "response.json"
    file.write_bytes(canonical(value))
    with pytest.raises(Denied, match="quote"):
        import_explanation(ws, file)
    value["blocks"][0]["quotations"] = []
    value["blocks"][0]["evidence_keys"] = ["evidence_missing"]
    file.write_bytes(canonical(value))
    with pytest.raises(Denied, match="unavailable"):
        import_explanation(ws, file)
    value["approved"] = True
    file.write_bytes(canonical(value))
    with pytest.raises(ValidationError):
        import_explanation(ws, file)


def test_export_grants_and_local_route_fail_closed(ws, tmp_path):
    grant(ws, {"client_export"})
    record = source(ws, processing="cloud_eligible")
    bundle = assemble(ws, "evidence", scope="research", object_id=record.id)
    remember(ws, bundle)
    job = prepare(
        ws,
        bundle.id,
        provider="synthetic-agent",
        route="cloud",
        destination="https://synthetic.invalid",
    )
    with pytest.raises(Denied, match="grant"):
        export_packet(ws, job.id, tmp_path / "denied.json")
    local = prepare(ws, bundle.id, provider="synthetic-agent")
    with pytest.raises(Blocked, match="local execution"):
        export_packet(ws, local.id, tmp_path / "local.json")
    assert not (tmp_path / "denied.json").exists()
    custom = prepare(
        ws,
        bundle.id,
        provider="synthetic-agent",
        route="cloud",
        destination="https://synthetic.invalid",
        request="Private question",
    )
    with pytest.raises(Denied, match="local-only"):
        export_packet(ws, custom.id, tmp_path / "private.json")


def test_revoked_grant_rejects_response(ws, tmp_path):
    job = prepared(ws, tmp_path)
    file = tmp_path / "response.json"
    file.write_bytes(canonical(response(job)))
    revoke_grant(ws, "grant_writing", base_hash=ws.policy_hash, statement="Synthetic revoke")
    with pytest.raises(Conflict, match="policy changed"):
        import_explanation(ws, file)


def test_feedback_proposal_requires_owner_approval_and_rejects_stale(ws, tmp_path):
    from cairn.ingest.service import load_extraction
    from cairn.proposals.service import approve, validate
    from cairn.transactions.apply import apply

    grant(ws)
    record = source(ws, processing="cloud_eligible")
    _, full_source, _ = ws.record(record.id)
    extraction, key = load_extraction(ws, full_source)
    ref = EvidenceRef(
        id=record.id,
        source_hash=extraction.source_hash,
        evidence_hash=key,
        locator=extraction.segments[0].locator,
    )
    concept = Record(
        id="concept_example",
        type="concept",
        title="Synthetic concept",
        domain="research",
        classification="public",
        processing="cloud_eligible",
        compartments={"research"},
        created_at=now(),
        updated_at=now(),
        sources=[ref],
    )
    path = "vault/wiki/research/concept_example.md"
    ws.fs.write(path, encode(concept, "Synthetic value 42."))
    bundle = assemble(
        ws,
        "query",
        scope="research",
        question="Synthetic",
        question_labels=Labels(
            domain="research", classification="public", processing="cloud_eligible"
        ),
    )
    remember(ws, bundle)
    file = tmp_path / "feedback.json"
    value = Feedback(
        bundle_id=bundle.id,
        bundle_hash=digest(canonical(bundle)),
        entries=[
            FeedbackEntry(
                target_id=concept.id,
                comment="Keep the condition attached to the value.",
                suggested_text="Synthetic value 42 under condition C.",
            )
        ],
    )
    file.write_bytes(canonical(value))
    receipt = import_feedback(ws, file, inline_synthetic=True)
    assert import_feedback(ws, file, inline_synthetic=True) == receipt
    job = prepare_feedback(
        ws,
        receipt.id,
        provider="synthetic-agent",
        route="cloud",
        destination="https://synthetic.invalid",
    )
    export_packet(ws, job.id, tmp_path / "revision-packet.json")
    candidate = job.revision.related[0].model_dump(mode="json")
    candidate["body"] = "Synthetic value 42 under condition C."
    candidate["rationale"] = "Preserve the condition stated by the source."
    file.write_bytes(
        canonical(
            {
                "schema_version": 1,
                "job_id": job.id,
                "input_hash": digest(canonical(job)),
                "candidates": [candidate],
            }
        )
    )
    before = ws.fs.read(path)
    # Returned prose cannot declare new authoritative state, even for a selected target.
    original_response = file.read_bytes()
    import json

    forged = json.loads(original_response)
    forged["candidates"][0]["record"]["status"] = "active"
    file.write_bytes(canonical(forged))
    with pytest.raises(Denied, match="authoritative"):
        stage_feedback(ws, file)
    forged = json.loads(original_response)
    forged["candidates"][0]["record"]["sources"][0]["locator"] = "line 999"
    file.write_bytes(canonical(forged))
    with pytest.raises(Denied, match="outside the supplied packet"):
        stage_feedback(ws, file)
    file.write_bytes(original_response)
    proposal = stage_feedback(ws, file)
    assert stage_feedback(ws, file) == proposal
    assert proposal and proposal.route == "cloud"
    assert ws.fs.read(path) == before
    validate(ws, proposal.id)
    with pytest.raises(Denied):
        apply(ws, proposal.id)
    approve(ws, proposal.id, acknowledgements=proposal.review_flags, statement="Synthetic approval")
    apply(ws, proposal.id)
    assert "condition C" in ws.fs.read(path).decode()
    with pytest.raises(Conflict):
        stage_feedback(ws, file)
    validate_payloads(durable_contents(ws))


def test_comments_only_and_immutable_targets(ws, tmp_path):
    record = source(ws)
    bundle = assemble(ws, "evidence", scope="research", object_id=record.id)
    remember(ws, bundle)
    value = Feedback(
        bundle_id=bundle.id,
        bundle_hash=digest(canonical(bundle)),
        entries=[FeedbackEntry(target_id=record.id, comment="Inspect this result.")],
    )
    file = tmp_path / "feedback.json"
    file.write_bytes(canonical(value))
    receipt = import_feedback(ws, file, inline_synthetic=True)
    with pytest.raises(Blocked, match="comments only"):
        prepare_feedback(ws, receipt.id, provider="synthetic-agent")
    value.entries[0].suggested_text = "Rewrite source"
    file.write_bytes(canonical(value))
    receipt = import_feedback(ws, file, inline_synthetic=True)
    with pytest.raises(Denied, match="immutable"):
        prepare_feedback(ws, receipt.id, provider="synthetic-agent")


def test_question_labels_and_tampered_saved_excerpt(ws, tmp_path):
    from cairn.presentation.service import identity

    grant(ws)
    record = source(ws, processing="cloud_eligible")
    bundle = assemble(ws, "query", scope="research", question="Synthetic result")
    remember(ws, bundle)
    job = prepare(
        ws,
        bundle.id,
        provider="synthetic-agent",
        route="cloud",
        destination="https://synthetic.invalid",
    )
    with pytest.raises(Denied):
        export_packet(ws, job.id, tmp_path / "private-question.json")
    assert not (tmp_path / "private-question.json").exists()
    bundle = assemble(ws, "evidence", scope="research", object_id=record.id)
    bundle.evidence[0].text = "Fabricated 999"
    bundle.id = identity(bundle)
    ws.fs.write(f"receipts/presentation/views/{bundle.id}.json", canonical(bundle))
    with pytest.raises(Conflict, match="evidence text"):
        validate_payloads(durable_contents(ws))
