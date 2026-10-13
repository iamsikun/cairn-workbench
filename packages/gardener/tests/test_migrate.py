"""Migration from kb-gardener 0.4 and an in-workspace catalog, on a synthetic old layout."""

import fcntl
import os
import tomllib
from pathlib import Path

import pytest
from cairn_garden import engine as g
from cairn_garden import migrate, workflow

from cairn.store import KB, init

OLD_CONFIG = """workspace = "{kb}"
collection = "research"
agent = "claude"
zotero_user_id = 42
zotero_collections = {{ "autoregressive-decoding" = "9RQU2TA9" }}
publish_upstream = false
workbench_repo = "someone/cairn-workbench"
upstream_sources = ["~/.local/share/kb-gardener"]
"""


@pytest.fixture
def legacy(tmp_path, monkeypatch):
    home = tmp_path / "home"
    kb = tmp_path / "cairn"
    monkeypatch.setenv("HOME", str(home))
    for name in (
        "CAIRN_CATALOG_DIR",
        "CAIRN_CATALOG_PREFERENCES",
        "CAIRN_WORKSPACE",
        "XDG_DATA_HOME",
        "XDG_CONFIG_HOME",
        "KB_GARDENER_CONFIG",
        "KB_GARDENER_HOME",
    ):
        monkeypatch.delenv(name, raising=False)
    config = home / ".config/cairn-workbench/config.toml"
    monkeypatch.setenv("CAIRN_WORKBENCH_CONFIG", str(config))
    monkeypatch.setattr(g, "CONFIG_FILE", config)
    monkeypatch.setattr(g, "HOME", home / ".local/state/cairn-workbench/garden")
    calls = []
    monkeypatch.setattr(migrate.subprocess, "run", lambda argv, **kw: calls.append(argv))

    old_config = home / ".config/kb-gardener"
    old_config.mkdir(parents=True)
    (old_config / "config.toml").write_text(OLD_CONFIG.format(kb=kb))
    (old_config / "zotero.key").write_text("web-api-key")
    (old_config / "zotero-local.json").write_text("{}")
    old_home = home / ".local/share/kb-gardener"
    (old_home / "history/cairn.git").mkdir(parents=True)
    (old_home / "history/cairn.git/HEAD").write_text("ref: refs/heads/master\n")
    (old_home / "logs").mkdir()
    (old_home / "logs/2026-10-13-daily.log").write_text("ok\n")
    skill = old_home / "skills/kb-gardener"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("old skill")
    (home / ".claude/skills").mkdir(parents=True)
    (home / ".claude/skills/kb-gardener").symlink_to(skill)
    agents = home / "Library/LaunchAgents"
    agents.mkdir(parents=True)
    (agents / "io.example.kb-gardener.daily.plist").write_bytes(b"<plist>daily</plist>")
    (agents / "io.example.other.plist").write_bytes(b"<plist>other</plist>")

    init(kb)
    catalog = kb / "research/catalog"
    (catalog / "raw/crossref").mkdir(parents=True)
    for name, text in [
        ("catalog.py", "# old code"),
        ("catalog.sqlite", "db"),
        ("catalog.html", "<html>"),
        ("Open catalog app.command", "#!/bin/zsh"),
        ("preferences.yaml", "people: []\n"),
        ("update.lock", ""),
        ("raw/crossref/page.json.gz", "x"),
    ]:
        (catalog / name).write_text(text)
    (kb / "research/resources").mkdir()
    (kb / "research/resources/extracted.txt").write_text("raw evidence")
    gardener = kb / ".gardener"
    (gardener / "runs/r1").mkdir(parents=True)
    (gardener / "runs/r1/manifest.json").write_text("{}")
    (gardener / "state.json").write_text('{"last_digest": "2026-10-13"}')
    (gardener / "run.lock").write_text("")
    KB(kb).save(
        kind="note",
        title="Journal catalog",
        body=f"[Open the catalog]({catalog}/catalog.html) and [coverage]({catalog}/COVERAGE.md).",
    )
    return {
        "home": home,
        "kb": kb,
        "catalog": catalog,
        "config": config,
        "calls": calls,
        "data": home / ".local/share/cairn-workbench/catalog",
    }


def snapshot(root: Path) -> dict:
    return {
        str(p.relative_to(root)): (
            os.readlink(p) if p.is_symlink() else p.read_bytes() if p.is_file() else None
        )
        for p in sorted(root.rglob("*"))
    }


def test_dry_run_plans_without_changing_anything(legacy, tmp_path):
    before = snapshot(tmp_path)
    proposal = migrate.plan(resources_to=tmp_path / "evidence")
    assert proposal["problems"] == []
    ops = [step["op"] for step in proposal["steps"]]
    assert ops[0] == "write" and "unload" in ops and "rewrite" in ops and "link" in ops
    assert snapshot(tmp_path) == before


def test_migration_empties_the_workspace_of_everything_but_notes(legacy, tmp_path):
    result = migrate.run(resources_to=tmp_path / "evidence")
    assert result["migrated"], result
    kb, data, home = legacy["kb"], legacy["data"], legacy["home"]
    assert not (kb / ".gardener").exists() and not (kb / "research/catalog").exists()
    assert not (kb / "research/resources").exists()

    config = tomllib.loads(legacy["config"].read_text())
    assert config["workspace"] == str(kb) and config["catalog"]["data_dir"] == str(data)
    assert config["garden"]["zotero_collections"] == {"autoregressive-decoding": "9RQU2TA9"}
    assert config["garden"]["zotero_user_id"] == 42
    assert not {"workbench_repo", "publish_upstream", "upstream_sources"} & set(config["garden"])

    assert (data / "catalog.sqlite").read_text() == "db" and (
        data / "raw/crossref/page.json.gz"
    ).exists()
    assert (data / "legacy-source/catalog.py").exists() and (
        data / "legacy-source/Open catalog app.command"
    ).exists()
    assert (home / ".config/cairn-workbench/catalog-preferences.yaml").read_text() == "people: []\n"
    assert (tmp_path / "evidence/extracted.txt").read_text() == "raw evidence"
    assert (home / ".config/cairn-workbench/zotero.key").exists()
    assert (home / ".config/kb-gardener/zotero-local.json").exists()  # the extension's fixed path

    cfg = g.config()
    assert g.load_state(cfg) == {"last_digest": "2026-10-13"}
    assert (g.state_dir(cfg) / "runs/r1/manifest.json").exists()
    assert (g.HOME / "history/cairn.git/HEAD").exists() and (
        g.HOME / "logs/2026-10-13-daily.log"
    ).exists()
    assert Path(os.readlink(home / ".claude/skills/kb-gardener")) == workflow.SKILL
    assert not (home / "Library/LaunchAgents/io.example.kb-gardener.daily.plist").exists()
    assert (home / "Library/LaunchAgents/io.example.other.plist").exists()
    assert ["launchctl", "bootout", f"gui/{os.getuid()}/io.example.kb-gardener.daily"] in legacy[
        "calls"
    ]

    note = g.kb_open(cfg).resolve("journal-catalog")
    assert f"]({data}/catalog.html)" in note.body and str(legacy["catalog"]) not in note.body
    assert g.foreign_entries(cfg) == []


def test_rollback_restores_the_previous_layout(legacy, tmp_path):
    before = snapshot(legacy["kb"]), snapshot(legacy["home"] / ".config/kb-gardener")
    result = migrate.run(resources_to=tmp_path / "evidence")
    undone = migrate.rollback(Path(result["journal"]))
    assert undone["rolled_back"] == result["steps"]
    after_kb = snapshot(legacy["kb"])
    # Only the note's revision metadata changes after a rewrite and its reversal.
    note = "research/notes/journal-catalog.md"
    assert {k: v for k, v in after_kb.items() if k != note} == {
        k: v for k, v in before[0].items() if k != note
    }
    assert (
        str(legacy["catalog"]) + "/catalog.html" in KB(legacy["kb"]).resolve("journal-catalog").body
    )
    assert snapshot(legacy["home"] / ".config/kb-gardener") == before[1]
    assert not legacy["config"].exists() and not legacy["data"].exists()
    assert "kb-gardener/skills" in os.readlink(legacy["home"] / ".claude/skills/kb-gardener")
    assert (
        legacy["home"] / "Library/LaunchAgents/io.example.kb-gardener.daily.plist"
    ).read_bytes() == b"<plist>daily</plist>"


def test_resources_stay_without_a_destination(legacy):
    proposal = migrate.plan()
    assert any("resources" in note for note in proposal["notes"])
    assert not any(step.get("from", "").endswith("/resources") for step in proposal["steps"])


def test_refuses_interrupted_catalog_publication(legacy):
    (legacy["catalog"] / "update-pending.json").write_text("{}")
    result = migrate.run()
    assert not result["migrated"] and any("interrupted" in p for p in result["problems"])
    assert legacy["catalog"].exists()


def test_refuses_existing_targets(legacy):
    legacy["data"].mkdir(parents=True)
    (legacy["data"] / "catalog.sqlite").write_text("another catalog")
    result = migrate.run()
    assert not result["migrated"] and any(str(legacy["data"]) in p for p in result["problems"])


def test_waits_for_a_running_workflow(legacy):
    with open(legacy["kb"] / ".gardener/run.lock") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(RuntimeError, match="held"):
            migrate.run()
    assert (legacy["kb"] / ".gardener/state.json").exists() and legacy["catalog"].exists()
