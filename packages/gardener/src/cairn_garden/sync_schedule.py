"""Install one daily Git sync as part of the optional gardener setup."""

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


def label(cfg):
    return f"{PREFIX}.{g.workspace_key(cfg)}"


def plist_path(cfg):
    return schedule.agents_folder() / f"{label(cfg)}.plist"


def launchctl(*args, check=True):
    result = subprocess.run(["launchctl", *args], capture_output=True, text=True, timeout=15)
    if check and result.returncode:
        raise sync.SyncError(f"launchctl {args[0]}: {result.stderr.strip()}")
    return result


def job(cfg, at):
    hour, minute = map(int, at.split(":"))
    return {
        "Label": label(cfg),
        "ProgramArguments": [sys.executable, "-m", "cairn_garden", "sync", "run", "--scheduled"],
        "WorkingDirectory": str(g.workspace(cfg).resolve()),
        "StartCalendarInterval": {"Hour": hour, "Minute": minute},
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


def plan(cfg, remote, branch, at, replace_plist=None):
    if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", at):
        raise sync.SyncError("--at must be a time such as 07:15 in the Mac's local timezone")
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
        "daily_time": at,
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


def install(cfg, remote="origin", branch="main", at="07:15", dry_run=False, replace_plist=None):
    value, replacement = plan(cfg, remote, branch, at, replace_plist)
    spec = job(cfg, at)
    result = {
        "dry_run": dry_run,
        "settings": value,
        "plist": str(plist_path(cfg)),
        "job": spec,
        "replace_plist": str(replacement) if replacement else None,
    }
    if dry_run:
        return result
    if sys.platform != "darwin":
        raise sync.SyncError("Local calendar scheduling requires macOS; --dry-run works anywhere")
    state = sync.state_dir(cfg)
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    with sync.lock(state / "sync.lock"):
        path = plist_path(cfg)
        path.parent.mkdir(parents=True, exist_ok=True)
        settings_path = state / "settings.json"
        previous = {p: p.read_bytes() if p.exists() else None for p in (path, settings_path)}
        domain = f"gui/{os.getuid()}"
        service = f"{domain}/{spec['Label']}"
        was_loaded = launchctl("print", service, check=False).returncode == 0
        old = plistlib.loads(replacement.read_bytes()) if replacement else None
        old_loaded = (
            old and launchctl("print", f"{domain}/{old['Label']}", check=False).returncode == 0
        )
        unload(spec["Label"])
        try:
            g.atomic_json(settings_path, value)
            path.write_bytes(plistlib.dumps(spec))
            launchctl("bootstrap", domain, str(path))
            launchctl("print", service)
            if replacement:
                unload(old["Label"])
                replacement.rename(replacement.with_suffix(".plist.disabled"))
        except Exception:
            # Restore the prior installation if registration or migration fails.
            unload(spec["Label"])
            for target, content in previous.items():
                if content is None:
                    target.unlink(missing_ok=True)
                else:
                    target.write_bytes(content)
            if was_loaded:
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
    loaded = None
    if sys.platform == "darwin":
        loaded = launchctl("print", f"gui/{os.getuid()}/{label(cfg)}", check=False).returncode == 0
    return {
        "installed": path.exists(),
        "loaded": loaded,
        "plist": str(path),
        "settings": g.read_json(state / "settings.json", None),
        "last_run": g.read_json(state / "status.json", None),
        "log": str(state / "sync.log"),
    }


def remove(cfg):
    if sys.platform != "darwin":
        raise sync.SyncError("Removing the local calendar schedule requires macOS")
    unload(label(cfg))
    path = plist_path(cfg)
    existed = path.exists()
    path.unlink(missing_ok=True)
    return {"removed": existed, "settings_preserved": True}
