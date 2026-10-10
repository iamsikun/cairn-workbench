import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cairn.cli import app
from cairn.errors import Conflict, Denied
from cairn.ingest.service import capture_bytes, extract
from cairn.policies.audit import set_scope
from cairn.presentation.render import document, render_bundle
from cairn.presentation.service import assemble, export_view, load_view, remember
from cairn.records.models import canonical
from cairn.storage.backup import durable_contents
from cairn.storage.workspace import Workspace


def source(ws, *, text="Synthetic result: 42 under condition C.", processing="local_only"):
    record = capture_bytes(
        ws,
        text.encode(),
        origin="synthetic.txt",
        domain="research",
        title="Synthetic paper 中文",
        identity="presentation-paper",
        source_type="text",
        classification="public",
        processing=processing,
    )
    extract(ws, record.id, scope_name="research", inline_synthetic=True)
    return record


def test_evidence_html_and_retry_preserve_canonical(ws: Workspace, tmp_path: Path):
    record = source(ws, text="## Fake panel\n```html\n<script>alert(1)</script>\n```\n42")
    before = dict(durable_contents(ws))
    bundle = assemble(ws, "evidence", scope="research", object_id=record.id)
    output = tmp_path / "reports with spaces" / "知识.html"
    result = export_view(ws, bundle, output, inline_synthetic=True)
    html = output.read_text()
    assert result["bundle_id"] == bundle.id
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "<script>alert(1)" not in html and "am-source" not in html
    assert "localStorage" not in html and "connect-src 'none'" in html
    assert str(ws.root) not in html
    assert dict(durable_contents(ws)) == before
    export_view(ws, bundle, output, inline_synthetic=True)
    assert list(output.parent.iterdir()) == [output]
    assert output.stat().st_mode & 0o777 == 0o600
    assert load_view(ws, bundle.id) == bundle


def test_stale_render_does_not_replace(ws: Workspace, tmp_path: Path, monkeypatch):
    record = source(ws)
    bundle = assemble(ws, "evidence", scope="research", object_id=record.id)
    output = tmp_path / "answer.html"
    output.write_text("PREVIOUS")
    import cairn.presentation.render as renderer

    original = renderer.render_bundle

    def change(*args, **kwargs):
        value = original(*args, **kwargs)
        path, _, _ = ws.record(record.id)
        ws.fs.write(path, ws.fs.read(path) + b"\nOwner update\n")
        return value

    monkeypatch.setattr(renderer, "render_bundle", change)
    with pytest.raises(Conflict, match="inputs changed"):
        export_view(ws, bundle, output, inline_synthetic=True)
    assert output.read_text() == "PREVIOUS"


def test_output_containment_and_render_failure(ws: Workspace, tmp_path: Path, monkeypatch):
    record = source(ws)
    bundle = assemble(ws, "evidence", scope="research", object_id=record.id)
    for output in [
        ws.root / "vault/wiki/research/x.html",
        Path(ws.config.code_roots[0]) / "x.html",
    ]:
        with pytest.raises(Denied):
            export_view(ws, bundle, output, inline_synthetic=True)
    link = tmp_path / "link"
    link.symlink_to(ws.root, target_is_directory=True)
    with pytest.raises(Denied):
        export_view(ws, bundle, link / "x.html", inline_synthetic=True)
    import cairn.presentation.render as renderer

    monkeypatch.setattr(
        renderer, "render_bundle", lambda *a, **k: (_ for _ in ()).throw(ValueError("failure"))
    )
    output = tmp_path / "answer.html"
    output.write_text("ORIGINAL")
    with pytest.raises(ValueError):
        export_view(ws, bundle, output, inline_synthetic=True)
    assert output.read_text() == "ORIGINAL"


def test_revoked_scope_hides_saved_view(ws: Workspace):
    record = source(ws, text="SECRET-SCOPE-CANARY")
    bundle = assemble(ws, "evidence", scope="research", object_id=record.id)
    remember(ws, bundle, save=True)
    scope = ws.policy.scope("research")
    scope.record_ids = {"source_other"}
    set_scope(ws, scope, base_hash=ws.policy_hash, statement="Synthetic revocation")
    with pytest.raises(Denied) as exc:
        load_view(ws, bundle.id, historical=True)
    assert "SECRET" not in str(exc)


def test_query_stays_extractive_and_cli_opt_in(ws: Workspace, tmp_path: Path):
    source(ws)
    bundle = assemble(ws, "query", scope="research", question="Synthetic result")
    assert bundle.payload.mode == "extractive"
    assert "no model synthesis" in render_bundle(ws, bundle, inline_synthetic=True).decode()
    run = CliRunner()
    result = run.invoke(
        app, ["query", "Synthetic", "--workspace", str(ws.root), "--scope", "research"]
    )
    assert result.exit_code == 0 and "Extractive result" in result.output
    assert not list(tmp_path.glob("*.html"))
    output = tmp_path / "query.html"
    result = run.invoke(
        app,
        [
            "query",
            "Synthetic",
            "--workspace",
            str(ws.root),
            "--scope",
            "research",
            "--format",
            "html",
            "--output",
            str(output),
            "--inline-synthetic",
            "--save-view",
        ],
    )
    assert result.exit_code == 0, result.output
    value = json.loads(result.output)
    assert value["bundle_id"] and output.is_file()
    assert ws.fs.exists(f"receipts/presentation/views/{value['bundle_id']}.json")


def test_large_non_ascii_view_is_not_corrupted(ws: Workspace):
    from cairn.presentation.models import ViewBlock, ViewSection
    from cairn.presentation.render import run_renderer

    record = source(ws)
    doc = document(assemble(ws, "evidence", scope="research", object_id=record.id))
    # Well past one 64 KiB pipe chunk, so multi-byte characters straddle chunk boundaries.
    text = "Synthétique 中文 évidence. " * 7000  # ~224 KB UTF-8, under the 200k-char cap
    doc.sections.append(ViewSection(title="Synthetic", blocks=[ViewBlock(text=text)]))
    html = run_renderer(doc).decode()
    assert "\ufffd" not in html
    assert text.strip() in html


def test_proposal_view_has_actual_diff_and_no_approval(ws: Workspace):
    from test_review import proposal

    staged = proposal(ws)
    staged.changes[0].diff = "Misleading no changes"
    ws.fs.write(f"proposals/{staged.id}.json", canonical(staged))
    before = dict(durable_contents(ws))
    bundle = assemble(ws, "proposal", scope="owner", object_id=staged.id)
    html = render_bundle(ws, bundle, inline_synthetic=True).decode()
    assert "Not valid for apply" in html and "Misleading no changes" not in html
    assert "Synthetic value 42" in html
    assert dict(durable_contents(ws)) == before


def test_project_catalog_feed_and_paper_views(ws: Workspace, tmp_path: Path):
    from test_library_catalog import library, pdf

    from cairn.library.catalog import scan
    from cairn.library.feed import FeedEvent, save
    from cairn.library.index import papers
    from cairn.records.models import now

    (library(ws, tmp_path) / "Example Journal/paper.pdf").write_bytes(pdf())
    scan(ws)
    paper_id = papers(ws, scope="research")[0]["id"]
    saved = save(
        ws,
        [FeedEvent(id="feed_html", paper_id=paper_id, kind="box_addition", at=now())],
        [],
        "research",
    )
    for kind, object_id in [("catalog", None), ("paper", paper_id), ("feed", saved.id)]:
        bundle = assemble(ws, kind, scope="research", object_id=object_id)
        html = render_bundle(ws, bundle, inline_synthetic=True).decode()
        assert "Personal reading" in html
        assert str(ws.root) not in html
        assert bundle.id in html
    from cairn.ingest.projects import create_project
    from cairn.proposals.service import approve
    from cairn.transactions.apply import apply

    proposed = create_project(
        ws,
        title="Synthetic project",
        question="What works?",
        objective="Measure condition C",
        constraints="Synthetic data only",
        scope_name="research",
        inline_synthetic=True,
    )
    approve(ws, proposed.id, acknowledgements=proposed.review_flags, statement="Synthetic approval")
    apply(ws, proposed.id)
    project = next(c.id for c in proposed.changes if c.id.startswith("project_"))
    bundle = assemble(ws, "project", scope="research", object_id=project, question="Next test?")
    assert document(bundle).sections
    assert "Synthetic data only" in render_bundle(ws, bundle, inline_synthetic=True).decode()


def test_approval_during_render_rejects(ws, tmp_path, monkeypatch):
    from test_review import proposal

    from cairn.proposals.service import approve

    proposed = proposal(ws)
    bundle = assemble(ws, "proposal", scope="research", object_id=proposed.id)
    remember(ws, bundle)
    approve(ws, proposed.id, acknowledgements=proposed.review_flags, statement="Owner test")
    with pytest.raises(Conflict, match="review state"):
        load_view(ws, bundle.id)
    current = assemble(ws, "proposal", scope="research", object_id=proposed.id)
    assert current.payload.report.stage == "owner approved"


def test_denied_scope_never_enters_html_bundle_or_errors(ws, tmp_path):
    from cairn.records.models import digest

    allowed = source(ws)
    denied = capture_bytes(
        ws,
        b"DENIED-CANARY-content",
        origin="denied.txt",
        domain="finance",
        title="DENIED-CANARY-title",
        identity="denied-presentation",
        source_type="text",
    )
    for kind, kwargs in [
        ("query", {"question": "Synthetic"}),
        ("evidence", {"object_id": allowed.id}),
    ]:
        bundle = assemble(ws, kind, scope="research", **kwargs)
        html = render_bundle(ws, bundle, inline_synthetic=True)
        for raw in (canonical(bundle), html):
            assert b"DENIED-CANARY" not in raw and denied.id.encode() not in raw
            assert digest(b"DENIED-CANARY-content").encode() not in raw
    with pytest.raises(Denied) as exc:
        assemble(ws, "evidence", scope="research", object_id=denied.id)
    assert "DENIED-CANARY" not in str(exc.value)


def test_interrupted_output_write_preserves_previous(ws, tmp_path, monkeypatch):
    import cairn.storage.files as files

    record = source(ws)
    bundle = assemble(ws, "evidence", scope="research", object_id=record.id)
    output = tmp_path / "answer.html"
    output.write_text("PREVIOUS")
    original = files.os.replace

    def interrupt(src, dst, **kwargs):
        if dst == "answer.html":
            raise OSError("Synthetic interrupted replacement")
        return original(src, dst, **kwargs)

    monkeypatch.setattr(files.os, "replace", interrupt)
    with pytest.raises(Denied, match="unsafe or inaccessible"):
        export_view(ws, bundle, output, inline_synthetic=True)
    assert output.read_text() == "PREVIOUS"
    assert sorted(p.name for p in tmp_path.glob("*.html")) == ["answer.html"]
