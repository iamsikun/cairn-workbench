"""Managed knowledge-base Quill against a local synthetic upstream and a synthetic home."""

import subprocess
from pathlib import Path

import pytest
from synthetic_channel import IDENTITY, env

from cairn.presentation.quill import HOOK, HOOK_MARKER
from cairn.updater import skills
from cairn.updater.home import Home


def synthetic_quill(tmp_path: Path) -> Path:
    work = tmp_path / "synthetic-quill"
    (work / "skills/quill/references").mkdir(parents=True)
    (work / "skills/quill/SKILL.md").write_text("# Synthetic Quill v1\n")
    (work / "skills/quill/references/drafting.md").write_text("Draft carefully.\n")
    (work / "README.md").write_text("Not part of the skill.\n")
    git(work, "init", "-q", "-b", "stable")
    commit(work, "Synthetic Quill v1")
    return work


def git(work: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *IDENTITY, *args], cwd=work, env=env(work.parent), check=True, capture_output=True
    )
    return completed.stdout.decode().strip()


def commit(work: Path, message: str) -> str:
    git(work, "add", "-A")
    git(work, "commit", "-qm", message)
    return git(work, "rev-parse", "HEAD")


@pytest.fixture
def upstream(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    work = synthetic_quill(tmp_path)
    monkeypatch.setenv("CAIRN_QUILL_REPO", str(work))
    return work


def test_private_setup_installs_channel_copy_with_handoff(
    upstream: Path, tmp_path: Path, synthetic_cairn_home: Path
) -> None:
    kb_skills = tmp_path / "kb" / ".claude" / "skills"
    result = skills.ensure_managed(kb_skills, fetch=True)
    assert result["status"] == "installed" and result["source"] == "channel"
    skill = kb_skills / "quill"
    assert (skill / "SKILL.md").read_text().startswith("# Synthetic Quill v1")
    assert HOOK_MARKER in (skill / "SKILL.md").read_text()
    assert (skill / HOOK).is_file() and (skill / "references/drafting.md").is_file()
    assert not (skill / "README.md").exists()
    home = Home(synthetic_cairn_home)
    assert skills.installs(home).skills_dirs["quill"] == [str(kb_skills)]
    clone = skills.clone_path(home, skills.QUILL)
    assert HOOK_MARKER not in (clone / "skills/quill/SKILL.md").read_text()


def test_refresh_follows_upstream_and_keeps_clone_pristine(
    upstream: Path, tmp_path: Path, synthetic_cairn_home: Path
) -> None:
    kb_skills = tmp_path / "kb" / ".claude" / "skills"
    skills.ensure_managed(kb_skills, fetch=True)
    home = Home(synthetic_cairn_home)
    assert skills.refresh(home)["quill"][str(kb_skills)]["status"] == "current"
    (upstream / "skills/quill/SKILL.md").write_text("# Synthetic Quill v2\n")
    (upstream / "skills/quill/references/new.md").write_text("New guidance.\n")
    latest = commit(upstream, "Synthetic Quill v2")
    report = skills.refresh(home)["quill"][str(kb_skills)]
    assert report["status"] == "updated" and report["commit"] == latest
    text = (kb_skills / "quill/SKILL.md").read_text()
    assert text.startswith("# Synthetic Quill v2") and HOOK_MARKER in text
    assert (kb_skills / "quill/references/new.md").is_file()
    clone = skills.clone_path(home, skills.QUILL)
    assert (
        subprocess.run(
            ["git", "-C", str(clone), "status", "--porcelain"], capture_output=True, check=True
        ).stdout
        == b""
    )
    assert not list(kb_skills.glob(".quill-*"))


def test_local_edits_and_unmanaged_skills_are_never_overwritten(
    upstream: Path, tmp_path: Path, synthetic_cairn_home: Path
) -> None:
    kb_skills = tmp_path / "kb" / ".claude" / "skills"
    skills.ensure_managed(kb_skills, fetch=True)
    edited = kb_skills / "quill/references/drafting.md"
    edited.write_text("Owner's own drafting notes.\n")
    (upstream / "skills/quill/SKILL.md").write_text("# Synthetic Quill v2\n")
    commit(upstream, "Synthetic Quill v2")
    home = Home(synthetic_cairn_home)
    assert skills.refresh(home)["quill"][str(kb_skills)]["status"] == "locally_modified"
    assert edited.read_text() == "Owner's own drafting notes.\n"

    owner = tmp_path / "owner-skills"
    (owner / "quill").mkdir(parents=True)
    (owner / "quill/SKILL.md").write_text("# Owner Quill\n")
    result = skills.ensure_managed(owner, fetch=True)
    assert result["updates"] == "unmanaged"
    assert (owner / "quill/SKILL.md").read_text().startswith("# Owner Quill")
    assert (
        skills.install_copy(
            owner, "quill", {"SKILL.md": b"x"}, source="channel", origin="o", commit="c"
        )["status"]
        == "unmanaged"
    )


def test_offline_setup_uses_bundled_snapshot_then_follows_channel(
    tmp_path: Path, synthetic_cairn_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CAIRN_QUILL_REPO", str(tmp_path / "unreachable"))
    kb_skills = tmp_path / "kb" / ".claude" / "skills"
    result = skills.ensure_managed(kb_skills, fetch=True)
    assert result["status"] == "installed" and result["source"] == "bundled"
    home = Home(synthetic_cairn_home)
    assert skills.refresh(home)["quill"]["status"] == "failed"
    work = synthetic_quill(tmp_path)
    monkeypatch.setenv("CAIRN_QUILL_REPO", str(work))
    assert skills.refresh(home)["quill"][str(kb_skills)]["status"] == "updated"
    assert (kb_skills / "quill/SKILL.md").read_text().startswith("# Synthetic Quill v1")


def test_synthetic_setup_is_bundled_and_unregistered(
    tmp_path: Path, synthetic_cairn_home: Path
) -> None:
    kb_skills = tmp_path / "kb" / ".claude" / "skills"
    assert skills.ensure_managed(kb_skills, fetch=False)["source"] == "bundled"
    assert skills.installs(Home(synthetic_cairn_home)).skills_dirs == {}


def test_finch_refresh_runs_only_finchs_own_updater(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def fake(command: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, b"", b"")

    finch_home = tmp_path / "synthetic-finch"
    environ = {"HOME": str(tmp_path), "FINCH_HOME": str(finch_home)}
    assert skills.refresh_finch(environ, run=fake)["status"] == "not_installed_by_finch_installer"
    finch_home.mkdir()
    (finch_home / "install.sh").write_text("#!/usr/bin/env bash\n")
    assert skills.refresh_finch(environ, run=fake)["status"] == "updated"
    assert calls == [["bash", str(finch_home / "install.sh"), "update"]]
