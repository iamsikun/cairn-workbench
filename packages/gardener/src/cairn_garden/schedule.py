"""Install the launchd jobs only after both real workflows pass readiness."""

import os
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

from . import engine as g
from . import workflow

LABEL = "org.cairn-workbench.garden"
CATALOG_LABEL = "org.cairn-workbench.catalog"
ASTER_LABEL = "org.cairn-workbench.aster"
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


def catalog_job(keep_notes: bool = False) -> dict:
    """Refresh the journal catalog on Monday morning, before the weekly review is due.

    With `keep_notes` the cloud gardener's refresh keeps the catalog notes' status block.
    """
    log = str(g.HOME / "logs" / "launchd-catalog.log")
    update = ["update", *(["--keep-notes"] if keep_notes else [])]
    return {
        "Label": CATALOG_LABEL,
        "ProgramArguments": [sys.executable, "-m", "cairn_catalog", *update],
        "StartCalendarInterval": {"Weekday": 1, "Hour": 9, "Minute": 0},
        "StandardOutPath": log,
        "StandardErrorPath": log,
        "EnvironmentVariables": environment(),
    }


def aster_job() -> dict:
    """Collect new items with Aster every morning, before the daily digest is due."""
    binary = shutil.which(os.environ.get("CAIRN_ASTER") or "aster")
    if not binary:
        raise SystemExit("`aster` is not installed; install Aster first or omit --aster.")
    log = str(g.HOME / "logs" / "launchd-aster.log")
    keep = ("ASTER_CONFIG", "ASTER_DATA_DIR", "ASTER_CONTACT_EMAIL")
    return {
        "Label": ASTER_LABEL,
        "ProgramArguments": [binary, "refresh"],
        "StartCalendarInterval": {"Hour": 6, "Minute": 45},
        "StandardOutPath": log,
        "StandardErrorPath": log,
        "EnvironmentVariables": environment() | {k: os.environ[k] for k in keep if k in os.environ},
    }


def labels() -> list[str]:
    return [f"{LABEL}.{mode}" for mode in MODES] + [CATALOG_LABEL, ASTER_LABEL]


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


def install(catalog: bool = False, aster: bool = False, only: bool = False) -> dict:
    """`only` installs just the catalog and Aster jobs, for a knowledge base gardened elsewhere
    (GitHub Actions), whose local pages still need a fresh catalog; it needs no readiness."""
    project = project_environment()
    if project:
        raise SystemExit(PROJECT_ENVIRONMENT.format(project))
    if only and not (catalog or aster):
        raise SystemExit("--only needs --catalog or --aster")
    cfg = g.config()
    if not only:
        check = workflow.readiness(cfg)
        if not check["ready"]:
            g.out(check)
            raise SystemExit(
                "Schedules remain disabled: run and verify daily and weekly on this release first."
            )
        if cfg.get("zotero_backend") in ("local", "web") and not workflow.scheduled_writes_enabled(
            cfg
        ):
            workflow.enable_scheduled_writes(cfg)
    folder = agents_folder()
    folder.mkdir(parents=True, exist_ok=True)
    (g.HOME / "logs").mkdir(parents=True, exist_ok=True)
    domain = f"gui/{os.getuid()}"
    jobs = [] if only else [job(mode) for mode in MODES]
    jobs += [catalog_job(keep_notes=only)] if catalog else []
    jobs += [aster_job()] if aster else []
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
        "daily": None if only else "07:30",
        "weekly": None if only else "Monday 10:30",
        "catalog": "Monday 09:00" if catalog else None,
        "aster": "06:45" if aster else None,
        "poll_seconds": 900,
    }
