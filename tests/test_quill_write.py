import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from test_presentation import source
from test_presentation_writing import grant
from typer.testing import CliRunner

from cairn.cli import app
from cairn.errors import Conflict, Denied
from cairn.policies.audit import revoke_grant
from cairn.presentation import quill
from cairn.presentation.service import assemble, remember
from cairn.presentation.writing import guidance, import_feedback
from cairn.presentation.writing_models import (
    Feedback,
    FeedbackEntry,
    NewTarget,
    QuillPacket,
    QuillResponse,
)
from cairn.proposals.accept import accept, plan
from cairn.proposals.inbox import inbox
from cairn.records.models import Labels, Record, canonical, digest, now
from cairn.storage.backup import durable_contents, validate_payloads
from cairn.storage.markdown import decode, encode
from cairn.storage.workspace import Workspace

SHAREABLE = Labels(domain="research", processing="cloud_eligible")
ROUTE = {"provider": "synthetic-agent", "destination": "https://synthetic.invalid"}


def vault(ws: Workspace) -> dict[str, bytes]:
    return {p: b for p, b in durable_contents(ws).items() if p.startswith("vault/")}


def begin(ws: Workspace, tmp_path: Path, **kwargs) -> QuillPacket:
    kwargs.setdefault("request_labels", SHAREABLE)
    out = quill.begin(
        ws,
        tmp_path / "packet.json",
        instructions=kwargs.pop("instructions", "Write a short concept page on the result."),
        scope_name="research",
        **ROUTE,
        **kwargs,
    )
    payload = json.loads((tmp_path / "packet.json").read_text())
    assert payload["input_hash"] == out["input_hash"]
    assert payload["guidance"] == guidance() and "Quill" in payload["guidance"]
    return QuillPacket.model_validate(payload["packet"])


def respond(tmp_path: Path, packet: QuillPacket, **fields) -> Path:
    value = {
        "packet_id": packet.id,
        "input_hash": digest(canonical(packet)),
        "body_markdown": "The synthetic study reports 42 under condition C.\n",
        "claims": [
            {
                "text": "The reported value is 42 under condition C.",
                "kind": "reported_result",
                "evidence_keys": ["ev1"],
                "quotations": [{"evidence_key": "ev1", "text": "42 under condition C"}],
            }
        ],
    } | fields
    file = tmp_path / "response.json"
    file.write_bytes(canonical(value))
    return file


def concept(ws: Workspace) -> str:
    timestamp = now()
    record = Record(
        id="concept_owner_page",
        type="concept",
        title="Owner page",
        domain="research",
        classification="private",
        processing="cloud_eligible",
        created_at=timestamp,
        updated_at=timestamp,
    )
    path = "vault/wiki/research/concept_owner_page.md"
    ws.fs.write(path, encode(record, "Owner draft.\n"))
    return path


def test_new_page_from_instructions_reaches_owner_accept(ws: Workspace, tmp_path: Path) -> None:
    grant(ws)
    paper = source(ws, processing="cloud_eligible")
    ws.fs.write("vault/notes/owner.md", b"Owner note.\n")
    packet = begin(
        ws,
        tmp_path,
        new=NewTarget(type="concept", domain="research", title="Result C"),
        from_ids=[paper.id],
    )
    assert [e.key for e in packet.evidence] == ["ev1"] and packet.target is None
    before = vault(ws)
    file = respond(tmp_path, packet)
    receipt = quill.finish(ws, file, inline_synthetic=True)
    assert quill.finish(ws, file, inline_synthetic=True) == receipt
    assert {p: b for p, b in vault(ws).items() if p in before} == before
    pending = inbox(ws)
    assert [(p.proposal_id, p.origin) for p in pending.proposals] == [
        (receipt.proposal_id, "quill")
    ]
    assert accept(ws, plan(ws, [receipt.proposal_id]))[0].status == "applied"
    _, record, body = ws.record("concept_quill_" + packet.id.removeprefix("quill_"))
    assert body == "The synthetic study reports 42 under condition C.\n"
    assert record.title == "Result C" and record.status == "draft"
    assert [(a.kind, a.verification) for a in record.assertions] == [
        ("reported_result", "unreviewed")
    ]
    assert record.assertions[0].sources[0].quote == "42 under condition C"
    assert ws.fs.read("vault/notes/owner.md") == b"Owner note.\n"
    validate_payloads(durable_contents(ws))
    respond(tmp_path, packet, limitations=["Different bytes"])
    with pytest.raises(Conflict):
        quill.finish(ws, file, inline_synthetic=True)


def test_revision_keeps_owner_state_and_rejects_stale_targets(
    ws: Workspace, tmp_path: Path
) -> None:
    grant(ws)
    paper = source(ws, processing="cloud_eligible")
    path = concept(ws)
    packet = begin(ws, tmp_path, target_id="concept_owner_page", from_ids=[paper.id])
    assert packet.target and packet.target.body == "Owner draft.\n"
    receipt = quill.finish(ws, respond(tmp_path, packet), inline_synthetic=True)
    items = plan(ws, [receipt.proposal_id])
    # An owner edit after the draft must not be overwritten.
    record, _ = decode(ws.fs.read(path))
    owner = encode(record, "Owner rewrite.\n")
    ws.fs.write(path, owner)
    assert accept(ws, items)[0].status == "failed"
    assert ws.fs.read(path) == owner
    second = begin(
        ws,
        tmp_path,
        target_id="concept_owner_page",
        from_ids=[paper.id],
        instructions="Tighten the page.",
    )
    ws.fs.write(path, encode(record, "Another owner edit.\n"))
    with pytest.raises(Conflict, match="changed"):
        quill.finish(ws, respond(tmp_path, second), inline_synthetic=True)
    ws.fs.write(path, owner)
    third = begin(
        ws,
        tmp_path,
        target_id="concept_owner_page",
        from_ids=[paper.id],
        instructions="Tighten the page again.",
    )
    done = quill.finish(ws, respond(tmp_path, third, title="Renamed"), inline_synthetic=True)
    assert accept(ws, plan(ws, [done.proposal_id]))[0].status == "applied"
    revised, body = decode(ws.fs.read(path))
    assert body.startswith("The synthetic study") and revised.title == "Renamed"
    assert revised.status == "draft" and revised.created_at == record.created_at


def test_fabrication_and_authority_fields_are_rejected(ws: Workspace, tmp_path: Path) -> None:
    grant(ws)
    paper = source(ws, processing="cloud_eligible")
    packet = begin(
        ws,
        tmp_path,
        new=NewTarget(type="concept", domain="research", title="X"),
        from_ids=[paper.id],
    )
    claim = {"text": "Value 99.", "kind": "reported_result", "evidence_keys": ["ev1"]}
    bad_quote = claim | {"quotations": [{"evidence_key": "ev1", "text": "Fabricated 99"}]}
    with pytest.raises(Denied, match="quote"):
        quill.finish(ws, respond(tmp_path, packet, claims=[bad_quote]), inline_synthetic=True)
    missing = claim | {"evidence_keys": ["ev9"]}
    with pytest.raises(Denied, match="unavailable"):
        quill.finish(ws, respond(tmp_path, packet, claims=[missing]), inline_synthetic=True)
    for forged in (
        {"claims": [claim | {"kind": "owner_decision"}]},
        {"approved": True},
        {"status": "active"},
        {"claims": [{"text": "Unsupported.", "kind": "reported_result"}]},
    ):
        with pytest.raises(ValidationError):
            quill.finish(ws, respond(tmp_path, packet, **forged), inline_synthetic=True)
    with pytest.raises(Denied, match="does not match"):
        quill.finish(ws, respond(tmp_path, packet, input_hash="0" * 64), inline_synthetic=True)
    assert not ws.fs.files("proposals/jobs")
    with pytest.raises(ValidationError):
        QuillResponse.model_validate({"packet_id": packet.id, "input_hash": "0" * 64})


def test_grants_labels_and_immutable_targets_fail_closed(ws: Workspace, tmp_path: Path) -> None:
    paper = source(ws, processing="cloud_eligible")
    new = NewTarget(type="concept", domain="research", title="X")
    with pytest.raises(Denied, match="grant"):
        begin(ws, tmp_path, new=new, from_ids=[paper.id])
    grant(ws)
    with pytest.raises(Denied, match="local-only"):
        begin(ws, tmp_path, new=new, from_ids=[paper.id], request_labels=None)
    private = source(ws, text="Local-only result 7.")
    with pytest.raises(Denied, match="local-only"):
        begin(ws, tmp_path, new=new, from_ids=[private.id])
    with pytest.raises(Denied, match="immutable"):
        begin(ws, tmp_path, target_id=paper.id)
    with pytest.raises(Denied):
        begin(ws, tmp_path, new=NewTarget(type="concept", domain="finance", title="X"))
    assert not (tmp_path / "packet.json").exists()


def test_revoked_grant_blocks_finish_and_accept(ws: Workspace, tmp_path: Path) -> None:
    grant(ws)
    paper = source(ws, processing="cloud_eligible")
    new = NewTarget(type="concept", domain="research", title="X")
    packet = begin(ws, tmp_path, new=new, from_ids=[paper.id])
    receipt = quill.finish(ws, respond(tmp_path, packet), inline_synthetic=True)
    revoke_grant(ws, "grant_writing", base_hash=ws.policy_hash, statement="Synthetic revoke")
    assert plan(ws, None)[0].status == "skipped"
    with pytest.raises(Conflict, match="policy"):
        plan(ws, [receipt.proposal_id])
    second = tmp_path / "second"
    second.mkdir()
    with pytest.raises(Denied):
        begin(ws, second, new=new, from_ids=[paper.id])


def test_feedback_comments_become_quill_instructions(ws: Workspace, tmp_path: Path) -> None:
    grant(ws)
    concept(ws)
    bundle = assemble(
        ws,
        "query",
        scope="research",
        question="Owner",
        question_labels=Labels(
            domain="research", classification="public", processing="cloud_eligible"
        ),
    )
    remember(ws, bundle)
    file = tmp_path / "feedback.json"
    file.write_bytes(
        canonical(
            Feedback(
                bundle_id=bundle.id,
                bundle_hash=digest(canonical(bundle)),
                entries=[FeedbackEntry(target_id="concept_owner_page", comment="Add context.")],
            )
        )
    )
    feedback = import_feedback(ws, file, inline_synthetic=True)
    packet = begin(ws, tmp_path, feedback_id=feedback.id, instructions="Address the feedback.")
    assert packet.target and packet.target.record.id == "concept_owner_page"
    assert "Comment: Add context." in packet.instructions
    assert packet.sources[0].id == feedback.source_id
    receipt = quill.finish(
        ws,
        respond(tmp_path, packet, claims=[], body_markdown="Owner draft with context.\n"),
        inline_synthetic=True,
    )
    assert accept(ws, plan(ws, [receipt.proposal_id]))[0].status == "applied"
    with pytest.raises(Denied, match="feedback"):
        begin(ws, tmp_path, feedback_id=feedback.id, target_id="concept_other")


def test_submit_maps_citations_and_refuses_stale_or_foreign_evidence(
    ws: Workspace, tmp_path: Path
) -> None:
    from cairn.presentation.writing_models import PageAnswer

    grant(ws)
    paper = source(ws, processing="cloud_eligible")
    path = concept(ws)
    base = digest(ws.fs.read(path))
    answer = PageAnswer.model_validate(
        {
            "body_markdown": "Owner draft, now citing 42 under condition C.\n",
            "claims": [
                {
                    "text": "The reported value is 42 under condition C.",
                    "kind": "reported_result",
                    "sources": [
                        {
                            "source_id": paper.id,
                            "locator": "line 1",
                            "quote": "42 under condition C",
                        }
                    ],
                }
            ],
        }
    )
    options = {
        "instructions": "Cite the synthetic result.",
        "scope_name": "research",
        "request_labels": SHAREABLE,
        "target_id": "concept_owner_page",
        "inline_synthetic": True,
        **ROUTE,
    }
    with pytest.raises(Conflict, match="changed since"):
        quill.submit(ws, answer, base_hash="0" * 64, **options)
    receipt = quill.submit(ws, answer, base_hash=base, **options)
    assert receipt.proposal_id and quill.submit(ws, answer, base_hash=base, **options) == receipt
    # A different answer to the same instructions seals a new packet, not a conflict.
    second = answer.model_copy(update={"body_markdown": "A second wording of 42 under C.\n"})
    assert quill.submit(ws, second, base_hash=base, **options).packet_id != receipt.packet_id
    foreign = answer.model_copy(deep=True)
    foreign.claims[0].sources[0].locator = "line 99"
    with pytest.raises(Denied, match="outside the supplied sources"):
        quill.submit(ws, foreign, base_hash=base, **options)
    assert accept(ws, plan(ws, [receipt.proposal_id]))[0].status == "applied"


def init_args(tmp_path: Path, *extra: str) -> list[str]:
    code = tmp_path / "public"
    code.mkdir(exist_ok=True)
    workspace = tmp_path / "private"
    return ["init", "--workspace", str(workspace), "--code-root", str(code), "--synthetic", *extra]


def test_setup_and_restore_never_install_or_edit_skills(ws: Workspace, tmp_path: Path) -> None:
    from cairn.storage.streaming_backup import backup

    home = tmp_path / "synthetic-home"
    (home / ".claude" / "skills").mkdir(parents=True)
    result = CliRunner().invoke(
        app, init_args(tmp_path), env={"HOME": str(home)}
    )
    assert result.exit_code == 0, result.output
    assert set(json.loads(result.stdout)) == {"workspace_id", "synthetic", "connect"}
    (tmp_path / "again").mkdir()
    removed = CliRunner().invoke(app, init_args(tmp_path / "again", "--no-quill"))
    assert removed.exit_code == 2  # The 0.1.x compatibility flags are gone.
    archive = tmp_path / "backup.zip"
    backup(ws, archive)
    code = tmp_path / "restore-code"
    code.mkdir()
    restored = CliRunner().invoke(
        app,
        [
            "restore",
            str(archive),
            "--destination",
            str(tmp_path / "restored"),
            "--code-root",
            str(code),
            "--synthetic",
            "--json",
        ],
        env={"HOME": str(home)},
    )
    assert restored.exit_code == 0, restored.output
    assert "quill" not in json.loads(restored.stdout)
    for root in (tmp_path / "private", tmp_path / "restored"):
        assert not (root / ".claude").exists()
    assert not any((home / ".claude" / "skills").iterdir())
    for retired in (["quill", "install"], ["finch", "install"], ["write", "begin"]):
        assert CliRunner().invoke(app, [*retired, "--help"]).exit_code != 0
