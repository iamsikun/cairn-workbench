"""Knowledge-base skills that follow their upstream stable release.

Cairn keeps a pristine clone of each upstream skill under CAIRN_HOME/skills/ and
fast-forwards it on every update run; the clone is never edited, so its own history
stays clean. Each knowledge base gets a generated, Cairn-managed copy: the upstream
files plus Cairn's writing handoff. A `.cairn-managed.json` marker records the bytes
Cairn wrote. A copy is replaced only while it still matches that marker; an owner's
local edits, or a skill directory Cairn did not create, are never overwritten.

Finch is installed machine-wide by its own installer, which schedules its own update;
the updater only invokes that installer's `update` command when it is present.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from pydantic import Field

from cairn.errors import CairnError, Conflict
from cairn.records.models import Digest, Model, canonical, digest, now
from cairn.updater.home import Home
from cairn.updater.source import git

MARKER = ".cairn-managed.json"
MAX_SKILL_FILE = 2 * 1024 * 1024
MAX_SKILL_FILES = 500


@dataclass(frozen=True)
class SkillSource:
    name: str
    repository_env: str
    repository: str
    ref: str
    subdirectory: str


QUILL = SkillSource(
    "quill", "CAIRN_QUILL_REPO", "https://github.com/iamsikun/quill.git", "stable", "skills/quill"
)


class ManagedSkill(Model):
    schema_version: int = 1
    name: str
    source: Literal["channel", "bundled"]
    repository: str
    commit: str
    installed_at: datetime
    files: dict[str, Digest] = Field(min_length=1)


class Installs(Model):
    schema_version: int = 1
    skills_dirs: dict[str, list[str]] = Field(default_factory=dict)


def repository(skill: SkillSource, environ: Mapping[str, str] | None = None) -> str:
    return (os.environ if environ is None else environ).get(skill.repository_env) or (
        skill.repository
    )


def clone_path(home: Home, skill: SkillSource) -> Path:
    return home.root / "skills" / skill.name


def sync_clone(home: Home, skill: SkillSource, environ: Mapping[str, str] | None = None) -> str:
    """Clone or fast-forward the pristine upstream copy; return its commit."""
    clone = clone_path(home, skill)
    if not (clone / ".git").is_dir():
        clone.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if clone.exists():
            shutil.rmtree(clone)
        git(
            clone.parent,
            "clone",
            "--quiet",
            "--branch",
            skill.ref,
            repository(skill, environ),
            clone.name,
        )
    else:
        git(clone, "fetch", "--quiet", repository(skill, environ), skill.ref)
        git(clone, "merge", "--quiet", "--ff-only", "FETCH_HEAD")
    return git(clone, "rev-parse", "HEAD").decode().strip()


def upstream_files(root: Path) -> dict[str, bytes]:
    if root.is_symlink() or not (root / "SKILL.md").is_file():
        raise Conflict("upstream skill layout is missing SKILL.md")
    files: dict[str, bytes] = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            raise Conflict("upstream skill contains a symlink")
        if not path.is_file() or relative == MARKER:
            continue
        if path.stat().st_size > MAX_SKILL_FILE or len(files) >= MAX_SKILL_FILES:
            raise Conflict("upstream skill exceeds the managed-copy limits")
        files[relative] = path.read_bytes()
    return files


def render_quill(files: dict[str, bytes]) -> dict[str, bytes]:
    """Upstream Quill plus the Cairn writing handoff; the upstream clone stays untouched."""
    from cairn.presentation.quill import HOOK, HOOK_MARKER, HOOK_SECTION, WORKFLOW

    rendered = dict(files)
    rendered.setdefault(HOOK, WORKFLOW.read_bytes())
    if HOOK_MARKER.encode() not in rendered["SKILL.md"]:
        rendered["SKILL.md"] += f"\n\n{HOOK_MARKER}\n{HOOK_SECTION}".encode()
    return rendered


def _safe_directory(skills_dir: Path) -> Path:
    root = skills_dir.absolute()
    if any(p.is_symlink() for p in (root, *root.parents)):
        raise Conflict("skill destination must not contain symlinks")
    return root


def _on_disk(directory: Path) -> dict[str, str] | None:
    try:
        return {name: digest(raw) for name, raw in upstream_files(directory).items()}
    except Conflict:
        return None


def install_copy(
    skills_dir: Path, name: str, files: dict[str, bytes], *, source: str, origin: str, commit: str
) -> dict[str, str]:
    root = _safe_directory(skills_dir)
    destination = root / name
    marker = destination / MARKER
    previous = None
    if destination.exists():
        if not marker.is_file():
            return {"status": "unmanaged", "path": str(destination)}
        previous = ManagedSkill.model_validate_json(marker.read_bytes())
        if _on_disk(destination) != previous.files:
            return {"status": "locally_modified", "path": str(destination)}
        if previous.commit == commit and previous.source == source:
            return {"status": "current", "path": str(destination), "commit": commit}
    record = ManagedSkill(
        name=name,
        source=source,  # type: ignore[arg-type]
        repository=origin,
        commit=commit,
        installed_at=now(),
        files={relative: digest(raw) for relative, raw in files.items()},
    )
    root.mkdir(parents=True, exist_ok=True)
    staging = root / f".{name}-{uuid4().hex}"
    try:
        for relative, raw in files.items():
            path = staging / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        (staging / MARKER).write_bytes(canonical(record))
        if previous is not None:
            retired = root / f".{name}-retired-{uuid4().hex}"
            os.rename(destination, retired)
            os.rename(staging, destination)
            shutil.rmtree(retired, ignore_errors=True)
        else:
            os.rename(staging, destination)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return {
        "status": "updated" if previous else "installed",
        "path": str(destination),
        "commit": commit,
    }


def _installs_path(home: Home) -> Path:
    return home.root / "skills" / "installs.json"


def installs(home: Home) -> Installs:
    path = _installs_path(home)
    return Installs.model_validate_json(path.read_bytes()) if path.is_file() else Installs()


def register(home: Home, name: str, skills_dir: Path) -> None:
    current = installs(home)
    directories = current.skills_dirs.setdefault(name, [])
    if str(skills_dir.absolute()) not in directories:
        directories.append(str(skills_dir.absolute()))
        path = _installs_path(home)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.write_bytes(canonical(current))


def ensure_managed(skills_dir: Path, *, fetch: bool, home: Home | None = None) -> dict[str, str]:
    """Install Quill for a knowledge base as a managed copy (or keep an existing one)."""
    from cairn.presentation import quill
    from cairn.presentation.writing_models import QUILL_REVISION

    destination = skills_dir / QUILL.name
    if destination.exists() and not (destination / MARKER).is_file():
        # An earlier or owner-made Quill: keep it and only attach the handoff, as before.
        return quill.install(skills_dir) | {"status": "installed", "updates": "unmanaged"}
    home = home or Home.from_env()
    track = fetch
    if fetch:
        try:
            commit = sync_clone(home, QUILL)
            files = upstream_files(clone_path(home, QUILL) / QUILL.subdirectory)
            source, origin = "channel", repository(QUILL)
        except CairnError:
            fetch = False
    if not fetch:
        snapshot = quill.skill_files()
        snapshot.pop(quill.HOOK, None)
        files, source, origin, commit = snapshot, "bundled", QUILL.repository, QUILL_REVISION
    result = install_copy(
        skills_dir, QUILL.name, render_quill(files), source=source, origin=origin, commit=commit
    )
    if track:
        register(home, QUILL.name, skills_dir)
    ok = result["status"] in ("installed", "updated", "current")
    status = "installed" if ok else result["status"]
    return result | {
        "status": status,
        "skill": QUILL.name,
        "source": source,
        "updates": "managed",
        "workflow": "packet_writing_and_proposals; owner_acceptance_required",
    }


def refresh_finch(
    environ: Mapping[str, str] | None = None,
    run: Callable[..., subprocess.CompletedProcess[bytes]] = subprocess.run,
) -> dict[str, str]:
    env = dict(os.environ if environ is None else environ)
    default = Path(env.get("HOME", "/nonexistent")) / ".local/share/finch"
    finch_home = Path(env["FINCH_HOME"]) if env.get("FINCH_HOME") else default
    installer = finch_home / "install.sh"
    if not installer.is_file():
        return {"status": "not_installed_by_finch_installer"}
    try:
        completed = run(
            ["bash", str(installer), "update"],
            env=env,
            capture_output=True,
            timeout=300,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {"status": "failed"}
    return {"status": "updated" if completed.returncode == 0 else "failed"}


def refresh(home: Home, config: object = None) -> dict[str, Any]:
    """Fast-forward managed skill clones and refresh every registered managed copy."""
    del config
    result: dict[str, Any] = {}
    registered = installs(home).skills_dirs.get(QUILL.name, [])
    if registered:
        try:
            commit = sync_clone(home, QUILL)
            files = render_quill(upstream_files(clone_path(home, QUILL) / QUILL.subdirectory))
        except CairnError as exc:
            result[QUILL.name] = {"status": "failed", "reason": str(exc)}
        else:
            result[QUILL.name] = {
                directory: install_copy(
                    Path(directory),
                    QUILL.name,
                    files,
                    source="channel",
                    origin=repository(QUILL),
                    commit=commit,
                )
                if Path(directory).is_dir()
                else {"status": "missing"}
                for directory in registered
            }
    result["finch"] = refresh_finch()
    return result


def status(home: Home) -> dict[str, Any]:
    report: dict[str, Any] = {}
    for directory in installs(home).skills_dirs.get(QUILL.name, []):
        marker = Path(directory) / QUILL.name / MARKER
        if marker.is_file():
            record = json.loads(marker.read_bytes())
            report[directory] = {"source": record["source"], "commit": record["commit"]}
        else:
            report[directory] = {"status": "missing_or_unmanaged"}
    return {"quill": report}
