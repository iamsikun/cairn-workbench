"""Historical runtime selection helpers; startup execution is retired."""

from __future__ import annotations

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
    """Compatibility entrypoint: startup updates and runtime re-execution are retired."""


def _prelaunch(argv: list[str]) -> None:
    """Compatibility entrypoint; deliberately has no side effects."""
