"""`cairn-garden migrate-reports`: legacy reports leave the research notes, reversibly."""

import json
from pathlib import Path

import pytest
from cairn_garden import migrate_reports as m
from cairn_garden import reports
from test_regressions import g, invoke, kb

WEEKLY = """# Garden weekly 2026-W41

Recommended reading: [[attention]]. Daily context in [[garden-digest-2026-10-01]].

- [x] **N1** Link the founding paper <!-- action: {"op":"link","from":"transformers","to":"attention","reason":"the founding paper"} -->
- [x] ✅ **R1** Retag attention _(applied 2026-10-06: retagged attention)_
- [ ] **M1** Merge the two attention notes <!-- action: {"op":"manual","description":"merge"} -->
- [x] **M2** Rewrite the summary by hand <!-- action: {"op":"manual","description":"rewrite"} -->

`[[attention]]` in code stays as written.

User: my own annotation on this review.

<!-- gardener-run:20261005T103000-weekly-abcdef01 -->"""


@pytest.fixture
def legacy(ws):
    cfg = g.config()
    kb().save(kind="topic", title="Transformers", body="Sequence models.")
    kb().save(
        kind="paper",
        title="Attention",
        body="The founding paper.",
        topics=["Transformers"],
        fields={"source": "arxiv:1706.03762"},
    )
    kb().save(
        kind="note",
        title="Garden digest 2026-10-01",
        body="Read [[attention]].\n\n<!-- gardener-run:20261001T073000-daily-abcdef01 -->",
        topics=["research-catalogs"],
    )
    kb().save(
        kind="note", title="Garden weekly 2026-W41", body=WEEKLY, topics=["research-catalogs"]
    )
    kb().save(kind="note", title="Garden design", body="Notes on designing gardens.")
    kb().save(kind="note", title="Follow-up", body="Discussed in [[garden-weekly-2026-w41]].")
    archive = g.state_dir(cfg) / "archive"
    archive.mkdir()
    (archive / "garden-digest-2026-09-01.md").write_text(
        "---\ntitle: Garden digest 2026-09-01\nkind: note\n---\nOld digest on [[attention]].\n"
    )
    run = g.state_dir(cfg) / "runs" / "20261005T103000-weekly-abcdef01"
    run.mkdir(parents=True)
    g.atomic_json(
        run / "manifest.json",
        {
            "id": run.name,
            "mode": "weekly",
            "status": "success",
            "started_at": "2026-10-05T10:30:00-05:00",
            "report": "garden-weekly-2026-w41",
        },
    )
    g.atomic_json(run / "report.json", {"slug": "garden-weekly-2026-w41"})
    return cfg


def snapshot(*roots):
    return {
        str(p): p.read_bytes()
        for root in roots
        for p in sorted(Path(root).rglob("*"))
        if p.is_file() and not p.name.endswith(".lock") and "report-migration" not in p.name
    }


def test_preview_writes_nothing(legacy):
    before = snapshot(legacy["workspace"], g.HOME)
    result = m.preview(legacy)
    assert snapshot(legacy["workspace"], g.HOME) == before
    assert {x["to"] for x in result["moves"]} == {
        "daily/garden-digest-2026-10-01.md",
        "weekly/garden-weekly-2026-w41.md",
        "archive/daily/garden-digest-2026-09-01.md",
    }
    assert [Path(p).name for p in result["relinked_notes"]] == ["follow-up.md"]
    assert result["problems"] == []


def test_migration_moves_reports_keeps_content_and_links(legacy):
    root = Path(legacy["workspace"])
    original = (root / "research/notes/garden-weekly-2026-w41.md").read_text()
    result = m.run(legacy)
    assert result["migrated"] and result["moved"] == 3 and result["indexed_runs"] == 1
    assert not list((root / "research/notes").glob("garden-digest-*"))
    assert (root / "research/notes/garden-design.md").exists()
    weekly = (root / "gardening/weekly/garden-weekly-2026-w41.md").read_text()
    assert weekly.split("---\n")[1] == original.split("---\n")[1]  # front matter verbatim
    assert "[Attention](../../research/papers/attention.md)" in weekly
    assert "[Garden digest 2026-10-01](../daily/garden-digest-2026-10-01.md)" in weekly
    assert "`[[attention]]` in code" in weekly and "User: my own annotation" in weekly
    assert '"op":"link"' in weekly and "- [x] ✅ **R1**" in weekly
    archived = (root / "gardening/archive/daily/garden-digest-2026-09-01.md").read_text()
    assert "(../../../research/papers/attention.md)" in archived
    follow = kb().resolve("follow-up").body
    assert "(../../gardening/weekly/garden-weekly-2026-w41.md)" in follow
    lint = invoke("lint")
    assert lint["report_links"] == lint["broken_links"] == lint["foreign_entries"] == []
    assert lint["legacy_reports"] == []
    receipt = {"slug": "garden-weekly-2026-w41"}
    assert reports.locate(legacy, receipt).path.name == "garden-weekly-2026-w41.md"
    assert "`20261005T103000-weekly-abcdef01`" in (root / "gardening/index.md").read_text()
    assert m.run(legacy) == {"migrated": False, "steps": 0, "note": "nothing to migrate"}


def test_approvals_apply_once_from_the_new_location(legacy):
    m.run(legacy)
    result = invoke("apply")
    assert [a["item"][:8] for a in result["applied"]] == ["- [x] **"]
    assert len(result["needs_agent"]) == 1  # the approved manual proposal
    body = reports.get(legacy, "weekly/garden-weekly-2026-w41.md").body
    assert "- [x] ✅ **N1**" in body and "- [ ] **M1**" in body
    assert "## Related\n- [[attention]] — the founding paper" in kb().resolve("transformers").body
    assert invoke("apply")["applied"] == []
    assert invoke("metrics", "--dry-run")["current"]["proposals"]["open"] == 1


def test_interrupted_migration_resumes_without_duplicates(legacy, monkeypatch):
    calls = {"n": 0}
    original = m._unlink

    def interrupted(path):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("power loss")
        original(path)

    monkeypatch.setattr(m, "_unlink", interrupted)
    with pytest.raises(OSError):
        m.run(legacy)
    monkeypatch.setattr(m, "_unlink", original)
    assert m.unfinished(legacy)
    assert m.run(legacy)["migrated"]
    root = Path(legacy["workspace"])
    assert not reports.legacy(kb().notes())
    assert len(list((root / "gardening").rglob("garden-*.md"))) == 3
    assert m.unfinished(legacy) is None


def test_destination_conflict_is_refused(legacy):
    target = Path(legacy["workspace"]) / "gardening/weekly/garden-weekly-2026-w41.md"
    target.parent.mkdir(parents=True)
    target.write_text("A different report.")
    before = snapshot(legacy["workspace"])
    result = m.run(legacy)
    assert not result["migrated"] and "different content" in result["problems"][0]
    assert snapshot(legacy["workspace"]) == before


def test_rollback_restores_every_byte(legacy):
    before = snapshot(legacy["workspace"], g.state_dir(legacy))
    journal = m.run(legacy)["journal"]
    result = m.rollback(legacy, Path(journal))
    assert result["problems"] == []
    after = snapshot(legacy["workspace"], g.state_dir(legacy))
    after.pop(str(g.state_dir(legacy) / "report-moves.json"))
    assert after == before
    assert not (Path(legacy["workspace"]) / "gardening").exists()


def test_rollback_keeps_edits_made_after_migration(legacy):
    journal = m.run(legacy)["journal"]
    rid = "weekly/garden-weekly-2026-w41.md"
    current = reports.get(legacy, rid)
    ticked = current.body.replace("- [ ] **M1**", "- [x] **M1**")
    reports.save(legacy, rid, ticked, {}, revision=current.revision)
    result = m.rollback(legacy, Path(journal))
    assert result["problems"] and "edited after the migration" in result["problems"][0]
    assert "- [x] **M1**" in reports.get(legacy, rid).body
    assert kb().resolve("garden-digest-2026-10-01") is not None
    record = json.loads(Path(journal).read_text())
    assert record["status"] == "rolled back with conflicts"


def test_workflow_refuses_to_run_before_migration(setup):
    from cairn_garden import workflow as w
    from test_workflows import draft

    kb().save(kind="note", title="Garden digest 2026-10-01", body="An old digest.")
    with pytest.raises(RuntimeError, match="migrate-reports"):
        w.run(setup, "daily", renderer=draft)
    m.run(setup)
    assert w.run(setup, "daily", renderer=draft)["status"].startswith("success")


def test_cli_preview_and_maintenance(legacy, capsys):
    from cairn_garden import cli

    kb().save(kind="note", title="Zotero write verification", body="Checked the bridge.")
    code = cli.main(["migrate-reports", "--dry-run", "--maintenance", "zotero-write-verification"])
    result = json.loads(capsys.readouterr().out)
    assert code == 0
    assert "maintenance/zotero-write-verification.md" in {x["to"] for x in result["moves"]}
    assert "garden-design" not in json.dumps(result)
