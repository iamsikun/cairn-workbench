from __future__ import annotations

import os
import subprocess

from cairn.errors import Blocked
from cairn.storage.history_safety import check_history_config, check_history_paths
from cairn.storage.workspace import Workspace


def snapshot(ws: Workspace, message: str) -> str:
    """Private local history; no hooks, remotes, inherited Git config, or network."""
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL="/dev/null", GIT_ATTR_NOSYSTEM="1")
    gitdir = ws.root / "history.git"
    common = [
        "git",
        "-c",
        "core.hooksPath=/dev/null",
        "-c",
        "core.fsmonitor=false",
        "-c",
        "gc.auto=0",
        "-c",
        "maintenance.auto=false",
        "-c",
        "protocol.allow=never",
        "-c",
        "user.name=Cairn local history",
        "-c",
        "user.email=cairn@localhost",
        f"--git-dir={gitdir}",
        f"--work-tree={ws.root}",
    ]

    def run(args: list[str]) -> subprocess.CompletedProcess[bytes]:
        try:
            return subprocess.run(
                args, cwd=ws.root, env=env, capture_output=True, timeout=30, check=True
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise Blocked("local_history_failed") from exc

    if not gitdir.exists():
        run(["git", "-c", "core.hooksPath=/dev/null", "init", "--bare", str(gitdir)])
    if gitdir.is_symlink():
        raise Blocked("unsafe_history_directory")
    check_history_paths(ws.fs.files("history.git"))
    check_history_config(ws.fs.read("history.git/config"))
    # Path list deliberately excludes blobs, caches, journals, and credentials.
    paths = ["workspace.json", "vault", "policy", "receipts", "approvals", "proposals", "evidence"]
    run([*common, "add", "--", *paths])
    status = run([*common, "status", "--porcelain", "--untracked-files=no"])
    if status.stdout:
        run([*common, "commit", "-m", message])
    return run([*common, "rev-parse", "HEAD"]).stdout.decode().strip()
