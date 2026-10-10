"""Draft packets: the owner's agent drafts from one source; Cairn validates and stages."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from test_presentation import source
from test_presentation_writing import grant
from typer.testing import CliRunner

from cairn.adapters.fake import FakeProvider
from cairn.adapters.protocol import Job, Result
from cairn.cli import app
from cairn.errors import Conflict, Denied
from cairn.policies.audit import revoke_grant
from cairn.proposals import draft
from cairn.proposals.inbox import inbox
from cairn.proposals.service import approve, load_proposal
from cairn.records.models import Record, canonical
from cairn.storage.backup import durable_contents, validate_payloads
from cairn.storage.workspace import Workspace
from cairn.transactions.apply import apply

ROUTE = {"provider": "synthetic-agent", "destination": "https://synthetic.invalid"}


def begin(ws: Workspace, tmp_path: Path, source_id: str) -> tuple[dict, Job]:
    output = tmp_path / "packets" / "draft.json"
    result = draft.begin(ws, source_id, output, scope_name="research", **ROUTE)
    payload = json.loads(output.read_bytes())
    return result, Job.model_validate(payload["packet"])


def drafted(job: Job) -> Result:
    """Stand-in for the owner's agent: a deterministic extractive draft."""
    result = FakeProvider().generate(job)
    result.provider = job.provider
    return result


def respond(tmp_path: Path, result: Result, name: str = "response.json") -> Path:
    path = tmp_path / name
    path.write_bytes(canonical(result))
    return path


def test_draft_roundtrip_is_idempotent_reviewable_and_owner_applied(ws, tmp_path):
    grant(ws)
    paper = source(ws, processing="cloud_eligible")
    began, job = begin(ws, tmp_path, paper.id)
    payload = json.loads(Path(began["path"]).read_bytes())
    assert payload["guidance"] == draft.guidance()
    assert payload["response_schema"] == Result.model_json_schema()
    assert job.route == "cloud" and job.id.startswith("job_draft_")
    assert job.provider == "synthetic-agent" and job.execution_image is None
    assert begin(ws, tmp_path, paper.id)[0] == began
    assert [p.kind for p in inbox(ws).packets] == ["draft"]

    response = respond(tmp_path, drafted(job))
    receipt = draft.finish(ws, response)
    assert receipt.workflow_stage == "validated" and not receipt.processing_verified
    assert draft.finish(ws, response) == receipt
    assert not inbox(ws).packets
    proposed = load_proposal(ws, receipt.proposal_id)
    assert proposed.route == "cloud"
    assert [p.origin for p in inbox(ws).proposals] == ["draft"]
    # A finished packet cannot be answered again with different bytes.
    other = drafted(job)
    other.warnings = ["different"]
    with pytest.raises(Conflict):
        draft.finish(ws, respond(tmp_path, other, "other.json"))
    validate_payloads(durable_contents(ws))
    # Staging is not acceptance; approval and apply stay with the owner.
    assert not ws.fs.exists(f"approvals/{proposed.id}.json")
    approve(ws, proposed.id, acknowledgements=proposed.review_flags, statement="Owner review")
    apply(ws, proposed.id)
    assert ws.fs.exists(proposed.changes[0].path)


def test_draft_begin_requires_a_grant_and_cloud_eligible_inputs(ws, tmp_path):
    paper = source(ws, processing="cloud_eligible")
    with pytest.raises(Denied, match="grant"):
        begin(ws, tmp_path, paper.id)
    assert not ws.fs.files("receipts/drafts/exports")
    assert not (tmp_path / "packets").exists()
    grant(ws, operations={"generation"})
    with pytest.raises(Denied, match="grant"):
        begin(ws, tmp_path, paper.id)
    private = source(ws, text="Local-only synthetic note.", processing="local_only")
    grant_all = Workspace(ws.root)
    revoke_grant(grant_all, "grant_writing", base_hash=grant_all.policy_hash, statement="Reset")
    grant(grant_all)
    with pytest.raises(Denied, match="local-only"):
        begin(grant_all, tmp_path, private.id)


def test_revoked_grant_blocks_finish(ws, tmp_path):
    grant(ws)
    paper = source(ws, processing="cloud_eligible")
    _, job = begin(ws, tmp_path, paper.id)
    revoke_grant(ws, "grant_writing", base_hash=ws.policy_hash, statement="Revoke")
    with pytest.raises((Denied, Conflict)):
        draft.finish(ws, respond(tmp_path, drafted(job)))
    assert not ws.fs.files("receipts/drafts/finished")


@pytest.mark.parametrize(
    "forge",
    ["provider", "input_hash", "owner_decision", "reviewed", "decision_active", "source"],
)
def test_untrusted_draft_cannot_claim_owner_authority(ws, tmp_path, forge):
    grant(ws)
    paper = source(ws, processing="cloud_eligible")
    _, job = begin(ws, tmp_path, paper.id)
    result = drafted(job)
    record = result.candidates[0].record
    if forge == "provider":
        result.provider = "someone-else"
    elif forge == "input_hash":
        result.input_hash = "0" * 64
    elif forge == "owner_decision":
        record.assertions[0].kind = "owner_decision"
    elif forge == "reviewed":
        record.assertions[0].verification = "reviewed"
    elif forge == "decision_active":
        result.candidates[0].record = Record.model_validate(
            record.model_dump()
            | {
                "id": "decision_" + record.id.removeprefix("concept_"),
                "type": "decision",
                "status": "active",
            }
        )
    else:
        result.candidates[0].record = paper
    with pytest.raises(Denied):
        draft.finish(ws, respond(tmp_path, result))
    assert not ws.fs.files("receipts/drafts/finished")


def test_malformed_draft_is_rejected_without_side_effects(ws, tmp_path):
    grant(ws)
    paper = source(ws, processing="cloud_eligible")
    begin(ws, tmp_path, paper.id)
    bad = tmp_path / "bad.json"
    bad.write_text('{"job_id": "job_draft_x", "approved": true}')
    with pytest.raises(ValidationError):
        draft.finish(ws, bad)
    assert not ws.fs.files("receipts/drafts/responses")


def test_cli_draft_begin_finish_and_blocked_plain_ingest(ws, tmp_path):
    grant(ws)
    paper = source(ws, processing="cloud_eligible")
    runner = CliRunner()
    options = ["--workspace", str(ws.root)]
    packet = tmp_path / "packet.json"
    began = runner.invoke(
        app,
        [
            "draft",
            "begin",
            paper.id,
            "--output",
            str(packet),
            "--provider",
            ROUTE["provider"],
            "--destination",
            ROUTE["destination"],
            *options,
        ],
    )
    assert began.exit_code == 0, began.output
    job = Job.model_validate(json.loads(packet.read_bytes())["packet"])
    finished = runner.invoke(
        app, ["draft", "finish", str(respond(tmp_path, drafted(job))), *options]
    )
    assert finished.exit_code == 0, finished.output
    assert json.loads(finished.stdout)["workflow_stage"] == "validated"
    blocked = runner.invoke(app, ["ingest", paper.id, "--scope", "research", *options])
    assert blocked.exit_code == 5 and "draft begin" in blocked.output
    assert runner.invoke(app, ["client", "run", "--help"]).exit_code != 0
