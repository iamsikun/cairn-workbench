import json
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cairn.cli import app
from cairn.errors import Denied
from cairn.ingest.service import capture, extract
from cairn.proposals.service import approve, ingest
from cairn.records.models import EvidenceRef, Record, canonical, now
from cairn.retrieval.search import backlinks, query, rebuild_index, search
from cairn.storage.markdown import encode
from cairn.storage.workspace import Workspace
from cairn.transactions.apply import apply


def test_scoped_search_no_counts_titles_or_ranking_leaks(ws: Workspace, tmp_path: Path) -> None:
    paper = tmp_path / "public-example.txt"
    paper.write_text("The evidence supports retrieval, subject to review.")
    source = capture(ws, paper, domain="research")
    proposal = ingest(ws, source.id, scope_name="research", inline_synthetic=True)
    assert proposal
    approve(ws, proposal.id, acknowledgements=proposal.review_flags, statement="Synthetic review")
    apply(ws, proposal.id)
    before = search(ws, "evidence", scope_name="research")
    secret = tmp_path / "secret-fixture.txt"
    secret.write_text("SECRET-ACCOUNT-TITLE evidence evidence evidence 9999999.")
    denied = capture(ws, secret, domain="finance", title="SECRET-ACCOUNT-TITLE")
    extract(ws, denied.id, scope_name="finance", inline_synthetic=True)
    assert search(ws, "evidence", scope_name="research") == before
    assert search(ws, "SECRET-ACCOUNT-TITLE", scope_name="research") == []
    assert "SECRET-ACCOUNT-TITLE" not in canonical(before).decode()
    with pytest.raises(Denied):
        backlinks(ws, denied.id, scope_name="research")
    assert {hit.kind for hit in before} == {"evidence", "synthesis"}


def test_bilingual_short_query_and_cache_rebuild(ws: Workspace, tmp_path: Path) -> None:
    file = tmp_path / "中文.txt"
    file.write_text("这是证据检索的合成样例。\nEnglish evidence remains distinct from proof.")
    item = capture(ws, file, domain="research")
    extract(ws, item.id, inline_synthetic=True)
    before = search(ws, "证据", scope_name="research")
    assert len(before) == 2
    assert search(ws, "evidence", scope_name="research") == before
    assert search(ws, "证据检索", scope_name="research")
    durable = {
        path: ws.fs.read(path)
        for prefix in ("vault", "blobs", "evidence")
        for path in ws.fs.files(prefix)
    }
    shutil.rmtree(ws.root / "cache")
    assert rebuild_index(ws, "research") == 2
    assert search(ws, "证据", scope_name="research") == before
    assert all(ws.fs.read(path) == data for path, data in durable.items())
    assert query(ws, "missing unicorn", scope_name="research")["status"] == "insufficient_evidence"


def test_restricted_backlinks_are_omitted(ws: Workspace, record: Record) -> None:
    ws.fs.write("vault/wiki/research/concept_demo.md", encode(record, "Public scoped content."))
    secret = record.model_copy(deep=True)
    secret.id = "concept_secret"
    secret.title = "DO-NOT-REVEAL"
    secret.domain = "finance"
    secret.related = [record.id]
    ws.fs.write("vault/wiki/finance/concept_secret.md", encode(secret, "restricted backlink"))
    assert backlinks(ws, record.id, scope_name="research") == []


def test_denied_evidence_withholds_derived_text_and_ranking(
    ws: Workspace,
    record: Record,
    tmp_path: Path,
) -> None:
    file = tmp_path / "secret-fixture.txt"
    file.write_text("SECRET-DERIVED-VALUE")
    source = capture(ws, file, domain="finance")
    extraction, key = extract(ws, source.id, inline_synthetic=True)
    record.title = "SECRET-DERIVED-TITLE"
    record.sources = [
        EvidenceRef(
            id=source.id, source_hash=extraction.source_hash, evidence_hash=key, locator="line 1"
        )
    ]
    ws.fs.write("vault/wiki/research/concept_demo.md", encode(record, "SECRET-DERIVED-VALUE"))
    assert search(ws, "SECRET", scope_name="research") == []
    assert rebuild_index(ws, "research") == 0
    assert all(b"SECRET-DERIVED" not in ws.fs.read(path) for path in ws.fs.files("cache"))


def test_cli_evidence_exact_locator_and_coverage(ws: Workspace, tmp_path: Path) -> None:
    file = tmp_path / "lines.txt"
    file.write_text("First evidence line.\nExact second value 42.")
    source = capture(ws, file, domain="research")
    extract(ws, source.id, inline_synthetic=True)
    result = CliRunner().invoke(
        app,
        [
            "evidence",
            source.id,
            "--scope",
            "research",
            "--locator",
            "line 2",
            "--workspace",
            str(ws.root),
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    report = json.loads(result.stdout)
    assert report["coverage"] == "full_text"
    assert (
        len(report["segments"]) == 1 and report["segments"][0]["text"] == "Exact second value 42."
    )


def test_cli_full_owner_workflow(tmp_path: Path) -> None:
    runner = CliRunner()
    workspace, code = tmp_path / "private", tmp_path / "public"
    code.mkdir()
    result = runner.invoke(
        app, ["init", "--workspace", str(workspace), "--code-root", str(code), "--synthetic"]
    )
    assert result.exit_code == 0, result.output
    file = tmp_path / "sample.txt"
    file.write_text("Synthetic evidence: exact value 42.")
    options = ["--workspace", str(workspace), "--json"]
    captured = runner.invoke(app, ["capture", str(file), "--domain", "research", *options])
    assert captured.exit_code == 0, captured.output
    source_id = json.loads(captured.stdout)["id"]
    staged = runner.invoke(
        app, ["ingest", source_id, "--scope", "research", "--inline-synthetic", *options]
    )
    assert staged.exit_code == 0, staged.output
    proposal = json.loads(staged.stdout)
    assert runner.invoke(app, ["apply", proposal["id"], *options]).exit_code == 3
    validation = runner.invoke(app, ["validate", proposal["id"], *options])
    assert validation.exit_code == 0, validation.output
    approval_args = ["approve", proposal["id"], "--statement", "Synthetic owner review", *options]
    for flag in proposal["review_flags"]:
        approval_args += ["--acknowledge", flag]
    assert runner.invoke(app, approval_args).exit_code == 0
    assert runner.invoke(app, ["apply", proposal["id"], *options]).exit_code == 0
    found = runner.invoke(app, ["search", "42", "--scope", "research", *options])
    assert found.exit_code == 0 and json.loads(found.stdout)
    assert runner.invoke(app, ["lint", "--scope", "research", *options]).exit_code == 0


def test_two_file_update_is_reviewable(ws: Workspace, tmp_path: Path) -> None:
    timestamp = now()
    project = Record(
        id="project_demo",
        type="project",
        title="Synthetic paper project",
        domain="research",
        created_at=timestamp,
        updated_at=timestamp,
        sections={"objective": "Preserve evidence and failed approaches."},
    )
    ws.fs.write("vault/wiki/research/project_demo.md", encode(project, "Owner project framing.\n"))
    paper = tmp_path / "paper.txt"
    paper.write_text("A synthetic paper reports a controlled result.")
    source = capture(ws, paper, domain="research")
    proposal = ingest(
        ws, source.id, scope_name="research", related_ids=[project.id], inline_synthetic=True
    )
    assert proposal and len(proposal.changes) == 2
    approve(
        ws, proposal.id, acknowledgements=proposal.review_flags, statement="Reviewed both changes"
    )
    apply(ws, proposal.id)
    _, revised, body = ws.record(project.id)
    assert revised.sources[0].id == source.id
    assert body == "Owner project framing.\n"
