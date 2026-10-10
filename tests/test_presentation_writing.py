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
    guidance,
    import_explanation,
    prepare,
    stored_explanation,
    submit_explanation,
)
from cairn.presentation.writing_models import (
    ExplanationBlock,
    ExplanationResponse,
)
from cairn.records.models import canonical, digest, now
from cairn.storage.backup import durable_contents, validate_payloads


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
    assert job.guidance == guidance() and "Preserve numbers" in job.guidance
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


def test_submit_explanation_keeps_it_for_owner_rendering(ws, tmp_path):
    from typer.testing import CliRunner

    from cairn.cli import app
    from cairn.presentation.writing_models import ExplanationAnswer
    from cairn.records.models import Labels

    grant(ws)
    record = source(ws, processing="cloud_eligible")
    bundle = assemble(ws, "evidence", scope="research", object_id=record.id)
    remember(ws, bundle, save=True)
    answer = ExplanationAnswer(
        blocks=[
            ExplanationBlock(
                text="The reported value is 42 under condition C.",
                kind="reported_result",
                evidence_keys=[bundle.evidence[0].key],
            )
        ]
    )
    options = {
        "request": "Explain the result.",
        "request_labels": Labels(domain="research", processing="cloud_eligible"),
        "provider": "synthetic-agent",
        "destination": "https://synthetic.invalid",
    }
    kept = submit_explanation(ws, bundle.id, answer, **options)
    assert submit_explanation(ws, bundle.id, answer, **options) == kept
    assert stored_explanation(ws, kept["job_id"]).blocks == answer.blocks
    output = tmp_path / "explained.html"
    rendered = CliRunner().invoke(
        app,
        [
            "view",
            "explanation",
            kept["job_id"],
            str(output),
            "--workspace",
            str(ws.root),
            "--inline-synthetic",
        ],
    )
    assert rendered.exit_code == 0, rendered.output
    assert "Generated explanation" in output.read_text()


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
