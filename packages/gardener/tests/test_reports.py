"""The gardening report folder: saving, index, archive, lint and metrics."""

from pathlib import Path

import pytest
from cairn_garden import reports
from cairn_garden import workflow as w
from test_regressions import g, invoke, kb
from test_workflows import draft


def rows(cfg):
    text = (reports.root(cfg) / reports.INDEX).read_text()
    return text, [line for line in text.splitlines() if line.endswith("` |")]


def test_index_has_one_row_per_run_and_marks_outcomes(setup, monkeypatch):
    ok = w.run(setup, "daily", renderer=draft)
    with g.engine_lock(setup, "run"):
        skipped = w.run(setup, "daily", renderer=draft)

    def broken(*a, **k):
        raise RuntimeError("agent interrupted")

    with pytest.raises(RuntimeError):
        w.run(setup, "daily", renderer=broken)
    reports.record_run(setup, ok)  # recording the same run again does not duplicate it
    text, lines = rows(setup)
    assert len(lines) == 3
    by_status = {line.split(" | ")[3]: line for line in lines}
    assert set(by_status) == {"success_with_warnings", "skipped", "failed"}
    assert (
        f"[garden-digest-{ok['period']}](daily/garden-digest-{ok['period']}.md)"
        in (by_status["success_with_warnings"])
    )
    assert "1 papers recommended" in by_status["success_with_warnings"]
    assert "—" in by_status["skipped"] and "another workflow" in by_status["skipped"]
    assert "—" in by_status["failed"] and "agent interrupted" in by_status["failed"]
    assert skipped["status"] == "skipped"
    assert invoke("lint")["report_links"] == []


def test_not_due_is_recorded_once(setup, capsys):
    w.run(setup, "daily", renderer=draft)
    capsys.readouterr()
    assert w.main(["daily", "--scheduled"]) == 0
    first, _ = rows(setup)
    w.main(["daily", "--scheduled"])
    second, lines = rows(setup)
    assert first == second and len(lines) == 1
    assert "- **daily**: not due; last completed" in second


def test_report_links_are_portable_and_protected(ws):
    cfg = g.config()
    kb().save(kind="topic", title="Transformers", body="Sequence models.")
    source = reports.path_of(cfg, "weekly/garden-weekly-2026-w42.md")
    body = "See [[transformers]] and [[transformers|the topic]].\n`[[transformers]]`\n<!-- [[transformers]] -->"
    result = reports.portable(cfg, body, source)
    assert "[Transformers](../../research/topics/transformers.md)" in result
    assert "[the topic](../../research/topics/transformers.md)" in result
    assert "`[[transformers]]`" in result and "<!-- [[transformers]] -->" in result


def test_save_requires_current_revision(ws):
    cfg = g.config()
    rid = "maintenance/zotero-check.md"
    first = reports.save(cfg, rid, "First check.", {"title": "Zotero check"})
    with pytest.raises(g.cairn().CairnError):
        reports.save(cfg, rid, "Overwrite.", {})
    reports.save(cfg, rid, "Second check.", {}, revision=first.revision)
    assert reports.find(cfg, "Zotero check").body.strip() == "Second check."


def test_archive_keeps_linked_digests_and_finds_archived_ones(ws):
    cfg = g.config()
    old = reports.save(cfg, "daily/garden-digest-2000-01-01.md", "Old.", {"title": "Old"})
    linked = reports.save(cfg, "daily/garden-digest-2000-01-02.md", "Kept.", {"title": "Kept"})
    reports.record_run(
        cfg,
        {
            "id": "20000101T073000-daily-00000000",
            "mode": "daily",
            "status": "success",
            "report_id": "daily/garden-digest-2000-01-01.md",
        },
    )
    kb().save(
        kind="note",
        title="Follow-up",
        body="From [the digest](../../gardening/daily/garden-digest-2000-01-02.md).",
    )
    result = invoke("archive-digests")
    assert result["archived"] == [
        {
            "from": "daily/garden-digest-2000-01-01.md",
            "to": "archive/daily/garden-digest-2000-01-01.md",
        }
    ]
    assert result["retained_referenced"] == ["daily/garden-digest-2000-01-02.md"]
    assert not old.path.exists() and linked.path.exists()
    assert reports.find(cfg, "garden-digest-2000-01-01").body.strip() == "Old."
    assert "(archive/daily/garden-digest-2000-01-01.md)" in rows(cfg)[0]
    assert invoke("lint")["report_links"] == []


def test_lint_allows_reports_and_repository_files_only(ws):
    cfg = g.config()
    reports.save(
        cfg, "weekly/garden-weekly-2026-w42.md", "[gone](../../research/notes/gone.md)", {}
    )
    for name in (".git", ".github", "tools"):
        (Path(ws) / name).mkdir()
    (Path(ws) / "cairn-workbench.toml").write_text("")
    lint = invoke("lint")
    assert lint["foreign_entries"] == ["tools"]
    assert lint["report_links"] == [
        {"report": "weekly/garden-weekly-2026-w42.md", "target": "../../research/notes/gone.md"}
    ]


def test_metrics_count_research_notes_only(ws):
    cfg = g.config()
    kb().save(kind="note", title="Garden design", body="Not a report, despite its name.")
    reports.save(cfg, "weekly/garden-weekly-2026-w42.md", "- [ ] **P1** Open", {})
    current = invoke("metrics", "--dry-run")["current"]
    assert current["notes"] == 1
    assert current["proposals"]["open"] == 1
    assert invoke("lint")["orphans"] == ["garden-design"]


def test_reports_are_in_private_history(setup):
    w.run(setup, "daily", renderer=draft)
    files = g.git(setup, "ls-files").stdout.split()
    assert any(f.startswith("gardening/daily/") for f in files)
    invoke("commit", "-m", "next run")  # the index row follows the run's own commit
    assert "gardening/index.md" in g.git(setup, "ls-files").stdout.split()


def test_reports_folder_must_stay_inside_the_workspace(ws):
    for bad in ("/tmp/elsewhere", "../outside", "research", ".hidden"):
        with pytest.raises(ValueError):
            reports.root({**g.config(), "reports": bad})
