"""Explicit retirement of an identified managed installation, separate from migration."""

import base64
import fcntl
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

from cairn.errors import Conflict, Denied
from cairn.records.models import canonical, digest
from cairn.storage.files import RootFS, disjoint
from cairn.updater.home import Busy, Home, UpdaterConfig
from cairn.updater.schedule import LABEL, Runner, cron_line, launchd_plist


def _old_shim(home: Home) -> bytes:
    python = shlex.quote(str(home.current / "venv" / "bin" / "python"))
    return (
        "#!/bin/sh\n"
        "# Installed by `cairn update setup`; runs the current verified Cairn runtime.\n"
        f'CAIRN_HOME="${{CAIRN_HOME:-{home.root}}}"\n'
        "export CAIRN_HOME\n"
        f'exec {python} -I -B -m cairn "$@"\n'
    ).encode()


def retire(
    managed_home: Path,
    user_home: Path,
    launcher: Path,
    python: Path,
    *,
    platform: str = sys.platform,
    run: Runner = subprocess.run,
) -> dict[str, Any]:
    home = Home(managed_home.absolute())
    fs, owner = RootFS(home.root), RootFS(user_home)
    binary = RootFS(launcher.absolute().parent)
    if not disjoint(home.root, python.resolve()):
        raise Denied("replacement Python must be outside the managed runtime tree")
    replacement = (
        "#!/bin/sh\n# Cairn direct-save launcher; no startup updater.\n"
        f'exec {shlex.quote(str(python.absolute()))} -I -B -m cairn "$@"\n'
    ).encode()
    with fs.parent("update.lock") as (parent, name):
        fd = os.open(name, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600, dir_fd=parent)
    try:
        fs._regular(os.fstat(fd))
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise Busy(
                "updater is running; let it finish and retry retirement before migration"
            ) from exc
        path = "transition/retirement.json"
        config = UpdaterConfig.model_validate_json(fs.read("updater.json"))
        current = binary.read(launcher.name)
        if fs.exists(path):
            journal = json.loads(fs.read(path))
            if journal["launcher"] != str(launcher.absolute()) or journal[
                "replacement_hash"
            ] != digest(replacement):
                raise Conflict(
                    "resume retirement with its original launcher and replacement Python"
                )
            if current not in (_old_shim(home), replacement):
                raise Conflict("launcher changed during retirement; preserved")
        else:
            if current != _old_shim(home):
                raise Conflict("launcher is not the identified Cairn-owned shim")
            trial = run(
                [
                    str(python),
                    "-I",
                    "-B",
                    "-c",
                    "import json; from cairn.saving.models import WorkspaceConfigV4; "
                    "from cairn.saving.mcp import TOOLS; "
                    "print(json.dumps({'schema': "
                    "WorkspaceConfigV4.model_fields['schema_version'].default, "
                    "'tools': sorted(TOOLS)}))",
                ],
                capture_output=True,
                check=False,
                timeout=30,
            )
            expected = {
                "schema": 4,
                "tools": [
                    "capture",
                    "get_note",
                    "list_topics",
                    "save_note",
                    "save_reading",
                    "search",
                ],
            }
            if trial.returncode or json.loads(trial.stdout) != expected:
                raise Denied("replacement runtime did not pass the direct-save interface check")
            journal = {
                "status": "prepared",
                "launcher": str(launcher.absolute()),
                "replacement_hash": digest(replacement),
                "original_config": config.model_dump(mode="json"),
                "original_launcher": base64.b64encode(current).decode(),
                "scheduler": None,
            }
            fs.write(path, canonical(journal), exclusive=True)
        # Disable launch-triggered checks before touching scheduling. Keep disabled on failure.
        config.enabled = False
        fs.write("updater.json", canonical(config))
        if platform == "darwin":
            plist = f"Library/LaunchAgents/{LABEL}.plist"
            if owner.exists(plist):
                raw = owner.read(plist)
                original_config = UpdaterConfig.model_validate(journal["original_config"])
                if raw != launchd_plist(home, original_config):
                    raise Conflict("launchd entry differs from the identified Cairn job")
                if journal["scheduler"] is None:
                    journal["scheduler"] = {
                        "platform": platform,
                        "path": plist,
                        "original": base64.b64encode(raw).decode(),
                    }
                    fs.write(path, canonical(journal))
                result = run(
                    ["launchctl", "bootout", f"gui/{os.getuid()}", str(user_home / plist)],
                    capture_output=True,
                    check=False,
                    timeout=30,
                )
                probe = run(
                    ["launchctl", "print", f"gui/{os.getuid()}/{LABEL}"],
                    capture_output=True,
                    check=False,
                    timeout=30,
                )
                if probe.returncode == 0 or (
                    result.returncode and b"Could not find service" not in probe.stderr
                ):
                    raise Conflict("could not verify that the scheduled updater is unloaded")
                owner.remove(plist)
            # A loaded launchd job can outlive a deleted plist. Absence of the file
            # is not evidence that scheduling has stopped.
            unloaded = run(
                ["launchctl", "print", f"gui/{os.getuid()}/{LABEL}"],
                capture_output=True,
                check=False,
                timeout=30,
            )
            if unloaded.returncode == 0 or b"Could not find service" not in unloaded.stderr:
                raise Conflict(
                    "scheduled updater is not verified absent; reconcile its launchd job"
                )
        else:
            existing = run(["crontab", "-l"], capture_output=True, check=False, timeout=30)
            if existing.returncode and b"no crontab" not in existing.stderr.lower():
                raise Conflict("cannot inspect the update schedule")
            cron_text = existing.stdout.decode() if existing.returncode == 0 else ""
            expected_line = cron_line(
                home, UpdaterConfig.model_validate(journal["original_config"])
            )
            if expected_line in cron_text.splitlines():
                if journal["scheduler"] is None:
                    journal["scheduler"] = {
                        "platform": platform,
                        "original": base64.b64encode(cron_text.encode()).decode(),
                    }
                    fs.write(path, canonical(journal))
                kept = (
                    "\n".join(line for line in cron_text.splitlines() if line != expected_line)
                    + "\n"
                )
                result = run(
                    ["crontab", "-"],
                    input=kept.encode(),
                    capture_output=True,
                    check=False,
                    timeout=30,
                )
                verified = run(["crontab", "-l"], capture_output=True, check=False, timeout=30)
                if result.returncode or verified.returncode or verified.stdout != kept.encode():
                    raise Conflict("could not verify removal of the scheduled updater")
            elif str(home.root) in cron_text and "cairn-auto-update" in cron_text:
                raise Conflict("Cairn cron entry changed; preserve it for explicit reconciliation")
        binary.write(launcher.name, replacement)
        with binary.parent(launcher.name) as (parent, leaf):
            os.chmod(leaf, 0o755, dir_fd=parent, follow_symlinks=False)
        processes = run(["ps", "-axo", "pid=,args="], capture_output=True, check=False, timeout=30)
        if processes.returncode:
            raise Conflict("cannot verify updater process quiescence")
        active = [
            line
            for line in processes.stdout.decode().splitlines()
            if str(home.root) in line
            and any(
                command in line
                for command in (
                    "-m cairn update",
                    "-m cairn legacy update",
                    "/cairn update",
                    "/cairn legacy update",
                )
            )
        ]
        if active:
            raise Busy(
                "an updater process is still running; scheduling is disabled; retry after it exits"
            )
        journal["status"] = "retired"
        fs.write(path, canonical(journal))
        fs.write(
            "retired.json",
            canonical({"replacement_hash": digest(replacement), "automatic_updates": False}),
        )
        return {
            "status": "retired",
            "scheduler": "disabled",
            "startup_updates": "disabled",
            "rollback_artifacts": str(home.root / path),
            "workspaces_migrated": False,
        }
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
