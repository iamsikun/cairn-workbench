"""Install the launchd jobs only after both real workflows pass readiness."""

import os
import plistlib
import subprocess
import sys
from pathlib import Path

from . import engine as g
from . import workflow

LABEL = "org.cairn-workbench.garden"
CATALOG_LABEL = "org.cairn-workbench.catalog"
MODES = ("daily", "weekly")


def agents_folder() -> Path:
    return Path.home() / "Library/LaunchAgents"


PROJECT_ENVIRONMENT = (
    "This interpreter belongs to the project at {}; a schedule would run that checkout's "
    "current branch. Run setup from the installed tool (`uv tool install`) instead."
)


def project_environment() -> Path | None:
    """The project whose `uv run` environment this is, if it is not an installed tool."""
    prefix = Path(sys.prefix)
    return prefix.parent if (prefix.parent / "pyproject.toml").exists() else None


def environment() -> dict:
    return {
        "HOME": str(Path.home()),
        "CAIRN_GARDEN_STATE": str(g.HOME),
        "CAIRN_WORKBENCH_CONFIG": str(g.CONFIG_FILE),
    }


def job(mode: str) -> dict:
    """Every 15 minutes; the runner itself decides whether a period is due."""
    log = str(g.HOME / "logs" / f"launchd-{mode}.log")
    return {
        "Label": f"{LABEL}.{mode}",
        "ProgramArguments": [sys.executable, "-m", "cairn_garden", mode, "--scheduled"],
        "StartInterval": 900,
        "RunAtLoad": True,
        "StandardOutPath": log,
        "StandardErrorPath": log,
        "EnvironmentVariables": environment(),
    }


def catalog_job() -> dict:
    """Refresh the journal catalog on Monday morning, before the weekly review is due."""
    log = str(g.HOME / "logs" / "launchd-catalog.log")
    return {
        "Label": CATALOG_LABEL,
        "ProgramArguments": [sys.executable, "-m", "cairn_catalog", "update"],
        "StartCalendarInterval": {"Weekday": 1, "Hour": 9, "Minute": 0},
        "StandardOutPath": log,
        "StandardErrorPath": log,
        "EnvironmentVariables": environment(),
    }


def labels() -> list[str]:
    return [f"{LABEL}.{mode}" for mode in MODES] + [CATALOG_LABEL]


def remove() -> dict:
    domain = f"gui/{os.getuid()}"
    removed = []
    for label in labels():
        path = agents_folder() / f"{label}.plist"
        subprocess.run(["launchctl", "bootout", f"{domain}/{label}"], capture_output=True)
        if path.exists():
            path.unlink()
            removed.append(label)
    return {"removed": removed}


def install(catalog: bool = False) -> dict:
    project = project_environment()
    if project:
        raise SystemExit(PROJECT_ENVIRONMENT.format(project))
    cfg = g.config()
    check = workflow.readiness(cfg)
    if not check["ready"]:
        g.out(check)
        raise SystemExit(
            "Schedules remain disabled: run and verify daily and weekly on this release first."
        )
    if cfg.get("zotero_backend") in ("local", "web"):
        workflow.enable_scheduled_writes(cfg)
    folder = agents_folder()
    folder.mkdir(parents=True, exist_ok=True)
    (g.HOME / "logs").mkdir(parents=True, exist_ok=True)
    domain = f"gui/{os.getuid()}"
    jobs = [job(mode) for mode in MODES] + ([catalog_job()] if catalog else [])
    for spec in jobs:
        path = folder / f"{spec['Label']}.plist"
        path.write_bytes(plistlib.dumps(spec))
        subprocess.run(["launchctl", "bootout", f"{domain}/{spec['Label']}"], capture_output=True)
        subprocess.run(["launchctl", "bootstrap", domain, str(path)], check=True)
        subprocess.run(
            ["launchctl", "print", f"{domain}/{spec['Label']}"], check=True, capture_output=True
        )
    return {
        "enabled": [spec["Label"] for spec in jobs],
        "timezone": cfg["timezone"],
        "daily": "07:30",
        "weekly": "Monday 10:30",
        "catalog": "Monday 09:00" if catalog else None,
        "poll_seconds": 900,
    }
