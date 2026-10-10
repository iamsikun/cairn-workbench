"""Periodic update job (launchd on macOS, cron elsewhere) and the `cairn` command shim."""

from __future__ import annotations

import os
import plistlib
import shlex
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

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
    if platform == "darwin":
        plist = user_home / "Library" / "LaunchAgents" / f"{LABEL}.plist"
        plist.parent.mkdir(parents=True, exist_ok=True)
        plist.write_bytes(launchd_plist(home, config))
        domain = f"gui/{os.getuid()}"
        run(["launchctl", "bootout", domain, str(plist)], capture_output=True, check=False)
        loaded = run(["launchctl", "bootstrap", domain, str(plist)], capture_output=True)
        state = "scheduled" if loaded.returncode == 0 else "written_not_loaded"
        return {"scheduler": "launchd", "path": str(plist), "status": state}
    existing = run(["crontab", "-l"], capture_output=True, check=False)
    lines = [
        line
        for line in (existing.stdout.decode() if existing.returncode == 0 else "").splitlines()
        if CRON_MARKER not in line
    ]
    lines.append(cron_line(home, config))
    written = run(["crontab", "-"], input=("\n".join(lines) + "\n").encode(), capture_output=True)
    return {"scheduler": "cron", "status": "scheduled" if written.returncode == 0 else "failed"}


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


def write_shim(home: Home, bin_dir: Path) -> Path:
    """A `cairn` command that always runs the current verified runtime."""
    bin_dir.mkdir(parents=True, exist_ok=True)
    shim = bin_dir / "cairn"
    python = shlex.quote(str(home.current / "venv" / "bin" / "python"))
    shim.write_text(
        "#!/bin/sh\n"
        "# Installed by `cairn update setup`; runs the current verified Cairn runtime.\n"
        f'CAIRN_HOME="${{CAIRN_HOME:-{home.root}}}"\n'
        "export CAIRN_HOME\n"
        f'exec {python} -I -B -m cairn "$@"\n'
    )
    shim.chmod(0o755)
    return shim
