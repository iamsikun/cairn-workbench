import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cairn.cli import app
from cairn.errors import Conflict, Denied
from cairn.ingest.service import capture
from cairn.proposals.accept import accept, plan
from cairn.proposals.service import approve, ingest
from cairn.records.models import canonical
from cairn.storage.markdown import decode, encode
from cairn.storage.workspace import Workspace
from cairn.transactions.apply import apply, recover


def proposed(
    ws: Workspace, tmp_path: Path, name: str, text: str, classification: str = "private"
) -> str:
    file = tmp_path / f"{name}.txt"
    file.write_text(text)
    source = capture(ws, file, domain="research", classification=classification)
    scope = "owner" if classification == "restricted" else "research"
    proposal = ingest(ws, source.id, scope_name=scope, inline_synthetic=True)
    assert proposal
    return proposal.id


def test_accept_one_and_batch_are_idempotent(ws: Workspace, tmp_path: Path) -> None:
    ws.fs.write("vault/notes/owner.md", b"Synthetic owner note.\n")
    first = proposed(ws, tmp_path, "one", "Synthetic yield was 8 percent.")
    second = proposed(ws, tmp_path, "two", "Synthetic margin was 3 percent.")
    before = ws.protected_hashes()
    results = accept(ws, plan(ws, [first]))
    assert [r.status for r in results] == ["applied"]
    approval = json.loads(ws.fs.read(f"approvals/{first}.json"))
    assert approval["owner_statement"] == "Owner accepted via cairn accept"
    batch = plan(ws, None)
    assert [(i.proposal_id, i.status) for i in batch] == [(second, "ready")]
    assert [r.status for r in accept(ws, batch)] == ["applied"]
    again = plan(ws, [first, second])
    assert {i.status for i in again} == {"applied"}
    assert all(r.receipt_id is None for r in accept(ws, again))
    assert ws.protected_hashes() == before


def test_batch_skips_sensitive_and_requires_explicit_choice(ws: Workspace, tmp_path: Path) -> None:
    sensitive = proposed(ws, tmp_path, "s", "Synthetic restricted value 5.", "restricted")
    items = plan(ws, None)
    assert [(i.status, i.reason) for i in items] == [
        ("skipped", "requires explicit owner selection")
    ]
    assert accept(ws, items)[0].receipt_id is None
    assert not ws.fs.exists(f"approvals/{sensitive}.json")
    explicit = plan(ws, [sensitive])
    assert explicit[0].status == "ready" and "sensitive_record" in explicit[0].review_flags
    assert accept(ws, explicit)[0].status == "applied"


def test_stale_item_stops_batch_and_keeps_earlier_applies(ws: Workspace, tmp_path: Path) -> None:
    ws.fs.write("vault/notes/owner.md", b"Synthetic owner note.\n")
    first = proposed(ws, tmp_path, "one", "Synthetic yield was 8 percent.")
    second = proposed(ws, tmp_path, "two", "Synthetic margin was 3 percent.")
    third = proposed(ws, tmp_path, "three", "Synthetic ratio was 2 percent.")
    items = plan(ws, None)
    # The owner edits a protected note after the preview; later proposals become stale.
    ws.fs.write("vault/notes/owner.md", b"Owner edit after preview.\n")
    results = accept(ws, items)
    assert [r.status for r in results] == ["failed", "not_attempted", "not_attempted"]
    assert results[0].reason and results[0].reason.startswith("conflict")
    assert not ws.fs.exists(f"receipts/applied/{first}.json")
    # Stale proposals are listed rather than blocking the rest of a later batch.
    assert {i.status for i in plan(ws, None)} == {"skipped"}
    with pytest.raises(Conflict):
        plan(ws, [second])
    assert not ws.fs.exists(f"approvals/{third}.json")


def test_partial_batch_failure_preserves_applied_items(ws: Workspace, tmp_path: Path) -> None:
    first = proposed(ws, tmp_path, "one", "Synthetic yield was 8 percent.")
    second = proposed(ws, tmp_path, "two", "Synthetic margin was 3 percent.")
    items = plan(ws, None)
    # Tamper with the second proposal after preview: it must fail, the first stays applied.
    raw = json.loads(ws.fs.read(f"proposals/{second}.json"))
    raw["review_flags"] = [*raw["review_flags"], "owner_adoption"]
    ws.fs.write(f"proposals/{second}.json", canonical(raw))
    results = accept(ws, items)
    assert [r.status for r in results] == ["applied", "failed"]
    assert ws.fs.exists(f"receipts/applied/{first}.json")
    assert not ws.fs.exists(f"receipts/applied/{second}.json")


def test_owner_edit_after_preview_is_not_overwritten(ws: Workspace, tmp_path: Path) -> None:
    first = proposed(ws, tmp_path, "one", "Synthetic yield was 8 percent.")
    receipt = apply_after_accept(ws, first)
    target = next(iter(receipt))
    file = tmp_path / "one.txt"
    file.write_text("Synthetic yield was 9 percent.")
    update = ingest(
        ws, capture(ws, file, domain="research").id, scope_name="research", inline_synthetic=True
    )
    assert update
    items = plan(ws, [update.id])
    record, _ = decode(ws.fs.read(target))
    owner = encode(record, "Owner rewrite.\n")
    ws.fs.write(target, owner)
    assert accept(ws, items)[0].status == "failed"
    assert ws.fs.read(target) == owner


def apply_after_accept(ws: Workspace, proposal_id: str) -> dict[str, str]:
    result = accept(ws, plan(ws, [proposal_id]))[0]
    assert result.status == "applied"
    return json.loads(ws.fs.read(f"receipts/applied/{proposal_id}.json"))["files"]


def test_model_supplied_approval_grants_nothing(ws: Workspace, tmp_path: Path) -> None:
    proposal_id = proposed(ws, tmp_path, "one", "Synthetic yield was 8 percent.")
    raw = json.loads(ws.fs.read(f"proposals/{proposal_id}.json"))
    original = ws.fs.read(f"proposals/{proposal_id}.json")
    ws.fs.write(f"proposals/{proposal_id}.json", canonical({**raw, "approved": True}))
    with pytest.raises(ValueError):
        plan(ws, [proposal_id])
    ws.fs.write(f"proposals/{proposal_id}.json", original)
    assert not ws.fs.exists(f"approvals/{proposal_id}.json")
    with pytest.raises(Denied):
        accept(ws, plan(ws, []), statement="   ")
    with pytest.raises(ValueError):
        flags = set(plan(ws, [proposal_id])[0].review_flags)
        approve(ws, proposal_id, acknowledgements=flags, statement=" ")


def test_cli_accept_requires_confirmation(tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()
    workspace, code = tmp_path / "private", tmp_path / "public"
    code.mkdir()
    assert (
        runner.invoke(
            app, ["init", "--workspace", str(workspace), "--code-root", str(code), "--synthetic"]
        ).exit_code
        == 0
    )
    file = tmp_path / "sample.txt"
    file.write_text("Synthetic evidence: exact value 42.")
    options = ["--workspace", str(workspace)]
    source_id = json.loads(
        runner.invoke(
            app, ["capture", str(file), "--domain", "research", *options, "--json"]
        ).stdout
    )["id"]
    staged = runner.invoke(
        app, ["ingest", source_id, "--scope", "research", "--inline-synthetic", *options, "--json"]
    )
    proposal_id = json.loads(staged.stdout)["id"]
    assert runner.invoke(app, ["accept", *options]).exit_code == 2
    # Without the owner's terminal (an agent's shell), acceptance is refused.
    monkeypatch.delenv("CAIRN_SYNTHETIC_OWNER")
    monkeypatch.setattr("cairn.cli.commands._terminal", no_terminal)
    refused = runner.invoke(app, ["accept", "--all", *options])
    assert refused.exit_code == 3 and "run it yourself in a terminal" in refused.output
    assert proposal_id in refused.output
    assert runner.invoke(app, ["accept", "--all", "--yes", *options]).exit_code == 2
    monkeypatch.setattr("cairn.cli.commands._terminal", terminal("nope"))
    assert runner.invoke(app, ["accept", "--all", *options]).exit_code == 3
    monkeypatch.setattr("cairn.cli.commands._terminal", terminal("accept"))
    done = runner.invoke(app, ["accept", "--all", *options, "--json"])
    assert done.exit_code == 0, done.output
    assert json.loads(done.stdout)[0]["status"] == "applied"
    monkeypatch.setenv("CAIRN_SYNTHETIC_OWNER", "1")
    found = runner.invoke(app, ["search", "42", "--scope", "research", *options, "--json"])
    assert any(hit["kind"] == "synthesis" for hit in json.loads(found.stdout))
    assert runner.invoke(app, ["apply", proposal_id, *options]).exit_code == 0


def no_terminal():
    raise OSError(6, "Device not configured")


def terminal(answer: str):
    """A pseudo-terminal where the owner types `answer`."""

    def opener():
        main, secondary = os.openpty()
        os.write(main, answer.encode() + b"\n")
        return secondary

    return opener


def test_owner_terminal_is_required_for_real_knowledge_bases(monkeypatch) -> None:
    from types import SimpleNamespace

    from cairn.cli.commands import owner_confirm

    real = SimpleNamespace(config=SimpleNamespace(synthetic=False))
    monkeypatch.setattr("cairn.cli.commands._terminal", no_terminal)
    # The synthetic test override is ignored for a real knowledge base.
    with pytest.raises(Denied, match="owner command"):
        owner_confirm(real, "approve", "Approve.")  # type: ignore[arg-type]
    monkeypatch.setattr("cairn.cli.commands._terminal", terminal("approve"))
    owner_confirm(real, "approve", "Approve.")  # type: ignore[arg-type]


def test_explicit_apply_still_requires_approval(ws: Workspace, tmp_path: Path) -> None:
    proposal_id = proposed(ws, tmp_path, "one", "Synthetic yield was 8 percent.")
    with pytest.raises(Denied, match="owner approval"):
        apply(ws, proposal_id)


def test_crash_during_batch_recovers_and_resumes(ws: Workspace, tmp_path: Path) -> None:
    first = proposed(ws, tmp_path, "one", "Synthetic yield was 8 percent.")
    second = proposed(ws, tmp_path, "two", "Synthetic margin was 3 percent.")
    code = (
        "from pathlib import Path; from cairn.storage.workspace import Workspace; "
        "from cairn.proposals.accept import accept, plan; import sys; "
        "ws = Workspace(Path(sys.argv[1])); accept(ws, plan(ws, None))"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code, str(ws.root)],
        env={**os.environ, "CAIRN_TEST_CRASH_AT": "prepared"},
    )
    assert proc.returncode == 77
    assert [r.proposal_id for r in recover(ws)] == [first]
    assert not ws.fs.exists(f"approvals/{second}.json")
    results = accept(ws, plan(ws, None))
    assert [(r.proposal_id, r.status) for r in results] == [(second, "applied")]
