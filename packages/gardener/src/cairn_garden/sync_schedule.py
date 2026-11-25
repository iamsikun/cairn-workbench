"""Install quick and scheduled Git sync as part of the optional gardener setup."""

from __future__ import annotations

import os
import plistlib
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

from . import engine as g
from . import reports, schedule, sync

PREFIX = "org.cairn-workbench.sync"
# Morning, before the cloud daily run; early afternoon, after its digest has usually landed.
DEFAULT_TIMES = ("07:15", "13:15")
# Hourly retries after sleep, a busy gardener or a network failure. Due slots decide what runs.
RETRY_SECONDS = 3600
# The quick job looks for settled edits this often; an idle look stays local and silent.
QUICK_SECONDS = 60


def label(cfg):
    return f"{PREFIX}.{g.workspace_key(cfg)}"


def plist_path(cfg):
    return schedule.agents_folder() / f"{label(cfg)}.plist"


def quick_label(cfg):
    return f"{label(cfg)}.quick"


def quick_plist_path(cfg):
    return schedule.agents_folder() / f"{quick_label(cfg)}.plist"


def launchctl(*args, check=True):
    result = subprocess.run(["launchctl", *args], capture_output=True, text=True, timeout=15)
    if check and result.returncode:
        raise sync.SyncError(f"launchctl {args[0]}: {result.stderr.strip()}")
    return result


def job(cfg, at):
    return {
        "Label": label(cfg),
        "ProgramArguments": [sys.executable, "-m", "cairn_garden", "sync", "run", "--scheduled"],
        "WorkingDirectory": str(g.workspace(cfg).resolve()),
        "StartCalendarInterval": [
            {"Hour": int(t[:2]), "Minute": int(t[3:])} for t in sorted(set(at))
        ],
        "StartInterval": RETRY_SECONDS,
        "ProcessType": "Background",
        "LowPriorityIO": True,
        "StandardOutPath": "/dev/null",
        "StandardErrorPath": str(sync.state_dir(cfg) / "launchd-error.log"),
        "EnvironmentVariables": {
            **schedule.environment(),
            "PATH": os.pathsep.join(
                [
                    str(Path.home() / ".local/bin"),
                    "/opt/homebrew/bin",
                    "/usr/local/bin",
                    "/usr/bin",
                    "/bin",
                ]
            ),
            "CAIRN_WORKSPACE": str(g.workspace(cfg).resolve()),
            "CAIRN_COLLECTION": cfg["collection"],
        },
    }


def quick_job(cfg):
    spec = job(cfg, DEFAULT_TIMES)
    del spec["StartCalendarInterval"]
    spec.update(
        Label=quick_label(cfg),
        ProgramArguments=[*spec["ProgramArguments"][:-1], "--quick"],
        StartInterval=QUICK_SECONDS,
        # It runs every minute: failures go to the rotating sync log, never to a growing file.
        StandardErrorPath="/dev/null",
    )
    return spec


def plan(cfg, remote, branch, at, replace_plist=None, quick=True, quiet=sync.QUIET_SECONDS):
    if not at or not all(re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", t) for t in at):
        raise sync.SyncError("--at must be a time such as 07:15 in the Mac's local timezone")
    if not 30 <= quiet <= 3600:
        raise sync.SyncError("--quiet-minutes must be between 0.5 and 60")
    root = g.kb_open(cfg).root
    worker = sync.Sync({"workspace": str(root), "remote": remote, "branch": branch})
    # Never let user-supplied remote/branch names become command-line options.
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", remote):
        raise sync.SyncError("Remote must be an existing Git remote name")
    worker.git("check-ref-format", "--branch", branch)
    url = worker.output("remote", "get-url", remote)
    if urlsplit(url).scheme in ("http", "https") and "@" in urlsplit(url).netloc:
        raise sync.SyncError(
            "Use a Git credential helper, not credentials embedded in the remote URL"
        )
    value = {
        "workspace": str(root),
        "remote": remote,
        "branch": branch,
        "expected_remote_url": url,
        "times": sorted(set(at)),
        "quick": bool(quick),
        "quiet_seconds": int(quiet),
        "note_folders": [f"{name}/" for name in g.cairn().COLLECTIONS]
        + [reports.root(cfg).resolve().relative_to(root).as_posix() + "/"],
    }
    worker = sync.Sync(value)
    worker.validate()
    if worker.git("check-ignore", "--quiet", ".cairn.lock", check=False).returncode:
        raise sync.SyncError("Add .cairn.lock to the KB's .gitignore before enabling sync")
    # merge-tree --write-tree was added in Git 2.38; require it before enabling a job.
    version = re.search(r"(\d+)\.(\d+)", worker.output("version"))
    if not version or tuple(map(int, version.groups())) < (2, 38):
        raise sync.SyncError("Git 2.38 or newer is required for conflict checks")
    replacement = None
    if replace_plist:
        replacement = replace_plist.expanduser().absolute()
        if replacement.parent != schedule.agents_folder().absolute() or replacement == plist_path(
            cfg
        ):
            raise sync.SyncError(
                "--replace-plist must select a different job in ~/Library/LaunchAgents"
            )
        old = plistlib.loads(replacement.read_bytes())
        if not isinstance(old.get("Label"), str):
            raise sync.SyncError("Replacement plist has no launchd Label")
        if old["Label"] == label(cfg):
            raise sync.SyncError("Replacement plist is already the managed sync job")
        if replacement.with_suffix(".plist.disabled").exists():
            raise sync.SyncError("A disabled copy of the selected old plist already exists")
    return value, replacement


def unload(label):
    service = f"gui/{os.getuid()}/{label}"
    if launchctl("print", service, check=False).returncode == 0:
        launchctl("bootout", service)


def install(
    cfg,
    remote="origin",
    branch="main",
    at=DEFAULT_TIMES,
    dry_run=False,
    replace_plist=None,
    quick=True,
    quiet=sync.QUIET_SECONDS,
):
    at = [at] if isinstance(at, str) else list(at)
    value, replacement = plan(cfg, remote, branch, at, replace_plist, quick, quiet)
    spec = job(cfg, at)
    fast = quick_job(cfg) if quick else None
    project = schedule.project_environment()
    result = {
        "dry_run": dry_run,
        "settings": value,
        "plist": str(plist_path(cfg)),
        "job": spec,
        "quick_plist": str(quick_plist_path(cfg)),
        "quick_job": fast,
        "quiet_minutes": value["quiet_seconds"] / 60 if quick else None,
        "replace_plist": str(replacement) if replacement else None,
    }
    if project:
        result["warning"] = schedule.PROJECT_ENVIRONMENT.format(project)
    if dry_run:
        return result
    if sys.platform != "darwin":
        raise sync.SyncError("Local calendar scheduling requires macOS; --dry-run works anywhere")
    if project:
        raise sync.SyncError(result["warning"])
    state = sync.state_dir(cfg)
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    with sync.lock(state / "sync.lock"):
        # The daily job and, unless quick sync is off, the quick job; re-running setup
        # replaces both in place.
        jobs = {plist_path(cfg): spec, quick_plist_path(cfg): fast}
        for path in jobs:
            path.parent.mkdir(parents=True, exist_ok=True)
        settings_path = state / "settings.json"
        previous = {p: p.read_bytes() if p.exists() else None for p in (*jobs, settings_path)}
        domain = f"gui/{os.getuid()}"
        names = {plist_path(cfg): label(cfg), quick_plist_path(cfg): quick_label(cfg)}
        was_loaded = {
            path: launchctl("print", f"{domain}/{name}", check=False).returncode == 0
            for path, name in names.items()
        }
        old = plistlib.loads(replacement.read_bytes()) if replacement else None
        old_loaded = (
            old and launchctl("print", f"{domain}/{old['Label']}", check=False).returncode == 0
        )
        for name in names.values():
            unload(name)
        try:
            g.atomic_json(settings_path, value)
            for path, content in jobs.items():
                if content is None:
                    path.unlink(missing_ok=True)
                    continue
                path.write_bytes(plistlib.dumps(content))
                launchctl("bootstrap", domain, str(path))
                launchctl("print", f"{domain}/{content['Label']}")
            if replacement:
                unload(old["Label"])
                replacement.rename(replacement.with_suffix(".plist.disabled"))
        except Exception:
            # Restore the prior installation if registration or migration fails.
            for name in names.values():
                unload(name)
            for target, content in previous.items():
                if content is None:
                    target.unlink(missing_ok=True)
                else:
                    target.write_bytes(content)
            for path, loaded in was_loaded.items():
                if loaded:
                    launchctl("bootstrap", domain, str(path))
            if (
                old_loaded
                and launchctl("print", f"{domain}/{old['Label']}", check=False).returncode
            ):
                launchctl("bootstrap", domain, str(replacement))
            raise
    return {**result, "enabled": True}


def status(cfg):
    state = sync.state_dir(cfg)
    path = plist_path(cfg)
    loaded = quick_loaded = None
    if sys.platform == "darwin":
        domain = f"gui/{os.getuid()}"
        loaded = launchctl("print", f"{domain}/{label(cfg)}", check=False).returncode == 0
        quick_loaded = (
            launchctl("print", f"{domain}/{quick_label(cfg)}", check=False).returncode == 0
        )
    return {
        "installed": path.exists(),
        "loaded": loaded,
        "plist": str(path),
        "quick_installed": quick_plist_path(cfg).exists(),
        "quick_loaded": quick_loaded,
        "settings": g.read_json(state / "settings.json", None),
        "last_run": g.read_json(state / "status.json", None),
        "log": str(state / "sync.log"),
    }


def remove(cfg):
    if sys.platform != "darwin":
        raise sync.SyncError("Removing the local calendar schedule requires macOS")
    existed = False
    for name, path in ((label(cfg), plist_path(cfg)), (quick_label(cfg), quick_plist_path(cfg))):
        unload(name)
        existed = path.exists() or existed
        path.unlink(missing_ok=True)
    return {"removed": existed, "settings_preserved": True}
