"""Tests for the kb-gardener engine against a throwaway Cairn workspace and a stub Zotero API.

Run: uv run --with pytest --with pyyaml pytest skills/kb-gardener/tests
"""

import fcntl
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest
from cairn_garden import engine as gardener

PAPER = """---
title: Attention Is All You Need
kind: paper
source: arxiv:1706.03762
authors: [Ashish Vaswani]
year: 2017
url: https://arxiv.org/abs/1706.03762v7
topics: ['[[transformers]]']
---
# Attention Is All You Need

## Source and reading position
- Local PDF: /private/tmp/co-reading/attention.pdf
- Completed: §§1–3.

The user asked why scaling by sqrt(d_k) matters.
"""
TOPIC = """---
title: Transformers
kind: topic
---
# Transformers

Source: [pasted summary](</Users/x/cairn/research/resources/run/astra-summary.txt>).
See [MQA](https://arxiv.org/abs/1911.02150) and [Sparse attention](https://arxiv.org/abs/1904.10509).
| [Attention](https://arxiv.org/abs/1706.03762) | [EE3TRR9S](zotero://select/library/items/EE3TRR9S) |
Inspected: [text](/Users/x/cairn/research/resources/run/extracted-text/EE3TRR9S-D333Q84T.txt)
"""

ITEMS = {
    "EE3TRR9S": {
        "key": "EE3TRR9S",
        "data": {
            "itemType": "preprint",
            "title": "Attention Is All You Need",
            "url": "http://arxiv.org/abs/1706.03762",
            "archiveID": "arXiv:1706.03762",
            "collections": [],
        },
    },
    "QFYRQXFN": {
        "key": "QFYRQXFN",
        "data": {
            "itemType": "preprint",
            "title": "Fast Transformer Decoding",
            "DOI": "10.48550/arXiv.1911.02150",
            "collections": ["SUBCOLL1"],
        },
    },
}
COLLECTIONS = [
    {"key": "TRANSFOR", "data": {"name": "Transformers"}},
    {"key": "SUBCOLL1", "data": {"name": "Attention variants", "parentCollection": "TRANSFOR"}},
]
CHILDREN = {
    "EE3TRR9S": [
        {"key": "D333Q84T", "data": {"itemType": "attachment", "contentType": "application/pdf"}}
    ]
}


class Zotero(BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split("?")[0].removeprefix("/api/users/0/")
        if path in ("items", "items/top"):
            body = list(ITEMS.values())
        elif path == "collections":
            body = COLLECTIONS
        elif path.endswith("/children"):
            body = CHILDREN.get(path.split("/")[1], [])
        elif path.startswith("items/") and path.split("/")[1] in ITEMS:
            body = ITEMS[path.split("/")[1]]
        else:
            self.send_response(404)
            self.end_headers()
            return
        data = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


@pytest.fixture
def zotero(monkeypatch):
    server = HTTPServer(("127.0.0.1", 0), Zotero)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setattr(gardener, "ZOTERO", f"http://127.0.0.1:{server.server_port}/api/users/0")
    yield
    server.shutdown()


@pytest.fixture
def ws(tmp_path, monkeypatch):
    root = tmp_path / "kb"
    (root / ".cairn").parent.mkdir(parents=True)
    (root / ".cairn").touch()
    for folder in ("papers", "topics", "notes"):
        (root / "research" / folder).mkdir(parents=True)
    (root / "research/papers/attention-is-all-you-need.md").write_text(PAPER)
    (root / "research/topics/transformers.md").write_text(TOPIC)
    monkeypatch.setenv("CAIRN_WORKSPACE", str(root))
    monkeypatch.setenv("CAIRN_CATALOG_DIR", str(tmp_path / "catalog"))
    monkeypatch.setattr(gardener, "CONFIG_FILE", tmp_path / "none.toml")
    monkeypatch.setattr(gardener, "HOME", tmp_path / "home")
    monkeypatch.setattr(gardener, "BRIDGE_CREDENTIALS", tmp_path / "bridge" / "zotero-local.json")
    monkeypatch.setattr(gardener, "ZOTERO", "http://127.0.0.1:9/api/users/0")  # Closed by default.
    monkeypatch.setattr(gardener, "remote_metadata", lambda ident: None)
    monkeypatch.setattr(gardener, "zotero_api_key", lambda: None)
    return root


def run(capsys, *argv):
    gardener.main(list(argv))
    return json.loads(capsys.readouterr().out)


def test_lint_flags_local_references(ws, capsys):
    report = run(capsys, "lint")
    targets = {r["target"] for r in report["forbidden_refs"]}
    assert "/private/tmp/co-reading/attention.pdf" in targets
    assert any("research/resources/run/astra-summary.txt" in t for t in targets)
    assert report["broken_links"] == []
    assert report["reading_positions"][0]["note"] == "attention-is-all-you-need"


def test_fix_links_uses_zotero(ws, zotero, capsys):
    result = run(capsys, "fix-links")
    paper = (ws / "research/papers/attention-is-all-you-need.md").read_text()
    assert "/private/tmp" not in paper
    # In Zotero: the note points to the Zotero item and its PDF only.
    assert (
        "- Paper: [Zotero](zotero://select/library/items/EE3TRR9S) · [PDF in Zotero](zotero://open-pdf/library/items/D333Q84T)"
        in paper
    )
    assert "The user asked why scaling" in paper  # The user's words are untouched.
    topic = (ws / "research/topics/transformers.md").read_text()
    assert "[text](zotero://select/library/items/EE3TRR9S)" in topic
    assert "[MQA](zotero://select/library/items/QFYRQXFN)" in topic  # Paper URL -> Zotero item.
    assert (
        "[Sparse attention](https://arxiv.org/abs/1904.10509)" in topic
    )  # Not in Zotero: unchanged.
    assert (
        "| Attention | [EE3TRR9S](zotero://select/library/items/EE3TRR9S) |" in topic
    )  # No duplicate link.
    assert [u["target"] for u in result["unresolved"]] == [
        "/Users/x/cairn/research/resources/run/astra-summary.txt"
    ]


def test_fix_links_falls_back_to_paper_url(ws, capsys):
    result = run(capsys, "fix-links", "--dry-run")
    assert result["zotero_available"] is False
    edit = result["changed"][0]["edits"][0]
    assert edit["to"] == "[arxiv:1706.03762](https://arxiv.org/abs/1706.03762v7)"
    assert (
        "/private/tmp" in (ws / "research/papers/attention-is-all-you-need.md").read_text()
    )  # Dry run.


def make_run(base: Path, name: str, marker: str, status: str, stamp: str, previous=True):
    run_dir = base / name
    (run_dir / "staged").mkdir(parents=True)
    if previous:
        (run_dir / "previous").mkdir()
        (run_dir / "previous" / "x.bin").write_bytes(b"0" * 1024)
    key = "completed_at" if marker == "report.json" else "published_at"
    (run_dir / marker).write_text(json.dumps({"status": status, key: stamp}))
    return run_dir


def test_storage_keeps_newest_successful_edition(ws, capsys):
    refreshes = gardener.catalog_dir() / ".refreshes"
    old = make_run(
        refreshes, "20261011T000000Z", "report.json", "success", "2026-10-11T00:00:00+00:00"
    )
    new = make_run(
        refreshes, "ui-tweak-20261012", "publication.json", "success", "2026-10-12T00:00:00+00:00"
    )
    failed = make_run(
        refreshes,
        "20261011T120000Z",
        "report.json",
        "failed",
        "2026-10-11T12:00:00+00:00",
        previous=False,
    )
    os.utime(failed, (0, 0))
    report = run(capsys, "storage")
    assert [k["path"] for k in report["kept"]] == [str(new)]
    assert {d["path"] for d in report["delete"]} == {str(old), str(failed)}
    assert old.exists()  # Dry run by default.
    run(capsys, "storage", "--apply")
    assert not old.exists() and not failed.exists() and new.exists()


def test_storage_waits_for_catalog_refresh(ws, capsys):
    catalog = gardener.catalog_dir()
    make_run(catalog / ".refreshes", "a", "report.json", "success", "2026-10-11T00:00:00+00:00")
    with (catalog / "update.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        report = run(capsys, "storage", "--apply")
    assert "skipped" in report


def test_apply_runs_ticked_actions_only(ws, capsys):
    checklist = """---
title: Garden weekly 2026-W42
kind: note
---
# Garden weekly 2026-W42

- [x] **N1** New topic <!-- action: {"op":"topic","title":"KV-cache compression","body":"Ways to shrink attention caches.","broader":["transformers"],"seeds":[{"title":"GQA","source":"arxiv:2305.13245","url":"https://arxiv.org/abs/2305.13245","year":2023}]} -->
- [ ] **L1** Unticked link <!-- action: {"op":"link","from":"transformers","to":"attention-is-all-you-need","reason":"x"} -->
- [x] **M1** Merge two notes <!-- action: {"op":"manual"} -->
"""
    (ws / "gardening/weekly").mkdir(parents=True)
    (ws / "gardening/weekly/garden-weekly-2026-w42.md").write_text(checklist)
    result = run(capsys, "apply")
    assert len(result["applied"]) == 1 and len(result["needs_agent"]) == 1
    topic = (ws / "research/topics/kv-cache-compression.md").read_text()
    assert "[[transformers]]" in topic
    seed = (ws / "research/papers/gqa.md").read_text()
    assert "arxiv:2305.13245" in seed and "kv-cache-compression" in seed
    note = (ws / "gardening/weekly/garden-weekly-2026-w42.md").read_text()
    assert "- [x] ✅ **N1**" in note and "- [ ] **L1**" in note
    assert "## Related" not in (ws / "research/topics/transformers.md").read_text()
    assert run(capsys, "apply")["applied"] == []  # Applied items are not run twice.


def test_link_action_adds_related_section(ws, capsys):
    (ws / "gardening/weekly").mkdir(parents=True)
    (ws / "gardening/weekly/garden-weekly-2026-w43.md").write_text(
        "---\ntitle: Garden weekly 2026-W43\nkind: note\n---\n"
        '- [x] **L1** link <!-- action: {"op":"link","from":"transformers","to":"attention-is-all-you-need","reason":"the founding paper"} -->\n'
    )
    run(capsys, "apply")
    body = (ws / "research/topics/transformers.md").read_text()
    assert "## Related\n- [[attention-is-all-you-need]] — the founding paper" in body


def test_commit_keeps_git_outside_workspace(ws, capsys):
    result = run(capsys, "commit", "-m", "first")
    assert result["committed"] is True
    assert not (ws / ".git").exists()
    assert run(capsys, "commit", "-m", "again")["committed"] is False


def test_zotero_sync_plans_memberships_and_creations(ws, zotero, capsys):
    result = run(capsys, "zotero-sync", "--dry-run")
    assert result["topic_collections"] == {"transformers": "Transformers"}
    added = {a["item"]: a["collections"] for a in result["to_add"]}
    assert added == {"EE3TRR9S": ["Transformers"]}  # Filed by its own paper note.
    # The topic note only cites Sparse attention: it is reported, never created or filed.
    assert result["to_create"] == []
    assert result["cited_without_note"] == [
        {"id": "arxiv:1904.10509", "cited_in": ["transformers"]}
    ]
    assert result["can_write"] is False and result["done"] == []
