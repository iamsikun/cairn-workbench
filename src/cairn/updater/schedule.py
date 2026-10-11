"""Periodic update job (launchd on macOS, cron elsewhere) and the `cairn` command shim."""

from __future__ import annotations

import os
import plistlib
import shlex
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from cairn.adapters.legacy import retired
from cairn.updater.home import Home, UpdaterConfig

LABEL = "io.github.iamsikun.cairn.update"
CRON_MARKER = "# cairn-auto-update"
INTERVAL_SECONDS = 3600  # Runs are cheap when not due; --if-due honours interval_hours.

type Runner = Callable[..., subprocess.CompletedProcess[bytes]]


def command(home: Home) -> list[str]:
    python = home.current / "venv" / "bin" / "python"
    return [str(python), "-I", "-B", "-m", "cairn", "update", "run", "--if-due", "--quiet"]


def launchd_plist(home: Home, config: UpdaterConfig) -> bytes:
    return plistlib.dumps(
        {
            "Label": LABEL,
            "ProgramArguments": command(home),
            "EnvironmentVariables": {"CAIRN_HOME": str(home.root), "PATH": config.path},
            "StartInterval": INTERVAL_SECONDS,
            "RunAtLoad": True,
            "ProcessType": "Background",
            "StandardOutPath": str(home.log),
            "StandardErrorPath": str(home.log),
        }
    )


def cron_line(home: Home, config: UpdaterConfig) -> str:
    env = f"CAIRN_HOME={shlex.quote(str(home.root))} PATH={shlex.quote(config.path)}"
    run = " ".join(shlex.quote(part) for part in command(home))
    return f"17 * * * * {env} {run} >> {shlex.quote(str(home.log))} 2>&1 {CRON_MARKER}"


def install(
    home: Home,
    config: UpdaterConfig,
    *,
    user_home: Path,
    platform: str = sys.platform,
    run: Runner = subprocess.run,
) -> dict[str, str]:
    retired("Managed update scheduling")


def remove(
    *, user_home: Path, platform: str = sys.platform, run: Runner = subprocess.run
) -> dict[str, str]:
    if platform == "darwin":
        plist = user_home / "Library" / "LaunchAgents" / f"{LABEL}.plist"
        if plist.is_file():
            run(
                ["launchctl", "bootout", f"gui/{os.getuid()}", str(plist)],
                capture_output=True,
                check=False,
            )
            plist.unlink()
        return {"scheduler": "launchd", "status": "removed"}
    existing = run(["crontab", "-l"], capture_output=True, check=False)
    if existing.returncode == 0 and CRON_MARKER in existing.stdout.decode():
        kept = [line for line in existing.stdout.decode().splitlines() if CRON_MARKER not in line]
        run(["crontab", "-"], input=("\n".join(kept) + "\n").encode(), capture_output=True)
    return {"scheduler": "cron", "status": "removed"}


def shim_bytes(home: Home) -> bytes:
    """Exact historical shim bytes for identification and synthetic fixtures."""
    python = shlex.quote(str(home.current / "venv" / "bin" / "python"))
    return (
        "#!/bin/sh\n"
        "# Installed by `cairn update setup`; runs the current verified Cairn runtime.\n"
        f'CAIRN_HOME="${{CAIRN_HOME:-{home.root}}}"\n'
        "export CAIRN_HOME\n"
        f'exec {python} -I -B -m cairn "$@"\n'
    ).encode()


def write_shim(home: Home, bin_dir: Path) -> Path:
    retired("Managed launcher installation")
