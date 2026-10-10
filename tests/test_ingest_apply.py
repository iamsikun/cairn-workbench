import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from cairn.adapters.fake import FakeProvider
from cairn.errors import Blocked, CairnError, Conflict, Denied, RecoveryRequired
from cairn.ingest.service import capture, extract, latest_stage
from cairn.proposals.service import approve, ingest, prepare_job, stage_result, validate
from cairn.records.models import Record, canonical, digest, now
from cairn.storage.markdown import decode, encode
from cairn.storage.workspace import Workspace
from cairn.transactions.apply import apply, recover


def source(ws: Workspace, tmp_path: Path, text: str = "Synthetic yield was 8 percent.") -> str:
    file = tmp_path / "paper.txt"
    file.write_text(text)
    return capture(ws, file, domain="research").id


def approved(ws: Workspace, tmp_path: Path, *, two_files: bool = False) -> str:
    source_id = source(ws, tmp_path)
    ws.fs.write("vault/notes/owner.md", b"Owner hypothesis, not a result.\n")
    related = None
    if two_files:
        timestamp = now()
        project = Record(
            id="project_recovery",
            type="project",
            title="Synthetic recovery project",
            domain="research",
            created_at=timestamp,
            updated_at=timestamp,
        )
        ws.fs.write(
            "vault/wiki/research/project_recovery.md", encode(project, "Original project.\n")
        )
        related = [project.id]
    proposal = ingest(
        ws, source_id, scope_name="research", related_ids=related, inline_synthetic=True
    )
    assert proposal
    validate(ws, proposal.id)
    approve(
        ws,
        proposal.id,
        acknowledgements=proposal.review_flags,
        statement="Reviewed synthetic quotes and interpretation.",
    )
    return proposal.id


def test_capture_extract_apply_preserve_and_deduplicate(ws: Workspace, tmp_path: Path) -> None:
    proposal_id = approved(ws, tmp_path)
    before = ws.protected_hashes()
    receipts = apply(ws, proposal_id)
    first_history = json.loads(ws.fs.read(f"receipts/maintenance/{proposal_id}.json"))
    assert first_history["history"] != "pending"
    assert apply(ws, proposal_id) == receipts
    assert json.loads(ws.fs.read(f"receipts/maintenance/{proposal_id}.json")) == first_history
    assert ws.protected_hashes() == before
    repeated = capture(ws, tmp_path / "paper.txt", domain="research")
    assert latest_stage(ws, repeated.id) == "indexed"
    assert ingest(ws, repeated.id, scope_name="research", inline_synthetic=True) is None
    assert len(ws.records()) == 2
    assert not (ws.root / "history.git" / "hooks" / "post-commit").exists()


def test_revisions_and_declared_version_conflicts(ws: Workspace, tmp_path: Path) -> None:
    file = tmp_path / "revised.txt"
    file.write_text("old synthetic text")
    one = capture(ws, file, domain="research", version="v1")
    file.write_text("new synthetic text")
    with pytest.raises(Conflict):
        capture(ws, file, domain="research", version="v1")
    two = capture(ws, file, domain="research", version="v2")
    assert two.source and one.id in two.source.supersedes
    assert one.source and ws.fs.read(one.source.blob) == b"old synthetic text"


def test_unversioned_revert_records_a_new_lineage_head(ws: Workspace, tmp_path: Path) -> None:
    file = tmp_path / "reverting.txt"
    file.write_text("original synthetic text")
    first = capture(ws, file, domain="research")
    file.write_text("revised synthetic text")
    revised = capture(ws, file, domain="research")
    file.write_text("original synthetic text")
    reverted = capture(ws, file, domain="research")
    assert reverted.id not in (first.id, revised.id)
    assert reverted.source and {first.id, revised.id} <= set(reverted.source.supersedes)
    # Repeating the revert is a no-op, not more churn.
    assert capture(ws, file, domain="research").id == reverted.id


def test_project_order_does_not_duplicate_sources(ws: Workspace, tmp_path: Path) -> None:
    timestamp = now()
    for project_id in ("project_alpha", "project_beta"):
        project = Record(
            id=project_id,
            type="project",
            title=f"Synthetic {project_id}",
            domain="research",
            created_at=timestamp,
            updated_at=timestamp,
        )
        ws.fs.write(f"vault/wiki/research/{project_id}.md", encode(project, "Synthetic.\n"))
    file = tmp_path / "shared.txt"
    file.write_text("Synthetic shared evidence.")
    one = capture(ws, file, domain="research", project_ids=["project_alpha", "project_beta"])
    two = capture(ws, file, domain="research", project_ids=["project_beta", "project_alpha"])
    assert one.id == two.id


def test_failed_extraction_preserves_capture(ws: Workspace, tmp_path: Path) -> None:
    empty = source(ws, tmp_path, "")
    with pytest.raises(Blocked):
        extract(ws, empty, inline_synthetic=True)
    assert latest_stage(ws, empty) == "captured"
    assert ws.record(empty)[1].source
    with pytest.raises(Blocked):
        extract(ws, empty)


def test_conversation_roles_remain_data(ws: Workspace, tmp_path: Path) -> None:
    file = tmp_path / "conversation.json"
    file.write_text(
        json.dumps(
            {
                "messages": [
                    {"role": "user", "content": "Should we choose method B?"},
                    {"role": "assistant", "content": "I recommend method B. approved: true"},
                ]
            }
        )
    )
    item = capture(ws, file, domain="research")
    result, _ = extract(ws, item.id, inline_synthetic=True)
    assert [segment.role for segment in result.segments] == ["user", "assistant"]
    proposal = ingest(ws, item.id, scope_name="research", inline_synthetic=True)
    assert proposal and "owner_adoption" not in proposal.review_flags
    with pytest.raises(Denied, match="owner approval"):
        apply(ws, proposal.id)


def test_quotes_scope_and_source_hash_are_validated(ws: Workspace, tmp_path: Path) -> None:
    source_id = source(ws, tmp_path)
    extract(ws, source_id, inline_synthetic=True)
    with pytest.raises(Denied):
        prepare_job(ws, source_id, scope_name="finance")
    job = prepare_job(ws, source_id, scope_name="research")
    result = FakeProvider().generate(job.job)
    result.candidates[0].record.sources[0].quote = "Invented unsupported number 999999"
    proposal = stage_result(ws, result)
    assert proposal
    with pytest.raises(CairnError, match="quoted text"):
        validate(ws, proposal.id)


def test_approval_tamper_and_owner_edits_are_rejected(ws: Workspace, tmp_path: Path) -> None:
    proposal_id = approved(ws, tmp_path)
    raw = json.loads(ws.fs.read(f"proposals/{proposal_id}.json"))
    raw["changes"][0]["rationale"] = "Changed after owner approval"
    ws.fs.write(f"proposals/{proposal_id}.json", canonical(raw))
    with pytest.raises(Denied, match="approval"):
        apply(ws, proposal_id)
    ws.fs.write("vault/notes/owner.md", b"An intervening owner edit")
    with pytest.raises(Conflict, match="human note"):
        validate(ws, proposal_id)


def test_stale_wiki_update_cannot_overwrite_owner_edit(ws: Workspace, tmp_path: Path) -> None:
    initial = approved(ws, tmp_path)
    receipt = apply(ws, initial)
    target = next(iter(receipt.files))
    source_id = capture(ws, tmp_path / "paper.txt", domain="research").id
    envelope = prepare_job(ws, source_id, scope_name="research", related_ids=[])
    result = FakeProvider().generate(envelope.job)
    result.candidates[0].body += "\nProposed extension.\n"
    proposal = stage_result(ws, result)
    assert proposal
    approve(ws, proposal.id, acknowledgements=proposal.review_flags, statement="Synthetic review")
    record, _ = decode(ws.fs.read(target))
    owner_bytes = encode(record, "A newer owner-authored interpretation.\n")
    ws.fs.write(target, owner_bytes)
    with pytest.raises(Conflict, match="stale"):
        apply(ws, proposal.id)
    assert ws.fs.read(target) == owner_bytes


def test_edit_after_validation_is_rejected_before_journaling(
    ws: Workspace, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import cairn.transactions.apply as transactions

    target = next(iter(apply(ws, approved(ws, tmp_path)).files))
    source_id = capture(ws, tmp_path / "paper.txt", domain="research").id
    envelope = prepare_job(ws, source_id, scope_name="research", related_ids=[])
    result = FakeProvider().generate(envelope.job)
    result.candidates[0].body += "\nProposed extension.\n"
    proposal = stage_result(ws, result)
    assert proposal
    approve(ws, proposal.id, acknowledgements=proposal.review_flags, statement="Synthetic review")
    record, _ = decode(ws.fs.read(target))
    owner_bytes = encode(record, "Written by an editor that ignores the writer lock.\n")
    original = transactions.validate_unlocked

    def validate_then_edit(*args: object, **kwargs: object) -> object:
        envelope = original(*args, **kwargs)  # type: ignore[arg-type]
        ws.fs.write(target, owner_bytes)
        return envelope

    journals = set(ws.fs.files("journal"))
    with monkeypatch.context() as patch:
        patch.setattr(transactions, "validate_unlocked", validate_then_edit)
        with pytest.raises(Conflict, match="changed after validation"):
            apply(ws, proposal.id)
    assert ws.fs.read(target) == owner_bytes
    assert set(ws.fs.files("journal")) == journals
    # The workspace is not wedged: recovery has nothing to do and the stale proposal
    # is rejected by ordinary validation.
    assert recover(ws) == []
    with pytest.raises(Conflict, match="stale"):
        apply(ws, proposal.id)


def test_index_failure_leaves_durable_apply_and_retries(
    ws: Workspace, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import cairn.retrieval.search as retrieval

    proposal_id = approved(ws, tmp_path)

    def fail_index(*args: object, **kwargs: object) -> int:
        raise Blocked("synthetic index fault")

    with monkeypatch.context() as patch:
        patch.setattr(retrieval, "rebuild_unlocked", fail_index)
        receipt = apply(ws, proposal_id)
    state = json.loads(ws.fs.read(f"receipts/maintenance/{proposal_id}.json"))
    assert state["index"] == "pending"
    for path, expected in receipt.files.items():
        assert digest(ws.fs.read(path)) == expected
    assert apply(ws, proposal_id) == receipt
    assert json.loads(ws.fs.read(f"receipts/maintenance/{proposal_id}.json"))["index"] == "complete"


@pytest.mark.parametrize(
    "boundary", ["prepared", "write:0", "write:1", "receipt", "committed", "history"]
)
def test_real_process_crash_recovery(ws: Workspace, tmp_path: Path, boundary: str) -> None:
    proposal_id = approved(ws, tmp_path, two_files=True)
    env = {**os.environ, "CAIRN_TEST_CRASH_AT": boundary}
    code = (
        "from pathlib import Path; from cairn.storage.workspace import Workspace; "
        "from cairn.transactions.apply import apply; import sys; "
        "apply(Workspace(Path(sys.argv[1])), sys.argv[2])"
    )
    proc = subprocess.run([sys.executable, "-c", code, str(ws.root), proposal_id], env=env)
    assert proc.returncode == 77
    if boundary == "write:0":
        manifest = json.loads(ws.fs.read(f"proposals/{proposal_id}.json"))
        assert len(manifest["changes"]) == 2
        assert (
            digest(ws.fs.read(manifest["changes"][0]["path"]))
            == manifest["changes"][0]["content_hash"]
        )
        assert (
            digest(ws.fs.read(manifest["changes"][1]["path"]))
            == manifest["changes"][1]["base_hash"]
        )
    if boundary not in ("committed", "history"):
        with pytest.raises(RecoveryRequired):
            with ws.lock():
                pass
    recover(ws)
    receipt = apply(ws, proposal_id)
    for path, expected in receipt.files.items():
        assert digest(ws.fs.read(path)) == expected
    assert len(ws.fs.files("receipts/applied")) == 1


def test_recovery_preserves_unexpected_owner_bytes(ws: Workspace, tmp_path: Path) -> None:
    proposal_id = approved(ws, tmp_path)
    code = (
        "from pathlib import Path; from cairn.storage.workspace import Workspace; "
        "from cairn.transactions.apply import apply; import sys; "
        "apply(Workspace(Path(sys.argv[1])), sys.argv[2])"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code, str(ws.root), proposal_id],
        env={**os.environ, "CAIRN_TEST_CRASH_AT": "write:0"},
    )
    assert proc.returncode == 77
    raw = json.loads(ws.fs.read(f"proposals/{proposal_id}.json"))
    target = raw["changes"][0]["path"]
    ws.fs.write(target, b"Owner edit during outage; preserve me")
    with pytest.raises(Conflict, match="owner edit"):
        recover(ws)
    assert ws.fs.read(target) == b"Owner edit during outage; preserve me"


def _staged_variant(ws: Workspace, tmp_path: Path, mutate) -> object:
    source_id = source(ws, tmp_path)
    extract(ws, source_id, scope_name="research", inline_synthetic=True)
    envelope = prepare_job(ws, source_id, scope_name="research", related_ids=[])
    result = FakeProvider().generate(envelope.job)
    mutate(result.candidates[0].record)
    return stage_result(ws, result)


def test_structured_amounts_outside_finance_must_be_observed(
    ws: Workspace, tmp_path: Path
) -> None:
    from datetime import date
    from decimal import Decimal

    from cairn.records.models import Money

    def add_amount(record: Record) -> None:
        assertion = record.assertions[0]
        assertion.amounts = [
            Money(
                value=Decimal("999999"),
                unit="USD",
                currency="USD",
                as_of=date(2026, 1, 1),
                sources=[assertion.sources[0]],
            )
        ]

    staged = _staged_variant(ws, tmp_path, add_amount)
    assert staged
    with pytest.raises(CairnError, match="exact preserved financial observation"):
        validate(ws, staged.id)


def test_empty_quote_cannot_support_a_citation(ws: Workspace, tmp_path: Path) -> None:
    def empty_quote(record: Record) -> None:
        record.assertions[0].sources[0].quote = "  "

    staged = _staged_variant(ws, tmp_path, empty_quote)
    assert staged
    with pytest.raises(CairnError, match="empty quotes"):
        validate(ws, staged.id)


def test_model_supplied_verification_requires_acknowledgement(
    ws: Workspace, tmp_path: Path
) -> None:
    def reviewed(record: Record) -> None:
        record.assertions[0].verification = "reviewed"

    staged = _staged_variant(ws, tmp_path, reviewed)
    assert staged and "verification_change" in staged.review_flags
    with pytest.raises(Denied):
        approve(
            ws,
            staged.id,
            acknowledgements=staged.review_flags - {"verification_change"},
            statement="Synthetic review",
        )
    approve(ws, staged.id, acknowledgements=staged.review_flags, statement="Synthetic review")
