"""Read-only repository binding. No project code, Git hooks, or filters are executed."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from cairn.errors import Blocked, Conflict, Denied
from cairn.records.models import RepositoryBinding, canonical, digest
from cairn.storage.files import RootFS, disjoint


def inspect_repository(
    root: Path, *, alias: str, workspace_root: Path, run_ids: list[str] | None = None
) -> RepositoryBinding:
    if root.is_symlink() or not disjoint(root, workspace_root) or not (root / ".git").exists():
        raise Denied("repository root must be explicit and separate from the workspace")
    root = root.resolve()
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_OPTIONAL_LOCKS="0",
        GIT_TERMINAL_PROMPT="0",
    )

    def git(*args: str) -> bytes:
        command = [
            "git",
            "--no-pager",
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "core.fsmonitor=false",
            "-c",
            "protocol.allow=never",
            *args,
        ]
        result = subprocess.run(command, cwd=root, env=env, capture_output=True, timeout=30)
        if result.returncode or len(result.stdout) > 8 * 1024 * 1024:
            raise Blocked("repository binding unavailable")
        return result.stdout

    if Path(git("rev-parse", "--show-toplevel").decode().strip()).resolve() != root:
        raise Denied("select the repository root, not a subdirectory")
    commit = git("rev-parse", "--verify", "HEAD").decode().strip()
    index = git("ls-files", "--stage", "-z")
    names = git("ls-files", "--cached", "--others", "--exclude-standard", "-z")
    fs = RootFS(root)
    files: dict[str, str | None] = {}
    for name in sorted(set(names.decode("utf-8").split("\0")) - {""}):
        # A deletion is fingerprinted. Links, special files, submodules, oversized
        # blobs and undecodable names fail closed as unverified rather than skipped.
        files[name] = digest(fs.read(name)) if fs.exists(name) else None
    if (
        git("rev-parse", "--verify", "HEAD").decode().strip() != commit
        or git("ls-files", "--stage", "-z") != index
        or git("ls-files", "--cached", "--others", "--exclude-standard", "-z") != names
    ):
        raise Conflict("repository changed during inspection")
    # Recheck bytes to detect ordinary concurrent owner edits during the scan.
    for name, checksum in files.items():
        if (digest(fs.read(name)) if fs.exists(name) else None) != checksum:
            raise Conflict("repository changed during inspection")
    return RepositoryBinding(
        alias=alias,
        commit=commit,
        worktree_hash=digest(canonical({"index": digest(index), "files": files})),
        run_ids=run_ids or [],
    )
