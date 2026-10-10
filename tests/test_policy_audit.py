import json
from datetime import timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from cairn.cli import app
from cairn.errors import Conflict, Denied
from cairn.ingest.service import capture, extract
from cairn.policies.audit import (
    RequestPart,
    RouteAudit,
    RouteRequest,
    check_route,
    inspect_changes,
    revoke_grant,
    set_grant,
    set_scope,
)
from cairn.policies.models import Operation, RouteGrant, Scope
from cairn.proposals.service import approve, ingest, prepare_job, validate
from cairn.records.models import Labels, canonical, digest, now
from cairn.retrieval.search import query
from cairn.storage.backup import backup, restore
from cairn.storage.files import RootFS
from cairn.storage.workspace import Workspace


def grant(operation: Operation = "query") -> RouteGrant:
    return RouteGrant(
        id="grant_synthetic",
        scope="research",
        provider="synthetic-provider",
        destination="https://synthetic.invalid/process",
        operations={operation},
        valid_until=now() + timedelta(days=1),
        owner_consent="Synthetic scope consent.",
    )


def request(operation: Operation = "query") -> RouteRequest:
    eligible = Labels(domain="research", classification="public", processing="cloud_eligible")
    return RouteRequest(
        scope="research",
        route="cloud",
        provider="synthetic-provider",
        destination="https://synthetic.invalid/process",
        operation=operation,
        question="SYNTHETIC-QUESTION-CANARY",
        question_labels=eligible,
        parts=[
            RequestPart(role=role, content="SYNTHETIC-INSTRUCTION-CANARY", labels=eligible)
            for role in ("instructions", "derived_metadata", "output_handling", "traces")
        ],
    )


@pytest.mark.parametrize(
    "operation", ["generation", "extraction", "query", "context", "client_export"]
)
def test_entire_request_and_exact_grants(ws: Workspace, operation: Operation) -> None:
    candidate = request(operation)
    assert check_route(ws, candidate).decision == "denied"
    consent = grant(operation)
    set_grant(ws, consent, base_hash=ws.policy_hash, statement=consent.owner_consent)
    matching = check_route(ws, candidate)
    assert matching.decision == "blocked"
    assert matching.reason.startswith("cloud_adapter_unavailable")
    assert not matching.execution_performed
    assert matching.payload_hash == digest(canonical(candidate))
    raw = ws.fs.read(f"receipts/routes/{matching.id}.json")
    assert b"CANARY" not in raw

    for field, value in (
        ("provider", "different"),
        ("destination", "different"),
        ("scope", "life"),
        ("question_labels", None),
        ("operation", "query" if operation != "query" else "extraction"),
    ):
        modified = candidate.model_copy(deep=True)
        setattr(modified, field, value)
        assert check_route(ws, modified).decision == "denied"
    for index in range(4):
        modified = candidate.model_copy(deep=True)
        modified.parts[index].labels = None
        assert check_route(ws, modified).decision == "denied"
    for labels in (
        Labels(domain="research", processing="local_only"),
        Labels(domain="finance", processing="cloud_eligible"),
        Labels(domain="research", classification="restricted", processing="cloud_eligible"),
        Labels(domain="research", compartments={"secret"}, processing="cloud_eligible"),
    ):
        modified = candidate.model_copy(deep=True)
        modified.question_labels = labels
        assert check_route(ws, modified).decision == "denied"
    policy = ws.policy
    policy.cloud_grants[0].valid_until = now() - timedelta(seconds=1)
    ws.fs.write("policy/workspace.json", canonical(policy))
    assert check_route(ws, candidate).decision == "denied"


def test_scope_grant_schema_and_forged_widening(ws: Workspace) -> None:
    consent = grant()
    for updates in (
        {"valid_until": "2026-01-01T00:00:00"},
        {"owner_consent": " "},
        {"operations": []},
        {"destination": " "},
    ):
        with pytest.raises(ValidationError):
            RouteGrant.model_validate({**consent.model_dump(), **updates})
    with pytest.raises(Denied):
        set_grant(ws, consent, base_hash=ws.policy_hash, statement="Different consent")
    consent.valid_until = now() - timedelta(days=1)
    with pytest.raises(Denied):
        set_grant(ws, consent, base_hash=ws.policy_hash, statement=consent.owner_consent)
    wider = Scope(name="research", domains={"research", "finance"})
    with pytest.raises(Denied, match="widened"):
        ws.policy.authorize_route(wider, [], route="local", provider="fake", operation="query")
    with pytest.raises(Denied, match="remote destination"):
        ws.policy.authorize_route(
            ws.policy.scope("research"),
            [],
            route="local",
            provider="fake",
            operation="query",
            destination="https://invalid",
        )


def test_owner_changes_chain_stale_proposals_and_scope_revocation(
    ws: Workspace, tmp_path: Path
) -> None:
    file = tmp_path / "paper.txt"
    file.write_text("Synthetic evidence.")
    source = capture(ws, file, domain="research")
    proposal = ingest(ws, source.id, scope_name="research", inline_synthetic=True)
    assert proposal
    approve(
        ws, proposal.id, acknowledgements=proposal.review_flags, statement="Reviewed synthetic."
    )
    old = ws.policy_hash
    consent = grant()
    first = set_grant(ws, consent, base_hash=old, statement=consent.owner_consent)
    with pytest.raises(Conflict):
        validate(ws, proposal.id)
    with pytest.raises(Conflict):
        revoke_grant(ws, consent.id, base_hash=old, statement="Revoke synthetic.")
    second = set_scope(
        ws,
        ws.policy.scope("research"),
        base_hash=ws.policy_hash,
        statement="Review new membership and revoke related grants.",
    )
    assert not ws.policy.cloud_grants
    assert ws.policy.revision == 3
    assert {row["id"] for row in inspect_changes(ws)} == {first.id, second.id}
    assert all(row["state"] == "applied" for row in inspect_changes(ws))
    archive = tmp_path / "policy-backup.zip"
    backup(ws, archive)
    restored = restore(
        archive, tmp_path / "restored", code_roots=[tmp_path / "public-code"], synthetic=True
    )
    assert inspect_changes(restored) == inspect_changes(ws)
    ws.fs.remove(f"receipts/policy/{first.id}.json")
    with pytest.raises((FileNotFoundError, Conflict)):
        inspect_changes(ws)
    with pytest.raises((FileNotFoundError, Conflict)):
        set_scope(ws, ws.policy.scope("research"), base_hash=ws.policy_hash, statement="No repair.")


def test_policy_crash_has_unapplied_intent_and_exact_preimage(
    ws: Workspace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Existing version-one policies may have owner formatting and no audit history.
    ws.fs.write(
        "policy/workspace.json", json.dumps(ws.policy.model_dump(mode="json"), indent=2).encode()
    )
    original = ws.fs.read("policy/workspace.json")
    write = RootFS.write

    def fail(self: RootFS, path: str, data: bytes, **kwargs: object) -> None:
        if path == "policy/workspace.json":
            raise OSError("synthetic interrupted replace")
        write(self, path, data, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(RootFS, "write", fail)
        with pytest.raises(OSError):
            set_scope(
                ws, ws.policy.scope("research"), base_hash=ws.policy_hash, statement="Review."
            )
    assert ws.fs.read("policy/workspace.json") == original
    assert [row["state"] for row in inspect_changes(ws)] == ["unapplied_intent"]
    set_scope(ws, ws.policy.scope("research"), base_hash=ws.policy_hash, statement="Retry review.")
    assert sorted(row["state"] for row in inspect_changes(ws)) == ["applied", "unapplied_intent"]


def test_missing_scoped_inputs_are_audited_without_titles(ws: Workspace, tmp_path: Path) -> None:
    file = tmp_path / "finance.txt"
    file.write_text("SYNTHETIC-DENIED-CANARY")
    source = capture(ws, file, domain="finance", title="SYNTHETIC-DENIED-CANARY")
    candidate = request()
    candidate.record_ids = [source.id]
    audit = check_route(ws, candidate)
    assert audit.decision == "denied" and not audit.input_hashes
    assert b"CANARY" not in canonical(audit)
    candidate.scope = "missing"
    assert check_route(ws, candidate).decision == "denied"


def test_public_source_and_private_question_stay_local(ws: Workspace, tmp_path: Path) -> None:
    file = tmp_path / "public-paper.txt"
    file.write_text("Synthetic public paper evidence.")
    source = capture(
        ws, file, domain="research", classification="public", processing="cloud_eligible"
    )
    consent = grant()
    set_grant(ws, consent, base_hash=ws.policy_hash, statement=consent.owner_consent)
    candidate = request()
    candidate.record_ids = [source.id]
    assert check_route(ws, candidate).decision == "blocked"
    candidate.question_labels = Labels(domain="research", classification="private")
    assert check_route(ws, candidate).decision == "denied"
    local = capture(ws, file, domain="research", identity="local-paper", classification="public")
    candidate = request()
    candidate.record_ids = [local.id]
    assert check_route(ws, candidate).decision == "denied"


def test_processing_audits_and_read_only_query(ws: Workspace, tmp_path: Path) -> None:
    file = tmp_path / "paper.txt"
    file.write_text("Synthetic evidence.")
    source = capture(ws, file, domain="research")
    extract(ws, source.id, scope_name="research", inline_synthetic=True)
    job = prepare_job(ws, source.id, scope_name="research").job
    audits = [
        RouteAudit.model_validate_json(ws.fs.read(path)) for path in ws.fs.files("receipts/routes")
    ]
    assert {audit.operation for audit in audits} == {"extraction", "generation"}
    assert all(audit.decision == "allowed" and not audit.execution_performed for audit in audits)
    assert all(
        audit.payload_hash == digest(canonical(job))
        for audit in audits
        if audit.operation != "extraction"
    )
    before = ws.fs.files("receipts")
    result = query(ws, "evidence", scope_name="research")
    assert result["processing"]["remote_requests"] == 0
    assert ws.fs.files("receipts") == before


def test_policy_cli_inspect_change_check_and_revoke(ws: Workspace, tmp_path: Path) -> None:
    runner = CliRunner()

    def run(*args: str):
        return runner.invoke(app, ["policy", *args, "--workspace", str(ws.root), "--json"])

    state = run("show")
    assert state.exit_code == 0 and not json.loads(state.stdout)["cloud_execution_available"]
    scope_file = tmp_path / "scope.json"
    scope_file.write_bytes(canonical(ws.policy.scope("research")))
    changed = run(
        "set-scope",
        str(scope_file),
        "--base-hash",
        ws.policy_hash,
        "--statement",
        "Synthetic scope review.",
    )
    assert changed.exit_code == 0, changed.output
    consent = grant()
    grant_file = tmp_path / "grant.json"
    grant_file.write_bytes(canonical(consent))
    changed = run(
        "set-grant",
        str(grant_file),
        "--base-hash",
        ws.policy_hash,
        "--statement",
        consent.owner_consent,
    )
    assert changed.exit_code == 0, changed.output
    candidate = request()
    request_file = tmp_path / "request.json"
    request_file.write_bytes(canonical(candidate))
    checked = run("check-route", str(request_file))
    assert checked.exit_code == 5 and json.loads(checked.stdout)["decision"] == "blocked"
    revoked = run(
        "revoke-grant",
        consent.id,
        "--base-hash",
        ws.policy_hash,
        "--statement",
        "Revoke synthetic consent.",
    )
    assert revoked.exit_code == 0, revoked.output
    assert not ws.policy.cloud_grants
    assert len(json.loads(run("history").stdout)) == 3
