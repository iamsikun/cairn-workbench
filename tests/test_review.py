import json
from datetime import date
from pathlib import Path

from markdown_it import MarkdownIt
from typer.testing import CliRunner

from cairn.adapters.fake import FakeProvider
from cairn.cli import app
from cairn.ingest.service import capture_bytes, extract
from cairn.policies.audit import set_scope
from cairn.proposals.service import prepare_job, stage_result
from cairn.records.models import Period, canonical, digest
from cairn.storage.backup import durable_contents
from cairn.storage.workspace import Workspace


def proposal(ws: Workspace, text: str = "Synthetic value 42.", title: str = "Synthetic source"):
    source = capture_bytes(
        ws,
        text.encode(),
        origin="review.txt",
        domain="research",
        title=title,
        identity="review",
        source_type="text",
        source_date=date(2025, 1, 2),
        version="v1",
    )
    extract(ws, source.id, scope_name="research", inline_synthetic=True)
    job = prepare_job(ws, source.id, scope_name="research", related_ids=[]).job
    result = FakeProvider().generate(job)
    staged = stage_result(ws, result)
    assert staged
    return staged


def show(ws: Workspace, proposal_id: str, *options: str):
    return CliRunner().invoke(
        app, ["proposal", "show", proposal_id, "--workspace", str(ws.root), *options]
    )


def test_review_has_local_evidence_and_no_durable_writes(ws: Workspace) -> None:
    staged = proposal(ws)
    before = durable_contents(ws)
    report = show(ws, staged.id, "--markdown")
    assert report.exit_code == 0, report.output
    assert "Valid against current inputs" in report.stdout
    assert "2025-01-02" in report.stdout and "version: v1" in report.stdout
    assert "full_text" in report.stdout.replace("\\", "")
    assert "tables inspected: False" in report.stdout
    assert "[Evidence at line 1](<" in report.stdout
    assert "[Original bytes](<" in report.stdout and "[Source manifest](<" in report.stdout
    assert "presence, not entailment" in report.stdout
    assert digest(canonical(staged)) in report.stdout
    assert "current canonical files" in report.stdout
    assert durable_contents(ws) == before
    assert json.loads(show(ws, staged.id, "--json").stdout)["id"] == staged.id
    assert show(ws, staged.id, "--json", "--markdown").exit_code == 2


def test_markdown_cannot_activate_imported_html_links_or_fences(ws: Workspace) -> None:
    title = "![remote](https://synthetic.invalid/image)<img src='https://synthetic.invalid/img'>"
    text = "```\n<img src='https://synthetic.invalid'>\n```\n\x1b[31mSYNTHETIC\x1b[0m"
    staged = proposal(ws, text=text, title=title)
    report = show(ws, staged.id, "--markdown")
    assert report.exit_code == 0, report.output
    rendered = MarkdownIt("commonmark").render(report.stdout)
    assert "<img " not in rendered and 'href="https://' not in rendered
    assert "\x1b" not in report.stdout and "\\u001b" in report.stdout
    assert "&lt;img" in rendered


def test_review_recomputes_diff_and_reports_tampering(ws: Workspace) -> None:
    staged = proposal(ws)
    staged.changes[0].diff = "Misleading: no changes."
    ws.fs.write(f"proposals/{staged.id}.json", canonical(staged))
    report = show(ws, staged.id)
    assert report.exit_code == 0, report.output
    assert "Not valid for apply" in report.stdout
    assert "review diff does not match" in report.stdout
    assert "Misleading: no changes." not in report.stdout
    assert "+> Synthetic value 42." in report.stdout
    ws.fs.write(
        staged.changes[0].path, staged.changes[0].content.encode() + b"\nOwner amendment.\n"
    )
    report = show(ws, staged.id)
    assert report.exit_code == 0
    assert "Not valid for apply" in report.stdout and "stale" in report.stdout
    assert "-Owner amendment." in report.stdout


def test_review_denies_revoked_scope_without_title_or_content(ws: Workspace) -> None:
    staged = proposal(ws, text="SECRETREVIEW", title="SECRETREVIEW")
    scope = ws.policy.scope("research")
    scope.record_ids = {"source_not_granted"}
    set_scope(ws, scope, base_hash=ws.policy_hash, statement="Synthetic membership revocation.")
    for flag in ("--json", "--markdown"):
        report = show(ws, staged.id, flag)
        assert report.exit_code == 3, report.output
        assert "SECRETREVIEW" not in report.output


def test_review_links_reject_replaced_evidence_symlink(ws: Workspace, tmp_path: Path) -> None:
    staged = proposal(ws)
    blob = next(iter(ws.fs.files("blobs")))
    ws.fs.remove(blob)
    outside = tmp_path / "outside.txt"
    outside.write_text("Synthetic target must not be linked.")
    (ws.root / blob).symlink_to(outside)
    report = show(ws, staged.id, "--markdown")
    assert report.exit_code != 0
    assert "[Original bytes]" not in report.stdout
    assert "Synthetic target" not in report.output


def test_review_surfaces_dates_and_explicit_conflict(ws: Workspace) -> None:
    older = capture_bytes(
        ws,
        b"Synthetic Cedar result 8 percent.",
        origin="old.txt",
        domain="research",
        title="Cedar older",
        identity="old",
        source_type="text",
    )
    newer = capture_bytes(
        ws,
        b"Synthetic Cedar result 13 percent.",
        origin="new.txt",
        domain="research",
        title="Cedar newer",
        identity="new",
        source_type="text",
    )
    extract(ws, newer.id, scope_name="research", inline_synthetic=True)
    job = prepare_job(ws, newer.id, scope_name="research", related_ids=[older.id]).job
    result = FakeProvider().generate(job)
    record = result.candidates[0].record
    record.period = Period(as_of=date(2025, 3, 4))
    assertion = record.assertions[0]
    assertion.rationale = "Keep both contradictory estimates."
    assertion.disputes = [older.id]
    assertion.verification = "disputed"
    staged = stage_result(ws, result)
    assert staged
    report = show(ws, staged.id)
    assert report.exit_code == 0, report.output
    assert "conflicting_evidence" in report.stdout
    assert "Conflict:" in report.stdout and "disputes=" + older.id in report.stdout
    assert "Keep both contradictory estimates." in report.stdout
    assert "as of: 2025-03-04" in report.stdout
