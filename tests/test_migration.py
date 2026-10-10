import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
from pydantic import ValidationError
from test_activation import reviewed_fixture as reviewed_fixture
from test_research_continuity import accept, session_file
from typer.testing import CliRunner

from cairn.cli import app
from cairn.errors import CairnError, Conflict, Denied, RecoveryRequired
from cairn.ingest.projects import create_project
from cairn.ingest.receipts import adopt_decision, import_receipt
from cairn.ingest.service import capture
from cairn.policies.audit import inspect_changes
from cairn.proposals.service import approve, ingest, validate
from cairn.records.models import canonical, digest
from cairn.retrieval.context import context_pack
from cairn.storage.backup import backup, durable_contents, restore
from cairn.storage.markdown import decode
from cairn.storage.migration import apply, inspect, preview, recover
from cairn.storage.workspace import Workspace
from cairn.transactions.apply import apply as apply_proposal


def legacy(ws: Workspace, *, omit_optional: bool = False) -> Workspace:
    data = ws.config.model_dump(mode="json")
    data.pop("record_schema_version")
    data["schema_version"] = 1
    if omit_optional:
        for key in ("worker_image", "runtime_release_hash", "runtime_approval_id"):
            data.pop(key)
    # Preserve an actual v1 shape, including noncanonical owner formatting.
    ws.fs.write("workspace.json", json.dumps(data, indent=2).encode())
    return Workspace(ws.root)


def migrate(ws: Workspace, tmp_path: Path):
    return apply(
        ws,
        plan_sha256=digest(canonical(preview(ws))),
        backup_path=tmp_path / "before-migration.zip",
        statement="Reviewed synthetic workspace format and pending-approval invalidation.",
    )


def test_inspection_and_legacy_reads_do_not_rewrite(ws: Workspace) -> None:
    assert inspect(ws)["workspace_schema"] == 2
    initial = ws.fs.read("workspace.json")
    missing_contract = json.loads(initial)
    missing_contract.pop("record_schema_version")
    ws.fs.write("workspace.json", canonical(missing_contract))
    with pytest.raises(ValidationError):
        Workspace(ws.root)
    ws.fs.write("workspace.json", initial)
    with pytest.raises(Conflict, match="already current"):
        preview(ws)
    ws = legacy(ws, omit_optional=True)
    before = durable_contents(ws)
    assert inspect(ws)["migration_available"] is True
    assert preview(ws) == preview(Workspace(ws.root))
    assert durable_contents(ws) == before
    for version in (0, 3, 999, True, "1"):
        data = json.loads(before["workspace.json"])
        data["schema_version"] = version
        raw = canonical(data)
        ws.fs.write("workspace.json", raw)
        with pytest.raises(Denied, match="unsupported workspace schema"):
            Workspace(ws.root)
        assert ws.fs.read("workspace.json") == raw


def test_migration_preserves_knowledge_backs_up_and_invalidates_pending_approval(
    ws: Workspace, tmp_path: Path
) -> None:
    ws = legacy(ws, omit_optional=True)
    source_file = tmp_path / "evidence.txt"
    source_file.write_text("Synthetic evidence is 12 units.")
    source = capture(ws, source_file, domain="research")
    proposal = ingest(ws, source.id, scope_name="research", inline_synthetic=True)
    assert proposal
    approve(ws, proposal.id, acknowledgements=proposal.review_flags, statement="Synthetic review.")
    before = durable_contents(ws)
    prior_reader = Workspace(ws.root)
    receipt = migrate(ws, tmp_path)
    with pytest.raises(Conflict, match="reopen"):
        inspect(prior_reader)
    assert ws.config.schema_version == 2
    assert ws.policy.revision == 2
    assert inspect_changes(ws) == [
        {"id": receipt.id, "operation": "schema_migration", "state": "applied"}
    ]
    for path, raw in before.items():
        if path not in receipt.files:
            assert ws.fs.read(path) == raw
    with zipfile.ZipFile(tmp_path / "before-migration.zip") as archive:
        assert {name: archive.read(name) for name in before} == before
    with pytest.raises(Conflict, match="policy"):
        validate(ws, proposal.id)
    with pytest.raises(Conflict):
        apply_proposal(ws, proposal.id)
    assert recover(ws) == []
    restored_old = restore(
        tmp_path / "before-migration.zip",
        tmp_path / "old-restored",
        code_roots=[tmp_path / "public-code"],
        synthetic=True,
    )
    assert restored_old.config.schema_version == 1
    assert not restored_old.fs.files("migrations")
    backup(ws, tmp_path / "current.zip")
    restored_new = restore(
        tmp_path / "current.zip",
        tmp_path / "current-restored",
        code_roots=[tmp_path / "public-code"],
        synthetic=True,
    )
    assert restored_new.config.schema_version == 2
    assert inspect_changes(restored_new) == inspect_changes(ws)


def test_stale_preview_backup_failure_and_unsupported_record_are_nonmutating(
    ws: Workspace, tmp_path: Path
) -> None:
    ws = legacy(ws)
    plan_hash = digest(canonical(preview(ws)))
    ws.fs.write("vault/notes/owner.md", b"Synthetic intervening owner note.")
    before = durable_contents(ws)
    with pytest.raises(Conflict, match="stale"):
        apply(ws, plan_sha256=plan_hash, backup_path=tmp_path / "stale.zip", statement="Review")
    assert durable_contents(ws) == before and not (tmp_path / "stale.zip").exists()
    destination = tmp_path / "occupied.zip"
    destination.write_bytes(b"Existing backup preserved.")
    with pytest.raises(Conflict):
        apply(
            ws,
            plan_sha256=digest(canonical(preview(ws))),
            backup_path=destination,
            statement="Review",
        )
    assert destination.read_bytes() == b"Existing backup preserved."
    assert durable_contents(ws) == before
    source_file = tmp_path / "evidence.txt"
    source_file.write_text("Synthetic evidence.")
    source = capture(ws, source_file, domain="research")
    path = f"vault/sources/{source.id}.md"
    ws.fs.write(path, ws.fs.read(path).replace(b"schema_version: 1", b"schema_version: 99"))
    before = durable_contents(ws)
    with pytest.raises(CairnError, match="invalid"):
        preview(ws)
    assert durable_contents(ws) == before


@pytest.mark.parametrize(
    "boundary",
    [
        "backup",
        "authorization",
        "policy_intent",
        "prepared",
        "write:0",
        "write:1",
        "receipt",
        "committed",
        "history",
    ],
)
def test_migration_process_crashes_and_recovery(
    ws: Workspace, tmp_path: Path, boundary: str
) -> None:
    ws = legacy(ws)
    ws.fs.write("vault/notes/owner.md", b"Preserved synthetic thinking.")
    before = durable_contents(ws)
    code = (
        "from pathlib import Path; import sys; from cairn.storage.workspace import Workspace; "
        "from cairn.storage.migration import apply; "
        "apply(Workspace(Path(sys.argv[1])), plan_sha256=sys.argv[2], "
        "backup_path=Path(sys.argv[3]), statement='Synthetic reviewed migration.')"
    )
    process = subprocess.run(
        [
            sys.executable,
            "-c",
            code,
            str(ws.root),
            digest(canonical(preview(ws))),
            str(tmp_path / "crash-backup.zip"),
        ],
        env={**os.environ, "CAIRN_TEST_CRASH_AT": f"migration:{boundary}"},
    )
    assert process.returncode == 77
    assert (tmp_path / "crash-backup.zip").exists()
    ws = Workspace(ws.root)
    if boundary in ("backup", "authorization", "policy_intent"):
        assert ws.config.schema_version == 1
        assert inspect(ws)["migration_available"]
        assert recover(ws) == []
        assert ws.fs.read("workspace.json") == before["workspace.json"]
        migrate(ws, tmp_path)
    else:
        if boundary not in ("committed", "history"):
            with pytest.raises(RecoveryRequired):
                inspect(ws)
            with pytest.raises(RecoveryRequired):
                backup(ws, tmp_path / "pending.zip", include_pending=True)
        recover(ws)
    assert Workspace(ws.root).config.schema_version == 2
    assert ws.fs.read("vault/notes/owner.md") == before["vault/notes/owner.md"]
    assert recover(Workspace(ws.root)) == []
    assert inspect(Workspace(ws.root))["migration_available"] is False
    receipt = next(p for p in ws.fs.files("migrations") if p.endswith("receipt.json"))
    migration_id = receipt.split("/")[1]
    maintenance = json.loads(ws.fs.read(f"receipts/maintenance/{migration_id}.json"))
    assert maintenance["history"] != "pending"


def test_recovery_rejects_owner_changes_and_journal_escalation(
    ws: Workspace, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = legacy(ws)

    def interrupt(_: Workspace, label: str) -> None:
        if label == "migration:write:0":
            raise OSError("synthetic loss of power")

    with monkeypatch.context() as patch:
        patch.setattr("cairn.storage.migration._crash", interrupt)
        with pytest.raises(OSError):
            migrate(ws, tmp_path)
    ws = Workspace(ws.root)
    path = "vault/notes/intervening.md"
    ws.fs.write(path, b"Preserve these synthetic owner bytes.")
    with pytest.raises(Conflict, match="owner bytes"):
        recover(ws)
    assert ws.fs.read(path) == b"Preserve these synthetic owner bytes."
    ws.fs.remove(path)
    authorization_path = next(
        p for p in ws.fs.files("migrations") if p.endswith("authorization.json")
    )
    original = ws.fs.read(authorization_path)
    auth = json.loads(original)
    changed = json.loads(auth["plan"]["after_config"])
    changed["code_roots"] = ["/synthetic-unapproved-root"]
    auth["plan"]["after_config"] = canonical(changed).decode()
    ws.fs.write(authorization_path, canonical(auth))
    with pytest.raises(Conflict, match="supported, approved transformation"):
        recover(ws)
    ws.fs.write(authorization_path, original)
    assert len(recover(ws)) == 1


def test_schema_cli_owner_preview_and_apply(ws: Workspace, tmp_path: Path) -> None:
    ws = legacy(ws)
    runner = CliRunner()

    def run(*args: str):
        return runner.invoke(app, ["schema", *args, "--workspace", str(ws.root), "--json"])

    assert json.loads(run("inspect").stdout)["workspace_schema"] == 1
    result = run("preview")
    assert result.exit_code == 0, result.output
    plan_hash = json.loads(result.stdout)["sha256"]
    result = run(
        "apply",
        "--plan-sha256",
        plan_hash,
        "--backup",
        str(tmp_path / "cli-backup.zip"),
        "--statement",
        "Synthetic owner migration review.",
    )
    assert result.exit_code == 0, result.output
    assert json.loads(run("inspect").stdout)["workspace_schema"] == 2
    assert json.loads(run("recover").stdout) == []


def test_migration_preserves_adopted_decision_and_historical_approval(
    ws: Workspace, tmp_path: Path
) -> None:
    ws = legacy(ws)
    created = create_project(
        ws,
        title="Synthetic migration continuity",
        question="Retain decisions?",
        objective="Keep evidence and adopted decisions.",
        constraints="Synthetic data only.",
        scope_name="research",
        inline_synthetic=True,
    )
    accept(ws, created)
    project = ws.record(created.changes[0].id)[1]
    imported = import_receipt(
        ws, session_file(tmp_path, project), scope_name="research", inline_synthetic=True
    )
    assert imported
    accept(ws, imported)
    decision = next(
        decode(change.content.encode())[0]
        for change in imported.changes
        if change.id.startswith("decision_")
    )
    adoption = adopt_decision(
        ws, decision.id, scope_name="research", statement="Retain exact locators."
    )
    assert adoption
    accept(ws, adoption)
    before = {
        path: raw
        for path, raw in durable_contents(ws).items()
        if path.startswith(("vault/", "evidence/", "blobs/", "approvals/", "receipts/applied/"))
    }
    first = context_pack(ws, project.id, question="Next?", budget=20000, scope_name="research")
    assert first.sections["current_decisions"]
    migrate(ws, tmp_path)
    after = context_pack(ws, project.id, question="Next?", budget=20000, scope_name="research")
    assert after.sections == first.sections
    for path, raw in before.items():
        assert ws.fs.read(path) == raw


def test_private_mode_migration_keeps_release_binding_and_rechecks_runtime(
    reviewed_fixture: dict, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Synthetic fixture with stubbed runtime checks, not a real private activation.
    ws = legacy(
        Workspace.init(
            tmp_path / "private-mode-fixture", code_roots=[tmp_path / "code"], **reviewed_fixture
        )
    )
    approval_id, release_hash = ws.config.runtime_approval_id, ws.config.runtime_release_hash
    plan_hash = digest(canonical(preview(ws)))
    before = durable_contents(ws)

    def unreviewed(*_: object) -> None:
        raise Denied("synthetic installed-byte mismatch")

    with monkeypatch.context() as patch:
        patch.setattr("cairn.storage.activation.verify_runtime", unreviewed)
        with pytest.raises(Denied, match="installed-byte mismatch"):
            apply(
                ws, plan_sha256=plan_hash, backup_path=tmp_path / "denied.zip", statement="Review"
            )
    assert durable_contents(ws) == before and not (tmp_path / "denied.zip").exists()
    migrate(ws, tmp_path)
    assert ws.config.runtime_release_hash == release_hash
    assert ws.config.runtime_approval_id == approval_id
    assert Workspace(ws.root).config.schema_version == 2


def test_migration_history_failure_is_retryable_after_commit(
    ws: Workspace, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = legacy(ws)

    def unavailable(*_: object) -> str:
        raise CairnError("Synthetic history unavailable")

    with monkeypatch.context() as patch:
        patch.setattr("cairn.storage.history.snapshot", unavailable)
        receipt = migrate(ws, tmp_path)
    path = f"receipts/maintenance/{receipt.id}.json"
    assert json.loads(ws.fs.read(path))["history"] == "pending"
    assert inspect(ws)["workspace_schema"] == 2
    assert recover(ws) == []
    assert json.loads(ws.fs.read(path))["history"] != "pending"


def test_backup_rejects_changed_migration_receipt(ws: Workspace, tmp_path: Path) -> None:
    ws = legacy(ws)
    receipt = migrate(ws, tmp_path)
    path = f"migrations/{receipt.id}/receipt.json"
    data = json.loads(ws.fs.read(path))
    data["authorization_hash"] = "0" * 64
    ws.fs.write(path, canonical(data))
    with pytest.raises(Conflict, match="receipt differs"):
        backup(ws, tmp_path / "invalid.zip")
    assert not (tmp_path / "invalid.zip").exists()


def test_migration_recovery_ignores_committed_library_journal(
    ws: Workspace, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from cairn.library.catalog import configure
    from cairn.library.models import LibraryConfig

    library_root = tmp_path / "synthetic-library"
    library_root.mkdir()
    configure(ws, LibraryConfig(root=str(library_root)))
    ws = legacy(ws)
    library_journals = [
        path
        for path in ws.fs.files("journal")
        if json.loads(ws.fs.read(path)).get("kind") == "library"
    ]
    assert library_journals

    def interrupt(_: Workspace, label: str) -> None:
        if label == "migration:write:0":
            raise OSError("synthetic loss of power")

    with monkeypatch.context() as patch:
        patch.setattr("cairn.storage.migration._crash", interrupt)
        with pytest.raises(OSError):
            migrate(ws, tmp_path)
    assert len(recover(Workspace(ws.root))) == 1
    assert Workspace(ws.root).config.schema_version == 2
