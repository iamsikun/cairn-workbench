import json
from datetime import UTC, datetime
from pathlib import Path

from typer.testing import CliRunner

from cairn.cli import app
from cairn.ingest.notes import labels_for, read_notes, write_note
from cairn.ingest.service import capture
from cairn.proposals.accept import accept, plan
from cairn.proposals.inbox import inbox
from cairn.proposals.service import ingest
from cairn.retrieval.search import query, search
from cairn.storage.workspace import Workspace


def test_owner_notes_are_searchable_without_capture(ws: Workspace) -> None:
    ws.fs.write("vault/notes/research/idea.md", b"# Lattice idea\n\nTry the zebrafish estimator.\n")
    hits = search(ws, "zebrafish", scope_name="research", include_notes=True)
    assert [(h.kind, h.id, h.title) for h in hits] == [
        ("note", "note:vault/notes/research/idea.md", "Lattice idea")
    ]
    assert hits[0].sources == []
    # Views, context and model packets use the default and never carry owner notes.
    assert search(ws, "zebrafish", scope_name="research") == []
    assert query(ws, "zebrafish", scope_name="research")["hits"] == []
    ws.fs.write("vault/notes/research/idea.md", b"Edited: try the okapi estimator.\n")
    assert search(ws, "zebrafish", scope_name="research", include_notes=True) == []
    assert search(ws, "okapi", scope_name="research", include_notes=True)


def test_note_labels_scope_and_fail_closed(ws: Workspace) -> None:
    ws.fs.write("vault/notes/finance/budget.md", b"Synthetic walrus budget.\n")
    ws.fs.write(
        "vault/notes/research/secret.md",
        b"---\nclassification: restricted\ntags: [x]\n---\nSynthetic walrus secret.\n",
    )
    ws.fs.write("vault/notes/loose.md", b"Synthetic walrus loose note.\n")
    ws.fs.write("vault/notes/research/bad.md", b"---\nclassification: secretish\n---\nwalrus\n")
    assert search(ws, "walrus", scope_name="research", include_notes=True) == []
    owner = {h.id for h in search(ws, "walrus", scope_name="owner", include_notes=True)}
    assert owner == {
        "note:vault/notes/finance/budget.md",
        "note:vault/notes/research/secret.md",
        "note:vault/notes/research/bad.md",
        "note:vault/notes/loose.md",
    }
    finance = search(ws, "walrus", scope_name="finance", include_notes=True)
    assert [h.id for h in finance] == ["note:vault/notes/finance/budget.md"]
    assert labels_for("vault/notes/loose.md", {}).classification == "restricted"
    assert labels_for("vault/notes/research/x.md", {"domain": "life"}).domain == "life"


def test_quick_note_is_new_file_and_survives_workflow(ws: Workspace, tmp_path: Path) -> None:
    note = write_note(
        ws,
        "Heron hypothesis for later.",
        domain="research",
        at=datetime(2026, 1, 2, tzinfo=UTC),
    )
    assert note.path.startswith("vault/inbox/2026-01-02-heron-hypothesis-for-later-")
    assert search(ws, "heron", scope_name="research", include_notes=True)[0].kind == "note"
    before = ws.protected_hashes()
    paper = tmp_path / "paper.txt"
    paper.write_text("Synthetic yield was 8 percent.")
    proposal = ingest(
        ws, capture(ws, paper, domain="research").id, scope_name="research", inline_synthetic=True
    )
    assert proposal
    assert accept(ws, plan(ws, None))[0].status == "applied"
    assert all(ws.protected_hashes()[path] == value for path, value in before.items())
    again = write_note(ws, "Second heron note.", domain="research")
    assert again.path != note.path and len(read_notes(ws)) == 2


def test_inbox_lists_notes_and_pending_proposals(ws: Workspace, tmp_path: Path) -> None:
    note = write_note(ws, "Inbox egret note.", domain="research")
    paper = tmp_path / "paper.txt"
    paper.write_text("Synthetic yield was 8 percent.")
    proposal = ingest(
        ws, capture(ws, paper, domain="research").id, scope_name="research", inline_synthetic=True
    )
    assert proposal
    view = inbox(ws)
    assert [(n.path, n.captured_as) for n in view.notes] == [(note.path, None)]
    assert [(p.proposal_id, p.origin) for p in view.proposals] == [(proposal.id, "ingest")]
    assert view.proposals[0].next == "cairn accept --all"
    captured = capture(ws, ws.root / note.path, domain="research")
    assert inbox(ws).notes[0].captured_as == captured.id


def test_cli_stdin_note_capture_and_inbox(tmp_path: Path) -> None:
    runner = CliRunner()
    workspace, code = tmp_path / "private", tmp_path / "public"
    code.mkdir()
    init = ["init", "--workspace", str(workspace), "--code-root", str(code), "--synthetic"]
    assert runner.invoke(app, init).exit_code == 0
    options = ["--workspace", str(workspace), "--json"]
    noted = runner.invoke(
        app, ["note", "-", "--domain", "research", *options], input="Piped ibis thought.\n"
    )
    assert noted.exit_code == 0, noted.output
    found = runner.invoke(app, ["search", "ibis", "--scope", "research", *options])
    assert json.loads(found.stdout)[0]["kind"] == "note"
    hidden = runner.invoke(app, ["search", "ibis", "--scope", "research", "--no-notes", *options])
    assert json.loads(hidden.stdout) == []
    captured = runner.invoke(
        app, ["capture", "-", "--domain", "research", *options], input="Piped crane evidence 7."
    )
    assert captured.exit_code == 0, captured.output
    source = json.loads(captured.stdout)
    assert source["source"]["origin"] == "stdin" and source["source"]["source_type"] == "text"
    empty = runner.invoke(app, ["note", "-", *options], input="  \n")
    assert empty.exit_code == 2
    listed = runner.invoke(app, ["inbox", *options])
    assert listed.exit_code == 0, listed.output
    assert [n["title"] for n in json.loads(listed.stdout)["notes"]] == ["Piped ibis thought."]
