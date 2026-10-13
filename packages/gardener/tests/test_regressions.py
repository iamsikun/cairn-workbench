"""Desired-behavior regression checks for kb-gardener b7e2558.

All mutations use tmp_path and all external requests are mocked. These tests
verify the corrected implementation without touching live data.
"""

import contextlib
import copy
import io
import json

import pytest
from cairn_garden import engine as g


def invoke(*args):
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        g.main(list(args))
    return json.loads(output.getvalue())


def kb():
    return g.kb_open(g.config())


def save_paper(body="Original reading.", source="arxiv:1706.03762", title="Original paper"):
    result = kb().save(
        kind="paper",
        title=title,
        body=body,
        topics=["Transformers"],
        fields={
            "source": source,
            "url": g.paper_url({"source": source}),
            "year": 2017,
            "authors": ["A Author"],
        },
    )
    return kb().resolve(result["slug"])


def index(items=None):
    items = items or [
        {
            "key": "PAPER001",
            "data": {
                "itemType": "preprint",
                "title": "Original paper",
                "url": "https://arxiv.org/abs/1706.03762",
                "collections": [],
            },
        }
    ]
    result = g.ZoteroIndex(items, [{"key": "TOPIC001", "data": {"name": "Transformers"}}])
    result._pdfs = {key: None for key in result.items}
    return result


def checklist(action, number="42"):
    body = "- [x] **N1** Approved action <!-- action: " + json.dumps(action) + " -->"
    result = kb().save(kind="note", title="Garden weekly 2026-W" + number, body=body)
    return result["slug"]


def test_source_line_keeps_user_annotation(ws):
    note = save_paper(
        "- Local PDF: /tmp/original.pdf — User: my annotation disagrees with Table 2."
    )
    body, *_ = g.fix_body(note, None)
    assert "User: my annotation disagrees with Table 2." in body


def test_other_papers_local_pdf_is_not_reassigned_to_current_paper(ws):
    note = save_paper("Compare [a different paper](/tmp/different-paper.pdf).")
    body, edits, unresolved, _ = g.fix_body(note, None)
    assert "[a different paper](/tmp/different-paper.pdf)" in body
    assert unresolved and not edits


def test_conflicting_identity_does_not_match_on_title(ws):
    idx = index(
        [
            {
                "key": "OTHER001",
                "data": {
                    "itemType": "journalArticle",
                    "title": "A repeated title",
                    "DOI": "10.1000/different",
                    "collections": [],
                },
            }
        ]
    )
    assert idx.find(["doi:10.1000/requested"], "A repeated title") is None


def test_zotero_item_links_still_drive_collection_sync(ws, monkeypatch):
    kb().save(
        kind="topic",
        title="Transformers",
        body="Read [this paper](zotero://select/library/items/PAPER001).",
    )
    monkeypatch.setattr(g.ZoteroIndex, "load", lambda: index())
    monkeypatch.setattr(g, "remote_titles", lambda cfg, ids: {})
    report = invoke("zotero-sync", "--dry-run")
    assert [item["item"] for item in report["to_add"]] == ["PAPER001"]


def test_paper_note_is_not_itself_proof_of_external_verification(ws, monkeypatch):
    save_paper(source="arxiv:9999.99999", title="Nonexistent paper")
    empty = g.ZoteroIndex([], [{"key": "TOPIC001", "data": {"name": "Transformers"}}])
    monkeypatch.setattr(g.ZoteroIndex, "load", lambda: empty)
    monkeypatch.setattr(g, "remote_titles", lambda cfg, ids: {})
    report = invoke("zotero-sync", "--dry-run")
    creation = next(item for item in report["to_create"] if item["id"] == "arxiv:9999.99999")
    assert creation["verified"] is False


def test_zotero_discovery_does_not_drop_same_day_later_additions(ws, monkeypatch):
    monkeypatch.setattr(
        g,
        "zotero_get",
        lambda *a, **kw: [
            {
                "key": "LATER001",
                "data": {
                    "title": "Added after the morning digest",
                    "dateAdded": "2026-10-12T18:00:00Z",
                },
            }
        ],
    )
    report = g.zotero_recent("2026-10-12")
    assert len(report["candidates"]) == 1


def candidate_sources(monkeypatch):
    candidate = {
        "source": "catalog",
        "id": "paper-1",
        "title": "A relevant discovery",
        "doi": "10.1000/discovery",
        "date": "2026-10-12",
    }
    monkeypatch.setattr(
        g,
        "catalog_candidates",
        lambda *a, **kw: {"available": True, "candidates": [copy.deepcopy(candidate)]},
    )
    monkeypatch.setattr(
        g, "arxiv_candidates", lambda *a, **kw: {"available": True, "candidates": []}
    )
    monkeypatch.setattr(g, "zotero_recent", lambda *a, **kw: {"available": True, "candidates": []})


def test_candidates_survive_crash_before_digest_is_saved(ws, monkeypatch):
    candidate_sources(monkeypatch)
    first = invoke("new-papers", "--since", "2026-10-10", "--record")
    # No digest was saved and no successful run was marked.
    second = invoke("new-papers", "--since", "2026-10-10", "--record")
    assert first["catalog"]["candidates"] == second["catalog"]["candidates"]


def test_weekly_window_contains_papers_seen_in_daily_runs(ws, monkeypatch):
    candidate_sources(monkeypatch)
    invoke("new-papers", "--since", "2026-10-10", "--record")
    weekly = invoke("new-papers", "--since", "2026-10-06")
    assert len(weekly["catalog"]["candidates"]) == 1


def test_existing_seed_is_attached_to_new_topic(ws):
    paper = save_paper()
    g.run_action(
        kb(),
        g.config(),
        {
            "op": "topic",
            "title": "New perspective",
            "body": "A new question.",
            "seeds": [{"title": paper.title, "source": paper.meta["source"]}],
        },
    )
    assert "new-perspective" in kb().resolve(paper.slug).topics


def test_topic_action_retries_unfinished_seeds(ws, monkeypatch):
    action = {
        "op": "topic",
        "title": "New perspective",
        "body": "A new question.",
        "seeds": [{"title": "Seed paper", "source": "arxiv:2305.13245"}],
    }
    name = checklist(action)
    original = g.run_action
    state = {"failed": False}

    def fail_once(kb_, cfg, action_):
        if action_["op"] == "paper" and not state["failed"]:
            state["failed"] = True
            raise OSError("simulated interruption after topic creation")
        return original(kb_, cfg, action_)

    monkeypatch.setattr(g, "run_action", fail_once)
    assert invoke("apply")["needs_agent"]
    invoke("apply")
    assert kb().resolve("Seed paper") is not None, kb().resolve(name).body


def test_apply_does_not_overwrite_concurrent_checklist_edits(ws, monkeypatch):
    name = checklist({"op": "topic", "title": "Example", "body": "Example description."})

    def action_with_concurrent_edit(kb_, cfg, action):
        current = kb_.resolve(name)
        g.save_note(kb_, current, current.body + "\n\nUser added this new decision.")
        return "done"

    monkeypatch.setattr(g, "run_action", action_with_concurrent_edit)
    invoke("apply")
    assert "User added this new decision." in kb().resolve(name).body


def test_dry_run_identifies_manual_work(ws):
    checklist({"op": "manual", "description": "merge notes"})
    report = invoke("apply", "--dry-run")
    assert len(report["needs_agent"]) == 1


def test_approved_proposal_without_json_reaches_agent(ws):
    kb().save(
        kind="note",
        title="Garden weekly 2026-W42",
        body="- [x] **M1** Consolidate the repeated explanation, preserving my observations.",
    )
    assert len(invoke("apply")["needs_agent"]) == 1


def test_html_audit_detects_missing_referenced_assets(ws):
    catalog = g.catalog_dir()
    catalog.mkdir()
    (catalog / "catalog.html").write_text(
        '<script src="catalog-assets-deadbeef/index.js"></script>'
    )
    report = invoke("html-audit")
    assert report.get("missing_asset_dirs") == ["catalog-assets-deadbeef"]


def test_storage_never_deletes_only_known_successful_recovery(ws):
    catalog = g.catalog_dir()
    run = catalog / ".refreshes/only-good-edition"
    (run / "previous").mkdir(parents=True)
    (run / "previous/restore-me.txt").write_text("Only recovery data")
    (run / "report.json").write_text(
        json.dumps({"status": "success", "completed_at": "2026-10-10T00:00:00Z"})
    )
    # A zero retention config should be refused or clamped under the documented keep-one rule.
    with pytest.raises(SystemExit):
        invoke("storage", "--keep", "0", "--apply")
    assert run.exists()


def test_archive_preserves_links_to_digest(ws):
    digest = kb().save(kind="note", title="Garden digest 2000-01-01", body="Useful discovery.")
    kb().save(kind="note", title="Follow-up", body="Source: [[" + digest["slug"] + "]].")
    invoke("archive-digests")
    assert invoke("lint")["broken_links"] == []


def test_metrics_does_not_call_one_day_history_week_ago(ws):
    state = g.state_dir(g.config())
    yesterday = (g.datetime.now() - g.timedelta(days=1)).isoformat()
    (state / "metrics.jsonl").write_text(json.dumps({"at": yesterday, "papers": 123}) + "\n")
    report = invoke("metrics", "--dry-run")
    assert report["week_ago"] is None


def test_reverse_edge_has_correct_direction(ws):
    kb().save(kind="topic", title="Earlier work", body="The original approach.")
    kb().save(kind="topic", title="Later work", body="The extension.")
    g.run_action(
        kb(),
        g.config(),
        {
            "op": "link",
            "from": "later-work",
            "to": "earlier-work",
            "reason": "extends this approach",
            "both": True,
        },
    )
    assert "[[later-work]] — extends this approach" not in kb().resolve("earlier-work").body
