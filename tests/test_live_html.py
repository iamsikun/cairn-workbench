"""Synthetic opt-in projections, failure recovery, and route boundaries."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from test_mcp import ROUTE, Client, grant
from test_notebook_workflow import accept_synthetic
from test_presentation import source

from cairn.errors import Conflict, Denied
from cairn.policies.audit import revoke_grant, set_scope
from cairn.presentation import live
from cairn.records.models import Record, now
from cairn.storage.backup import backup, restore
from cairn.storage.markdown import encode
from cairn.transactions.apply import recover


def notebook(ws):
    paper = source(ws, processing="cloud_eligible")
    at = now()
    note = Record(
        id="concept_paper",
        type="concept",
        title="Paper note",
        domain="research",
        processing="cloud_eligible",
        primary_source_id=paper.id,
        created_at=at,
        updated_at=at,
    )
    topic = note.model_copy(
        update={
            "id": "concept_topic",
            "title": "Generative recommendation",
            "primary_source_id": None,
            "related": [note.id],
        }
    )
    for record, body in [(note, "Initial paper explanation."), (topic, "## Topic\n\nA synthesis.")]:
        ws.fs.write(f"vault/wiki/research/{record.id}.md", encode(record, body))
    return topic, note


def edit(ws, record, body):
    path = ws.record(record.id)[0]
    ws.fs.write(path, encode(record, body))


def test_opt_in_apply_sync_and_editor_sync(ws, tmp_path):
    grant(ws)
    topic, note = notebook(ws)
    client = Client(ws, "--html-root", str(tmp_path / "html"))
    try:
        page = client.ok("page", record_id=note.id)
        assert not live.registrations(ws)
        failed, _ = client.call("view", record_id=topic.id)
        assert failed
        rendered = client.ok("view", record_id=topic.id, format="html")
        output = Path(rendered["path"])
        assert output == tmp_path / "html/research/concept_topic.html"
        assert "Initial paper explanation" in output.read_text()
        assert len(list((tmp_path / "html").rglob("*.html"))) == 1
        result = client.ok(
            "propose_page",
            target=note.id,
            base_hash=page["base_hash"],
            instructions="Clarify.",
            body_markdown="Accepted new explanation.",
        )
        accept_synthetic(ws, result["proposal_id"])
        assert "Accepted new explanation" in output.read_text()
        edit(ws, ws.record(note.id)[1], "Editor update.")
        assert "Editor update" not in output.read_text()
        assert live.sync(ws)[0].status == "current"
        assert "Editor update" in output.read_text()
    finally:
        client.close()


def test_dependencies_and_unrelated_changes(ws, tmp_path, monkeypatch):
    topic, note = notebook(ws)
    output = tmp_path / "topic.html"
    live.render_page(ws, topic.id, "research", output, inline_synthetic=True)
    original = live.render_bundle
    calls = []

    def render(*args, **kwargs):
        calls.append(True)
        return original(*args, **kwargs)

    monkeypatch.setattr(live, "render_bundle", render)
    other = note.model_copy(update={"id": "concept_other", "primary_source_id": None})
    ws.fs.write("vault/wiki/research/concept_other.md", encode(other, "Unrelated"))
    live.sync(ws)
    assert calls == []
    added = note.model_copy(update={"id": "concept_added"})
    ws.fs.write("vault/wiki/research/concept_added.md", encode(added, "Added linked note."))
    topic.related.append(added.id)
    edit(ws, topic, "Changed notebook links.")
    live.sync(ws)
    assert len(calls) == 1 and "Added linked note" in output.read_text()
    topic.related.remove(note.id)
    edit(ws, topic, "Removed initial note.")
    live.sync(ws)
    calls.clear()
    edit(ws, note, "Detached paper edit.")
    live.sync(ws)
    assert calls == [] and "Detached paper edit" not in output.read_text()


def test_failure_retry_tamper_and_safe_paths(ws, tmp_path, monkeypatch):
    topic, note = notebook(ws)
    output = tmp_path / "topic.html"
    live.render_page(ws, topic.id, "research", output, inline_synthetic=True)
    previous = output.read_bytes()
    edit(ws, note, "Pending update.")
    original = live.render_bundle

    def fail(*args, **kwargs):
        raise Denied("synthetic renderer failure")

    monkeypatch.setattr(live, "render_bundle", fail)
    assert live.sync(ws)[0].status == "stale"
    assert output.read_bytes() == previous
    monkeypatch.setattr(live, "render_bundle", original)
    recover(ws)
    assert "Pending update" in output.read_text()
    output.write_text("OWNER HTML EDIT")
    assert live.sync(ws)[0].status == "stale"
    assert output.read_text() == "OWNER HTML EDIT"
    with pytest.raises(Conflict, match="modified"):
        live.render_page(ws, topic.id, "research", output, inline_synthetic=True)
    with pytest.raises(Denied):
        live.render_page(ws, topic.id, "research", ws.root / "inside.html", inline_synthetic=True)
    link = tmp_path / "link"
    link.symlink_to(output)
    with pytest.raises(Denied):
        live.render_page(ws, topic.id, "research", link, inline_synthetic=True)


@pytest.mark.parametrize("first_render", [False, True])
def test_interrupted_replacement_retries(ws, tmp_path, first_render):
    topic, note = notebook(ws)
    output = tmp_path / "topic.html"
    if not first_render:
        live.render_page(ws, topic.id, "research", output, inline_synthetic=True)
    edit(ws, note, "Crash update.")
    command = (
        ["page", topic.id, "--format", "html", "--output", str(output), "--inline-synthetic"]
        if first_render
        else ["sync"]
    )
    result = subprocess.run(
        [sys.executable, "-m", "cairn", "view", *command, "--workspace", str(ws.root)],
        env={**os.environ, "CAIRN_TEST_CRASH_AT": "html:replaced"},
        timeout=30,
    )
    assert result.returncode == 77
    assert live.registrations(ws)[0].pending_checksum
    recover(ws)
    entry = live.registrations(ws)[0]
    assert entry.status == "current" and entry.pending_checksum is None
    assert "Crash update" in output.read_text()


def test_revoked_grant_and_narrowed_scope(ws, tmp_path):
    grant(ws)
    topic, note = notebook(ws)
    output = tmp_path / "topic.html"
    live.render_page(
        ws,
        topic.id,
        "research",
        output,
        route=(ROUTE["provider"], ROUTE["destination"]),
        inline_synthetic=True,
    )
    previous = output.read_bytes()
    revoke_grant(ws, "grant_agent", base_hash=ws.policy_hash, statement="Synthetic revocation")
    edit(ws, note, "Must not export.")
    assert live.sync(ws)[0].status == "stale" and output.read_bytes() == previous
    grant(ws)
    scope = ws.policy.scope("research").model_copy(update={"record_ids": {note.id}})
    set_scope(ws, scope, base_hash=ws.policy_hash, statement="Synthetic narrowed scope")
    assert live.sync(ws)[0].status == "stale" and output.read_bytes() == previous


@pytest.mark.parametrize("streaming", [False, True])
def test_restore_does_not_write_historical_destinations(ws, tmp_path, streaming):
    from cairn.storage import streaming_backup

    topic, _ = notebook(ws)
    output = tmp_path / "topic.html"
    live.render_page(ws, topic.id, "research", output, inline_synthetic=True)
    archive = tmp_path / "backup.zip"
    backup(ws, archive)
    restored = (streaming_backup.restore if streaming else restore)(
        archive, tmp_path / "restored", code_roots=[tmp_path / "public-code"], synthetic=True
    )
    output.write_text("External file after backup")
    entries = live.sync(restored)
    assert entries[0].status == "inactive" and not entries[0].active
    assert output.read_text() == "External file after backup"
    rebound = tmp_path / "rebound.html"
    live.render_page(restored, topic.id, "research", rebound, inline_synthetic=True)
    assert rebound.exists()


def test_markdown_rendering_is_passive(ws, tmp_path):
    topic, _ = notebook(ws)
    edit(
        ws,
        topic,
        "# Heading\n\n- List\n\n| A | B |\n|---|---|\n| 1 | 2 |\n\n"
        "```python\nprint(42)\n```\n<script>INJECT()</script>\n"
        "![tracker](https://synthetic.invalid/tracker)\n[bad](javascript:alert%281%29)",
    )
    output = tmp_path / "topic.html"
    live.render_page(ws, topic.id, "research", output, inline_synthetic=True)
    html = output.read_text()
    assert "<h1>Heading</h1>" in html and "<table>" in html and "<li>List</li>" in html
    assert "language-python" in html and "&lt;script&gt;INJECT" in html
    assert 'src="https:' not in html and 'href="javascript:' not in html
