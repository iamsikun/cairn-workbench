import base64
import json
import subprocess
from pathlib import Path

import pytest

from cairn.errors import Conflict
from cairn.saving.installation import retire
from cairn.updater.home import Busy, Home, UpdaterConfig
from cairn.updater.schedule import LABEL, cron_line, launchd_plist, shim_bytes


class Scheduler:
    """Explicit adapter fake: not an actual client, scheduler or installed-runtime trial."""

    def __init__(self, home, config):
        self.cron = ("0 1 * * * other-task\n" + cron_line(home, config) + "\n").encode()
        self.active = b""
        self.loaded = True
        self.fail = False

    def __call__(self, command, **kwargs):
        code, output, error = 0, b"", b""
        if "-c" in command:
            output = json.dumps(
                {
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
            ).encode()
        elif command == ["crontab", "-l"]:
            output = self.cron
        elif command == ["crontab", "-"]:
            if self.fail:
                code = 1
            else:
                self.cron = kwargs["input"]
        elif command[0] == "launchctl":
            if command[1] == "bootout" and not self.fail:
                self.loaded = False
            if command[1] == "print" and not self.loaded:
                code, error = 1, b"Could not find service"
        elif command[0] == "ps":
            output = self.active
        else:
            raise AssertionError(command)
        return subprocess.CompletedProcess(command, code, output, error)


def setup(tmp_path):
    home = Home(tmp_path / "managed")
    home.root.mkdir()
    config = UpdaterConfig(repository="https://example.invalid/synthetic.git")
    home.save_config(config)
    owner = tmp_path / "synthetic-home"
    owner.mkdir()
    shim = owner / "bin" / "cairn"
    shim.parent.mkdir()
    shim.write_bytes(shim_bytes(home))
    shim.chmod(0o755)
    return home, config, owner, shim, Scheduler(home, config)


@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_retirement_preserves_unrelated_jobs_and_rollback_bytes(tmp_path: Path, platform):
    home, config, owner, shim, run = setup(tmp_path)
    original = shim.read_bytes()
    if platform == "darwin":
        folder = owner / "Library" / "LaunchAgents"
        folder.mkdir(parents=True)
        (folder / f"{LABEL}.plist").write_bytes(launchd_plist(home, config))
        (folder / "other.plist").write_bytes(b"unrelated")
    result = retire(
        home.root, owner, shim, Path("/synthetic/new/python"), platform=platform, run=run
    )
    assert result["status"] == "retired" and not home.config().enabled
    assert b"no startup updater" in shim.read_bytes()
    journal = json.loads((home.root / "transition/retirement.json").read_bytes())
    assert base64.b64decode(journal["original_launcher"]) == original
    assert (
        retire(home.root, owner, shim, Path("/synthetic/new/python"), platform=platform, run=run)
        == result
    )
    if platform == "darwin":
        assert (folder / "other.plist").read_bytes() == b"unrelated"
    else:
        assert run.cron == b"0 1 * * * other-task\n"


def test_active_updater_and_prelock_race_never_pass_retirement(tmp_path: Path):
    home, config, owner, shim, run = setup(tmp_path)
    with home.lock(), pytest.raises(Busy):
        retire(home.root, owner, shim, Path("/synthetic/new/python"), platform="linux", run=run)
    run.active = f"123 {home.current}/venv/bin/python -I -B -m cairn update run\n".encode()
    with pytest.raises(Busy):
        retire(home.root, owner, shim, Path("/synthetic/new/python"), platform="linux", run=run)
    assert not home.config().enabled
    assert not (home.root / "retired.json").exists()
    run.active = b""
    assert (
        retire(home.root, owner, shim, Path("/synthetic/new/python"), platform="linux", run=run)[
            "status"
        ]
        == "retired"
    )


def test_unknown_launcher_and_scheduler_failure_preserve_recovery(tmp_path: Path):
    home, config, owner, shim, run = setup(tmp_path)
    original = shim.read_bytes()
    shim.write_bytes(b"unrelated launcher")
    with pytest.raises(Conflict):
        retire(home.root, owner, shim, Path("/synthetic/new/python"), platform="linux", run=run)
    assert shim.read_bytes() == b"unrelated launcher"
    shim.write_bytes(original)
    run.fail = True
    with pytest.raises(Conflict):
        retire(home.root, owner, shim, Path("/synthetic/new/python"), platform="linux", run=run)
    assert not home.config().enabled and shim.read_bytes() == original
    run.fail = False
    assert (
        retire(home.root, owner, shim, Path("/synthetic/new/python"), platform="linux", run=run)[
            "status"
        ]
        == "retired"
    )


def test_missing_plist_is_not_evidence_a_loaded_job_was_removed(tmp_path: Path):
    home, config, owner, shim, run = setup(tmp_path)
    with pytest.raises(Conflict, match="not verified absent"):
        retire(home.root, owner, shim, Path("/synthetic/new/python"), platform="darwin", run=run)
    assert not (home.root / "retired.json").exists()
    assert not home.config().enabled
    run.loaded = False
    assert (
        retire(home.root, owner, shim, Path("/synthetic/new/python"), platform="darwin", run=run)[
            "status"
        ]
        == "retired"
    )
