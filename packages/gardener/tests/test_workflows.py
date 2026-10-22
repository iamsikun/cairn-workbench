"""Integration and failure-injection tests; real Cairn persistence and Git, isolated externals."""

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from cairn_garden import schedule
from cairn_garden import workflow as w
from test_regressions import g, index, invoke, kb, report, save_paper


def draft(cfg, mode, folder, facts, model=None):
    return {
        "body": 'Research update: [New attention paper](https://doi.org/10.1234/one) extends a current topic.\n\n- [ ] **P1** Review this paper. <!-- action: {"op":"manual","description":"Read the paper"} -->',
        "selected": ["doi:10.1234/one"],
    }, {"agent": "claude", "model": "fixture"}


def test_daily_weekly_persist_reports_history_and_delivery(setup):
    daily = w.run(setup, "daily", renderer=draft)
    weekly = w.run(setup, "weekly", renderer=draft, verify_html=True)
    assert daily["status"] == weekly["status"] == "success_with_warnings"
    assert report(daily["report_id"]) and report(weekly["report_id"])
    assert daily["report_id"] == "daily/garden-digest-" + daily["period"] + ".md"
    assert not list((Path(setup["workspace"]) / "research/notes").glob("garden-*"))
    assert "gardening/" in g.git(setup, "show", "--stat", "--format=").stdout
    assert g.load_state(setup)["last_run_weekly"] == weekly["id"]
    entry = g.read_json(g.state_dir(setup) / "discoveries.json", {})["candidates"][
        "doi:10.1234/one"
    ]
    assert entry["status"] == "delivered"
    assert "verified report" in g.git(setup, "log", "-1", "--format=%s").stdout
    assert not (Path(setup["workspace"]) / ".git").exists()
    weekly_facts = g.read_json(g.state_dir(setup) / "runs" / weekly["id"] / "new-papers.json", {})
    assert weekly_facts["catalog"]["candidates"][0]["identity"] == entry["identity"]


@pytest.mark.parametrize("failure", ["agent", "commit"])
def test_failed_workflow_does_not_acknowledge_delivery(setup, monkeypatch, failure):
    def failed(*a, **k):
        raise RuntimeError("agent interrupted")

    if failure == "commit":
        original = w.execute

        def execute(*argv):
            if argv[0] == "commit" and "verified report" in argv[-1]:
                raise RuntimeError("history write failed")
            return original(*argv)

        monkeypatch.setattr(w, "execute", execute)
    with pytest.raises(RuntimeError):
        w.run(setup, "daily", renderer=failed if failure == "agent" else draft)
    assert "last_digest" not in g.load_state(setup)
    ledger = g.read_json(g.state_dir(setup) / "discoveries.json", {})
    assert ledger["candidates"]["doi:10.1234/one"]["status"] == "discovered"
    receipts = list((g.state_dir(setup) / "runs").glob("*/manifest.json"))
    assert json.loads(receipts[-1].read_text())["status"] == "failed"


def test_run_lock_skips_second_owner_and_releases(setup):
    with g.engine_lock(setup, "run"):
        result = w.run(setup, "daily", renderer=draft)
        assert result["status"] == "skipped"
    assert w.run(setup, "daily", renderer=draft)["status"].startswith("success")


def test_test_runs_cannot_enable_schedules(setup, monkeypatch):
    w.run(setup, "daily", renderer=draft)
    w.run(setup, "weekly", renderer=draft, verify_html=True)
    monkeypatch.setattr(
        w,
        "health",
        lambda cfg: {"ready": True, "release": w.release_hash(), "workspace": cfg["workspace"]},
    )
    assert not w.readiness(setup)["ready"]


def test_rerun_preserves_user_edits(setup):
    first = w.run(setup, "daily", renderer=draft)
    note = report(first["report_id"])
    g.reports.save(
        setup, first["report_id"], note.body + "\nUser: keep this question.", {}, note.revision
    )

    # A new daily recommendation normally comes from pending candidates.
    def empty_draft(*args, **kwargs):
        return {
            "body": "No further discoveries today; earlier observations are retained.",
            "selected": [],
        }, {"agent": "claude"}

    again = w.run(setup, "daily", renderer=empty_draft)
    assert "User: keep this question." in report(again["report_id"]).body


@pytest.mark.parametrize(
    "mode,stamp,expected",
    [
        ("daily", "2026-10-13T07:29:00", False),
        ("daily", "2026-10-13T07:30:00", True),
        ("weekly", "2026-10-12T10:29:00", False),
        ("weekly", "2026-10-12T10:30:00", True),
        ("weekly", "2026-10-13T00:00:00", True),
    ],
)
def test_schedule_timezone_and_catchup(setup, mode, stamp, expected):
    assert (
        w.due(
            setup, mode, datetime.fromisoformat(stamp).replace(tzinfo=ZoneInfo("America/Chicago"))
        )
        is expected
    )


def test_completed_day_and_week_are_not_repeated(setup):
    g.save_state(setup, {"last_digest": "2026-10-13", "last_weekly": "2026-10-12"})
    stamp = datetime(2026, 10, 13, 12, tzinfo=ZoneInfo("America/Chicago"))
    assert not w.due(setup, "daily", stamp) and not w.due(setup, "weekly", stamp)


def test_schedule_plist_preserves_paths_and_uses_verified_runner():
    import plistlib

    value = schedule.job("daily")
    assert plistlib.loads(plistlib.dumps(value)) == value
    assert value["ProgramArguments"][-3:] == ["cairn_garden", "daily", "--scheduled"]


def test_aster_refresh_job_needs_the_command(tmp_path, monkeypatch):
    import plistlib

    with pytest.raises(SystemExit, match="not installed"):
        schedule.aster_job()
    binary = tmp_path / "aster"
    binary.write_text("#!/bin/sh\n")
    binary.chmod(0o755)
    monkeypatch.setenv("CAIRN_ASTER", str(binary))
    monkeypatch.setenv("ASTER_DATA_DIR", str(tmp_path / "data"))
    value = schedule.aster_job()
    assert plistlib.loads(plistlib.dumps(value)) == value
    assert value["ProgramArguments"] == [str(binary), "refresh"]
    assert value["EnvironmentVariables"]["ASTER_DATA_DIR"] == str(tmp_path / "data")
    assert schedule.ASTER_LABEL in schedule.labels()


def test_first_source_outage_keeps_original_window(setup, monkeypatch):
    monkeypatch.setattr(
        g, "arxiv_candidates", lambda *a, **k: {"available": False, "candidates": []}
    )
    invoke("new-papers", "--since", "2026-10-01", "--record")
    g.save_state(setup, {"last_digest": "2026-10-13"})
    windows = []
    monkeypatch.setattr(
        g,
        "arxiv_candidates",
        lambda cfg, terms, since, *a, **k: (
            windows.append(since) or {"available": True, "candidates": []}
        ),
    )
    invoke("new-papers", "--record")
    assert windows == ["2026-09-26"]


def test_incomplete_catalog_resumes_before_advancing_cursor(setup, monkeypatch):
    offsets = []

    def pages(cfg, terms, since, limit, offset=0):
        offsets.append(offset)
        return {"available": True, "complete": offset == 60, "next_offset": 60, "candidates": []}

    monkeypatch.setattr(g, "catalog_candidates", pages)
    invoke("new-papers", "--record")
    invoke("new-papers", "--record")
    assert offsets == [0, 60]
    assert (
        "pending"
        not in g.read_json(g.state_dir(setup) / "discoveries.json", {})["sources"]["catalog"]
    )


def test_zotero_pagination_is_inclusive(ws, monkeypatch):
    offsets = []

    def get(*args, **kwargs):
        offsets.append(kwargs["start"])
        return (
            [
                {
                    "key": str(kwargs["start"]),
                    "data": {"title": "Paper", "dateAdded": "2026-10-13T19:00:00Z"},
                }
            ]
            if kwargs["start"] < 2
            else []
        )

    monkeypatch.setattr(g, "zotero_get", get)
    assert len(g.zotero_recent("2026-10-13", limit=1)["candidates"]) == 2
    assert offsets == [0, 1, 2]


def test_uncertain_zotero_creation_is_not_repeated(ws, monkeypatch):
    save_paper()
    empty = g.ZoteroIndex([], [{"key": "TOPIC001", "data": {"name": "Transformers"}}])
    monkeypatch.setattr(g.ZoteroIndex, "load", lambda: empty)
    monkeypatch.setattr(g, "remote_zotero_index", lambda cfg: empty)
    monkeypatch.setattr(g, "zotero_api_key", lambda: "test-only")
    monkeypatch.setattr(g, "DEFAULTS", {**g.DEFAULTS, "zotero_user_id": 1})
    monkeypatch.setattr(
        g,
        "remote_metadata",
        lambda ident: {
            "itemType": "preprint",
            "title": "Original paper",
            "url": "https://arxiv.org/abs/1706.03762",
        },
    )
    calls = []

    def remote(cfg, method, *args, **kwargs):
        calls.append(method)
        raise TimeoutError("server may have accepted request")

    monkeypatch.setattr(g, "zotero_web", remote)
    assert invoke("zotero-sync")["failed"]
    assert invoke("zotero-sync")["failed"]
    assert calls == ["POST"]
    assert invoke("zotero-sync", "--dry-run")["daily_writes_used"] == 1


def test_daily_zotero_budget_survives_reruns(ws, monkeypatch):
    save_paper()
    monkeypatch.setattr(g.ZoteroIndex, "load", lambda: index())
    monkeypatch.setattr(g, "zotero_api_key", lambda: "test-only")
    monkeypatch.setattr(g, "DEFAULTS", {**g.DEFAULTS, "zotero_user_id": 1, "zotero_write_limit": 1})
    calls = []

    def remote(cfg, method, *args, **kwargs):
        calls.append(method)
        return {"data": {"collections": []}, "version": 7}

    monkeypatch.setattr(g, "zotero_web", remote)
    invoke("zotero-sync")
    invoke("zotero-sync")
    assert calls.count("PATCH") == 1


def test_false_metadata_cannot_create_item(ws, monkeypatch):
    save_paper()
    monkeypatch.setattr(
        g.ZoteroIndex,
        "load",
        lambda: g.ZoteroIndex([], [{"key": "TOPIC001", "data": {"name": "Transformers"}}]),
    )
    monkeypatch.setattr(
        g,
        "remote_metadata",
        lambda ident: {"title": "Wrong result", "url": "https://arxiv.org/abs/9999.99999"},
    )
    assert not invoke("zotero-sync", "--dry-run")["to_create"][0]["verified"]


def test_storage_failed_deletion_is_not_counted(ws, monkeypatch):
    from test_gardener import make_run

    base = g.catalog_dir() / ".refreshes"
    make_run(base, "old", "report.json", "success", "2026-10-01T00:00:00Z")
    make_run(base, "new", "report.json", "success", "2026-10-13T00:00:00Z")

    def deny(path):
        raise PermissionError("cannot remove target")

    monkeypatch.setattr(g.shutil, "rmtree", deny)
    result = invoke("storage", "--apply")
    assert result["failed"] and not result["deleted"] and result["freed_bytes"] == 0


def test_html_validation_and_missing_file(ws):
    catalog = g.catalog_dir()
    assets = catalog / "catalog-assets-abc"
    assets.mkdir(parents=True)
    (catalog / "catalog.html").write_text('<script src="catalog-assets-abc/missing.js"></script>')
    (catalog / "offline-validation.json").write_text(
        json.dumps({"checks": {"status": "failed"}, "validated_at": "2000-01-01T00:00:00Z"})
    )
    result = invoke("html-audit")
    assert result["missing_asset_files"] == ["catalog-assets-abc/missing.js"]
    assert result["validation_files"]["offline-validation.json"]["status"] == "failed"
    assert result["validation_files"]["offline-validation.json"]["stale"]


def test_lint_reports_tools_and_data_kept_in_the_workspace(ws):
    (ws / "research/catalog").mkdir()
    (ws / "research/resources").mkdir()
    (ws / "research/ideation").mkdir()
    (ws / ".gardener").mkdir()
    (ws / "html").mkdir()
    (ws / "research/.DS_Store").write_text("")
    kb().save(kind="note", title="Plain note", body="Only knowledge here.")
    report = invoke("lint")
    assert report["foreign_entries"] == [".gardener", "research/catalog", "research/resources"]
    assert report["summary"]["foreign_entries"] == 3


def test_state_and_history_stay_outside_the_workspace(ws):
    cfg = g.config()
    assert not g.state_dir(cfg).is_relative_to(ws)
    kb().save(
        kind="idea",
        title="A new direction",
        body="**Question:** does it work?",
        fields={"status": "seed"},
    )
    assert invoke("commit", "-m", "ideas are history too")["committed"] is True
    tracked = g.git(cfg, "ls-files").stdout.split()
    assert "research/ideation/a-new-direction.md" in tracked
    assert not (ws / ".gardener").exists() and not (ws / ".git").exists()


def test_config_file_sections_and_environment(tmp_path, monkeypatch):
    config = tmp_path / "config.toml"
    config.write_text(
        'workspace = "~/kb"\ncollection = "finance"\n[garden]\nagent = "codex"\ncontact_email = "a@example.org"\n'
        '[catalog]\ndata_dir = "/elsewhere"\n'
    )
    monkeypatch.setattr(g, "CONFIG_FILE", config)
    monkeypatch.delenv("CAIRN_WORKSPACE", raising=False)
    cfg = g.config()
    assert (cfg["workspace"], cfg["collection"], cfg["agent"]) == ("~/kb", "finance", "codex")
    assert "data_dir" not in cfg and g.user_agent() == "cairn-garden (mailto:a@example.org)"
    monkeypatch.setenv("CAIRN_WORKSPACE", str(tmp_path / "other"))
    assert g.config()["workspace"] == str(tmp_path / "other")


def test_missing_workspace_is_reported(tmp_path, monkeypatch):
    monkeypatch.setattr(g, "CONFIG_FILE", tmp_path / "missing.toml")
    monkeypatch.delenv("CAIRN_WORKSPACE", raising=False)
    with pytest.raises(ValueError, match="workspace"):
        g.kb_open(g.config())


def test_mark_cannot_forge_completion(ws):
    with pytest.raises(SystemExit):
        invoke("mark", "digest")
    assert "last_digest" not in g.load_state(g.config())


def test_zotero_attachment_and_wikilink_drive_sync(ws, monkeypatch):
    paper = save_paper()
    g.save_note(
        kb(),
        kb().resolve("transformers"),
        "See [[" + paper.slug + "]] and [PDF](zotero://open-pdf/library/items/ATTACH01).",
    )
    monkeypatch.setattr(g.ZoteroIndex, "load", lambda: index())
    monkeypatch.setattr(
        g, "zotero_get", lambda path, **kwargs: {"data": {"parentItem": "PAPER001"}}
    )
    result = invoke("zotero-sync", "--dry-run")
    assert [x["item"] for x in result["to_add"]] == ["PAPER001"]
    assert not result["to_create"]


def test_html_failure_prevents_weekly_completion(setup, monkeypatch):
    original = w.execute

    def execute(*argv):
        return (
            {"verification": {"status": "failed"}} if argv[0] == "html-audit" else original(*argv)
        )

    monkeypatch.setattr(w, "execute", execute)
    with pytest.raises(RuntimeError, match="verification"):
        w.run(setup, "weekly", renderer=draft, verify_html=True)
    assert "last_weekly" not in g.load_state(setup)


def test_node_discovery_skips_incompatible_path_version(tmp_path, monkeypatch):
    newer = tmp_path / ".nvm/versions/node/v24.0.0/bin/node"
    newer.parent.mkdir(parents=True)
    newer.write_text("fake")
    monkeypatch.setattr(g.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(g.shutil, "which", lambda name: "/usr/local/bin/node")
    monkeypatch.setattr(g.os, "access", lambda *args: True)
    monkeypatch.setattr(
        g.subprocess,
        "run",
        lambda args, **kwargs: type(
            "Result", (), {"returncode": 0 if args[0] == str(newer) else 1}
        )(),
    )
    assert g.node_runtime() == str(newer)


def test_html_only_publication_cannot_evict_last_database_recovery(ws):
    from test_gardener import make_run

    base = g.catalog_dir() / ".refreshes"
    database = make_run(base, "database", "report.json", "success", "2026-10-12T00:00:00Z")
    (database / "previous/catalog.sqlite").write_bytes(b"recovery database")
    html = make_run(base, "html", "publication.json", "success", "2026-10-13T00:00:00Z")
    result = invoke("storage", "--apply")
    assert database.exists() and html.exists()
    assert not result["deleted"]


def test_bare_invented_publisher_citation_is_rejected(setup):
    value = {
        "body": "Read this useful new paper: https://publisher.example/fabricated-study",
        "selected": [],
    }
    with pytest.raises(ValueError, match="evidence"):
        w.validate_draft(kb(), value, "daily", {})


def test_wikilinks_in_code_are_not_checked(setup):
    body = (
        "Links that fix-links could not repair need manual rewriting to `[[slugs]]`.\n\n"
        "```markdown\nSee [[example]].\n```\n"
    )
    w.validate_draft(kb(), {"body": body, "selected": []}, "daily", {})
    with pytest.raises(ValueError, match="nonexistent note: missing-note"):
        w.validate_draft(
            kb(), {"body": body + "Read [[Missing note]].", "selected": []}, "daily", {}
        )


def test_weekly_proposals_require_executable_or_manual_records(setup):
    value = {
        "body": "Weekly review of the knowledge base.\n\n- [ ] Add a useful cross-reference between two notes.",
        "selected": [],
    }
    with pytest.raises(ValueError, match="stable IDs"):
        w.validate_draft(kb(), value, "weekly", {})


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://doi.org/10.1016/s0065-2458(08)60418-0", "doi:10.1016/s0065-2458(08)60418-0"),
        ("https://doi.org/10.1016/s0065-2458(08)60418-0).", "doi:10.1016/s0065-2458(08)60418-0"),
        ("https://arxiv.org/abs/cs/0309048v2", "arxiv:cs/0309048"),
        ("https://doi.org/10.48550/arXiv.cs/0309048", "arxiv:cs/0309048"),
        ("https://arxiv.org/abs/math.GT/0309001", "arxiv:math.gt/0309001"),
    ],
)
def test_full_doi_and_legacy_arxiv_identities(url, expected):
    assert g.url_id(url) == expected


def test_markdown_doi_parentheses_are_preserved(ws):
    note = save_paper("[Good](https://doi.org/10.1016/s0065-2458(08)60418-0).")
    body, *_ = g.fix_body(note, None)
    assert body == note.body
    assert g.MD_LINK.search(body).group(2) == "https://doi.org/10.1016/s0065-2458(08)60418-0"


def test_identity_migration_preserves_delivered_status():
    candidate = {"source": "zotero", "id": "KEY", "doi": "10.1016/s0065-2458(08)60418-0"}
    ledger = {
        "candidates": {
            "old": {
                "candidate": candidate,
                "identity": "old",
                "sources": ["zotero"],
                "status": "delivered",
                "discovered_at": "2026-10-13",
                "digest": "garden-digest-2026-10-13",
            }
        },
        "sources": {},
    }
    result = g.rekey_discoveries(ledger)["candidates"]
    assert result["doi:10.1016/s0065-2458(08)60418-0"]["status"] == "delivered"


def test_weekly_continuation_action_moves_without_losing_details(setup):
    body = 'Weekly review.\n\n- [ ] **Z1** Configure pending work:\n  - First detail.\n  - Second detail.\n\n  Do this manually. <!-- action: {"op":"manual","task":"Review"} -->\n'
    value = w.canonicalize_proposals(body)
    assert "First detail." in value and "Second detail." in value
    assert "<!-- action:" in next(line for line in value.splitlines() if line.startswith("- [ ]"))
    w.validate_draft(kb(), {"body": value, "selected": []}, "weekly", {})


@pytest.mark.parametrize(
    "citation",
    [
        "[Paper](zotero://select/library/items/4S2QQNAA): read this next.",
        "Paper (zotero://select/library/items/4S2QQNAA): read this next.",
        "[Paper](https://doi.org/10.1016/s0065-2458(08)60418-0): read this next.",
        "Paper (https://doi.org/10.1016/s0065-2458(08)60418-0): read this next.",
    ],
)
def test_citation_punctuation_does_not_change_source_url(setup, citation):
    facts = {
        "sources": [
            "zotero://select/library/items/4S2QQNAA",
            "https://doi.org/10.1016/s0065-2458(08)60418-0",
        ]
    }
    w.validate_draft(
        kb(),
        {"body": "A useful next step in our reading. " + citation, "selected": []},
        "daily",
        facts,
    )


def test_weekly_rerun_supersedes_the_earlier_checklist(setup):
    older = "weekly/garden-weekly-2026-w01.md"
    g.reports.save(
        setup,
        older,
        '- [ ] **L1** Old link <!-- action: {"op":"manual"} -->\n'
        '- [x] **L2** Approved, not yet applied <!-- action: {"op":"manual"} -->\n'
        "```markdown\n- [ ] an example, not a proposal\n```\n",
        {"title": "Garden weekly 2026-W01"},
    )
    seen = []

    def drafting(cfg, mode, folder, facts, model=None):
        seen.append(facts["open-proposals"])
        return draft(cfg, mode, folder, facts)

    first = w.run(setup, "weekly", renderer=drafting, verify_html=True)
    assert [x["item"] for x in seen[0]] == [
        '- [ ] **L1** Old link <!-- action: {"op":"manual"} -->'
    ]
    old = report(older).body
    assert f"- [-] **L1** Old link _(superseded by run {first['id']})_ <!-- action:" in old
    assert "- [x] **L2**" in old and "- [ ] an example" in old
    second = w.run(setup, "weekly", renderer=draft, verify_html=True)
    body = report(second["report_id"]).body
    assert body.count("- [-] **P1**") == 1 and body.count("- [ ] **P1**") == 1
    assert f"superseded by run {second['id']}" in body
    stats = invoke("metrics", "--dry-run")["current"]["proposals"]
    assert (stats["open"], stats["superseded"], stats["rejected"]) == (1, 2, 0)


def test_only_the_latest_run_of_a_report_counts_as_open(setup):
    runs = [f"- [ ] **P1** Same proposal again\n\n<!-- gardener-run:run{n} -->" for n in range(3)]
    g.reports.save(setup, "weekly/garden-weekly-2026-w02.md", "\n\n## Update\n\n".join(runs), {})
    assert g.proposal_stats(setup)["open"] == 1


def test_aster_settings_are_not_foreign(ws, monkeypatch):
    (ws / "aster.yaml").write_text("fields: []\n")
    (ws / "scouting").mkdir()
    (ws / "scouting/aster-settings.yaml").write_text("fields: []\n")
    kb().save(kind="note", title="Plain note", body="Only knowledge here.")
    assert invoke("lint")["foreign_entries"] == ["scouting"]
    monkeypatch.setenv("ASTER_CONFIG", str(ws / "scouting/aster-settings.yaml"))
    assert invoke("lint")["foreign_entries"] == []


def test_report_facts_are_rendered_from_the_run_not_the_draft(setup):
    result = w.run(setup, "daily", renderer=draft)
    body = report(result["report_id"]).body
    facts = body[body.index("## Run facts") : body.index("<!-- gardener-run:")]
    assert "- **Zotero**: unavailable" in facts and "- **Lint**: broken links 0" in facts
    assert "catalog 1 pending" in facts and "aster not installed" in facts
    assert "- **Warning**: Zotero writes unconfigured" in facts


def test_run_facts_name_confirmed_writes_and_gated_ones():
    facts = {
        "zotero-sync": {
            "zotero_available": True,
            "can_write": True,
            "backend": "web",
            "to_add": [{"item": "OLD00001"}, {"item": "OLD00002"}],
            "to_create": [{"id": "doi:10.1/a", "verified": True}],
            "done": [
                {
                    "status": "created",
                    "verified": True,
                    "id": "doi:10.1/a",
                    "title": "A paper",
                    "key": "NEW00001",
                },
                {"status": "added", "verified": True, "item": "OLD00001"},
            ],
            "failed": [],
        },
        "fix-links": {"changed": [{"note": "a-paper"}], "unresolved": []},
        "lint": {"summary": {"orphans": 2}},
        "new-papers": {"arxiv": {"available": False}},
        "metrics": {"current": {"proposals": {"open": 3, "superseded": 4}}},
    }
    text = w.run_facts("daily", facts, ["arxiv: unavailable"])
    assert (
        "- **Zotero**: (web) created 1 — [A paper](zotero://select/library/items/NEW00001)"
        " · filed in topic collections 1 · pending 1" in text
    )
    assert "notes repaired 1 ([[a-paper]])" in text and "orphans 2" in text
    assert "arxiv unavailable, checkpoint kept" in text and "open 3 · superseded 4" in text
    facts["zotero-sync"].update(dry_run=True, done=[])
    assert "pending 3 (read-only run: writes are gated)" in w.run_facts("daily", facts, [])


def test_a_rejected_draft_is_redone_once_with_the_reason(setup):
    calls = []

    def drafting(cfg, mode, folder, facts, model=None):
        calls.append((folder / w.REJECTED).exists())
        if len(calls) == 1:
            return {"body": "A long enough report that links [[Missing note]].", "selected": []}, {}
        return draft(cfg, mode, folder, facts)

    result = w.run(setup, "daily", renderer=drafting)
    assert calls == [False, True] and result["status"] == "success_with_warnings"
    assert any("first draft rejected" in warning for warning in result["warnings"])

    def invalid(cfg, mode, folder, facts, model=None):
        calls.append("again")
        return {"body": "A long enough report that links [[Missing note]].", "selected": []}, {}

    with pytest.raises(ValueError, match="nonexistent note"):
        w.run(setup, "weekly", renderer=invalid, verify_html=True)
    assert calls.count("again") == 2
