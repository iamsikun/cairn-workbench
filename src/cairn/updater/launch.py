"""Work done before the CLI starts when running from a managed runtime.

1. A knowledge base still bound to another installed runtime (for example, one whose
   rebind failed) is served by that runtime, so it never becomes unusable.
2. A one-time notice reports a completed update, like a self-updating terminal app.
3. When a check is due, a detached `cairn update run --if-due` starts in the background.

All of this is best-effort: it never blocks or fails the requested command.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from cairn.updater.home import Home, bound_release

REEXEC = "CAIRN_REEXEC"
DISABLE = "CAIRN_NO_AUTO_UPDATE"


def workspace_argument(argv: Sequence[str], environ: Mapping[str, str]) -> Path | None:
    for index, item in enumerate(argv):
        if item in ("--workspace", "-w") and index + 1 < len(argv):
            return Path(argv[index + 1])
        if item.startswith("--workspace="):
            return Path(item.split("=", 1)[1])
    value = environ.get("CAIRN_WORKSPACE")
    return Path(value) if value else None


def bound_runtime(home: Home, argv: Sequence[str], environ: Mapping[str, str]) -> Path | None:
    """The interpreter of the runtime this command's knowledge base is bound to, if other."""
    running = home.running_runtime()
    workspace = workspace_argument(argv, environ)
    if running is None or workspace is None or environ.get(REEXEC):
        return None
    bound = bound_release(workspace)
    if bound is None or bound == running.release_sha256 or home.installed(bound) is None:
        return None
    return home.python(bound)


def prelaunch(argv: Sequence[str] | None = None) -> None:
    try:
        _prelaunch(list(sys.argv[1:] if argv is None else argv))
    except Exception:  # noqa: BLE001 - never fail the requested command
        return


def _prelaunch(argv: list[str]) -> None:
    home = Home.from_env()
    if home.running_runtime() is None:
        return
    python = bound_runtime(home, argv, os.environ)
    if python is not None:
        os.environ[REEXEC] = "1"
        os.execv(python, [str(python), "-I", "-B", "-m", "cairn", *argv])
    config = home.config()
    if config is None or not config.enabled:
        return
    state = home.state()
    if state.notice and not state.notice_shown:
        print(state.notice, file=sys.stderr)
        state.notice_shown = True
        home.save_state(state)
    if argv[:1] == ["update"] or os.environ.get(DISABLE) or not home.due(config, state):
        return
    home.root.mkdir(parents=True, exist_ok=True, mode=0o700)
    with open(home.log, "ab") as log:
        subprocess.Popen(
            [sys.executable, "-I", "-B", "-m", "cairn", "update", "run", "--if-due", "--quiet"],
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            start_new_session=True,
            close_fds=True,
        )
