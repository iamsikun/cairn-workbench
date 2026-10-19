"""The installed command: dispatch, skill links and packaged assets."""

import json
import os
import subprocess
import sys
from pathlib import Path

from cairn_garden import workflow
from cairn_garden.zotero_local import BRIDGE

from cairn.store import init


def run(env, *args):
    result = subprocess.run(
        [sys.executable, "-m", "cairn_garden", *args], env=env, capture_output=True, text=True
    )
    return result.returncode, result.stdout


def sandbox(tmp_path):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("CAIRN_", "XDG_"))}
    env.update(
        HOME=str(tmp_path / "home"),
        CAIRN_WORKBENCH_CONFIG=str(tmp_path / "config.toml"),
        CAIRN_GARDEN_STATE=str(tmp_path / "state"),
        CAIRN_CATALOG_DIR=str(tmp_path / "catalog"),
    )
    (tmp_path / "home").mkdir()
    return env


def test_engine_commands_use_the_configured_workspace(tmp_path):
    env = sandbox(tmp_path)
    init(tmp_path / "kb")
    (tmp_path / "config.toml").write_text(f'workspace = "{tmp_path / "kb"}"\n')
    code, out = run(env, "lint")
    assert code == 0 and json.loads(out)["notes"] == 0
    assert (tmp_path / "state" / "workspaces").is_dir()


def test_skill_links_into_detected_agents_and_unlinks(tmp_path):
    env = sandbox(tmp_path)
    (tmp_path / "home/.claude").mkdir()
    code, out = run(env, "skill")
    link = tmp_path / "home/.claude/skills/kb-gardener"
    assert code == 0 and link.is_symlink() and (link / "SKILL.md").exists()
    assert link.resolve() == workflow.SKILL.resolve()
    assert not (tmp_path / "home/.agents").exists()
    run(env, "skill", "--remove")
    assert not link.exists()


def test_skill_keeps_links_owned_elsewhere(tmp_path):
    env = sandbox(tmp_path)
    other = tmp_path / "elsewhere/kb-gardener"
    other.mkdir(parents=True)
    skills = tmp_path / "home/.copilot/skills"
    skills.mkdir(parents=True)
    (skills / "kb-gardener").symlink_to(other)
    code, out = run(env, "skill")
    assert code == 0 and json.loads(out)["skill"][0]["kept"] == str(skills / "kb-gardener")
    run(env, "skill", "--remove")
    assert (skills / "kb-gardener").resolve() == other.resolve()


def test_skill_version_matches_the_package():
    from cairn_garden import __version__

    assert f'version: "{__version__}"' in (workflow.SKILL / "SKILL.md").read_text()


def test_skill_references_and_bridge_ship_with_the_package():
    names = {p.name for p in (workflow.SKILL / "references").glob("*.md")}
    assert {
        "daily.md",
        "weekly.md",
        "apply.md",
        "link-policy.md",
        "note-formats.md",
        "local-zotero.md",
    } <= names
    assert sorted(p.name for p in BRIDGE.iterdir()) == ["bootstrap.js", "manifest.json"]


def test_help_lists_commands(tmp_path):
    code, out = run(sandbox(tmp_path), "--help")
    assert code == 0 and "daily | weekly" in out and "schedule" in out
    assert "workbench" not in out


def test_release_hash_covers_instructions(tmp_path, monkeypatch):
    import shutil

    copy = tmp_path / "cairn_garden"
    shutil.copytree(workflow.PACKAGE, copy, ignore=shutil.ignore_patterns("__pycache__"))
    monkeypatch.setattr(workflow, "PACKAGE", copy)
    monkeypatch.setattr(workflow, "SKILL", copy / "skill")
    before = workflow.release_hash()
    (copy / "skill/references/daily.md").write_text("changed instructions")
    assert workflow.release_hash() != before


def test_old_layout_is_gone():
    package = Path(workflow.__file__).parent
    assert not (package / "scripts").exists() and not (package / "run.sh").exists()


def test_workflow_commands_find_agents_from_a_minimal_path(tmp_path):
    env = sandbox(tmp_path)
    env["PATH"] = "/usr/bin:/bin"
    init(tmp_path / "kb")
    (tmp_path / "config.toml").write_text(f'workspace = "{tmp_path / "kb"}"\n')
    agent = tmp_path / "home/.local/bin/claude"
    agent.parent.mkdir(parents=True)
    agent.write_text("#!/bin/sh\necho '{\"loggedIn\": true}'\n")
    agent.chmod(0o755)
    code, out = run(env, "health")
    assert json.loads(out)["executable"] == str(agent)
