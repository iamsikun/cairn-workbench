"""Finch agent installation against a synthetic home and a local synthetic remote."""

import json
import subprocess

import pytest
from typer.testing import CliRunner

from cairn.cli import app
from cairn.errors import Conflict
from cairn.reading import skill
from cairn.reading.skill import HANDOFF, files, guidance, install, installer, status


def synthetic_home(tmp_path, *agents):
    home = tmp_path / "synthetic-home"
    for agent in agents:
        (home / agent).mkdir(parents=True)
    return home


def environment(tmp_path, home, remote=None):
    # A minimal, explicit environment: no inherited home, credentials or update scheduler.
    return {
        "HOME": str(home),
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "FINCH_HOME": str(home / ".local/share/finch"),
        "FINCH_BIN": str(home / ".local/bin"),
        "FINCH_REPO": str(remote or tmp_path / "missing-remote.git"),
        "XDG_STATE_HOME": str(home / ".local/state"),
        "GIT_CONFIG_NOSYSTEM": "1",
    }


def synthetic_remote(tmp_path):
    """A local repository shaped like upstream Finch, built from the bundled snapshot."""
    work = tmp_path / "synthetic-finch-work"
    for name, raw in files().items():
        path = work / "skills/finch" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    (work / "install.sh").write_bytes(installer())
    env = {"HOME": str(tmp_path), "GIT_CONFIG_NOSYSTEM": "1", "PATH": "/usr/bin:/bin"}

    def git(*args, cwd=work):
        subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True)

    git("init", "-q", "-b", "stable")
    git("add", "-A")
    identity = ("-c", "user.name=Synthetic", "-c", "user.email=synthetic@example.invalid")
    git(*identity, "commit", "-qm", "Synthetic Finch release")
    remote = tmp_path / "synthetic-finch.git"
    git("clone", "-q", "--bare", str(work), str(remote), cwd=tmp_path)
    return remote


def forbidden(*args, **kwargs):
    raise AssertionError("installer must not run when Finch is available")


def snapshot(root):
    return {p: p.read_bytes() for p in root.rglob("*") if p.is_file() and not p.is_symlink()}


def test_bundle_carries_handoff_and_verified_installer(tmp_path, monkeypatch):
    assert files()["LICENSE"].startswith(b"MIT License")
    assert b"references/cairn.md" in files()["SKILL.md"]
    assert b"cairn_handoff_pending" in files()[HANDOFF]
    # The offline reader's guidance stays paper-only; the handoff ships with agent packets.
    assert "Finch: reading" in guidance() and "cairn_handoff_pending" not in guidance()
    assert installer().startswith(b"#!/usr/bin/env bash")
    tampered = tmp_path / "install.sh"
    tampered.write_bytes(installer() + b"\necho altered\n")
    monkeypatch.setattr(skill, "INSTALLER", tampered)
    with pytest.raises(Conflict, match="installer checksum"):
        installer()


def test_existing_finch_is_preserved_without_running_installer(tmp_path):
    home = synthetic_home(tmp_path, ".claude")
    existing = home / ".claude/skills/finch"
    existing.mkdir(parents=True)
    (existing / "SKILL.md").write_text('---\nname: finch\nmetadata:\n  version: "0.2.0"\n---\n')
    before = snapshot(home)
    result = install(environment(tmp_path, home), run=forbidden)
    assert result["state"] == "available"
    assert result["version"] == "0.2.0" and result["updates"] == "unmanaged"
    assert result["cairn_handoff"] is False
    assert snapshot(home) == before


def test_missing_finch_runs_upstream_installer_for_detected_agents(tmp_path):
    home = synthetic_home(tmp_path, ".claude", ".codex")
    env = environment(tmp_path, home, synthetic_remote(tmp_path))
    result = install(env, auto_update=False)
    assert result["state"] == "installed", result
    assert result["updates"] == "finch_installer"
    assert result["version"] == skill.VERSION and result["cairn_handoff"] is True
    clone = home / ".local/share/finch/skills/finch"
    links = [home / ".claude/skills/finch", home / ".agents/skills/finch"]
    assert result["agent_skill_dirs"] == [str(link.parent) for link in links]
    assert all(link.is_symlink() and link.resolve() == clone.resolve() for link in links)
    assert not (home / ".copilot").exists()
    # Installed Finch stays a clean clone so its own fast-forward update keeps working.
    dirty = subprocess.run(
        ["git", "-C", str(home / ".local/share/finch"), "status", "--porcelain"],
        env=env,
        capture_output=True,
        check=True,
    )
    assert dirty.stdout == b""
    assert install(env, run=forbidden)["state"] == "available"


def test_failed_install_is_pending_and_leaves_no_links(tmp_path):
    home = synthetic_home(tmp_path, ".claude")
    result = install(environment(tmp_path, home), auto_update=False)
    assert result["state"] == "pending" and result["available"] is False
    assert "cairn finch install" in result["reason"]
    assert not (home / ".claude/skills/finch").exists()


def test_init_installs_finch_only_when_requested_for_synthetic(tmp_path):
    home = synthetic_home(tmp_path, ".claude")
    env = environment(tmp_path, home, synthetic_remote(tmp_path))
    code = tmp_path / "public-code"
    code.mkdir()
    runner = CliRunner()
    base = ["init", "--code-root", str(code), "--synthetic"]
    result = runner.invoke(app, [*base, "--workspace", str(tmp_path / "a")], env=env)
    assert result.exit_code == 0, result.output
    assert "finch" not in json.loads(result.output)
    assert not (home / ".local").exists()
    result = runner.invoke(
        app,
        [*base, "--workspace", str(tmp_path / "b"), "--finch", "--no-finch-auto-update"],
        env=env,
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["finch"]["state"] == "installed"
    result = runner.invoke(app, ["finch", "status"], env=env)
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == status(env)
