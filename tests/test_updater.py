"""Updater cycle against a synthetic CAIRN_HOME and a local versioned channel.

Docker, uv, the release build and the new runtime's commands are simulated by a fake
runner: these tests cover selection, ordering, failure handling and state, not a live
build, installation or worker isolation.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from synthetic_channel import channel
from test_release import manifest
from typer.testing import CliRunner

from cairn.cli import app
from cairn.errors import Conflict, Denied
from cairn.records.models import canonical, digest, now
from cairn.storage.release import requirements
from cairn.updater import launch, schedule, service
from cairn.updater.home import Home, RuntimeInfo, UpdaterConfig
from cairn.updater.source import source_hash


class FakeRunner:
    """Records commands and emulates the build, install and new-runtime steps."""

    def __init__(self, home: Home, *, fail: str | None = None, revision: str | None = None):
        self.home = home
        self.fail = fail
        self.revision = revision
        self.commands: list[list[str]] = []

    def __call__(self, command: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        self.commands.append(command)
        text = " ".join(command)
        if self.fail and self.fail in text:
            return subprocess.CompletedProcess(command, 1, b"", b"synthetic failure")
        stdout = b""
        if command[:3] == ["docker", "image", "inspect"]:
            stdout = ("sha256:" + "2" * 64).encode()
        elif "scripts/build_release.py" in command:
            self.build(Path(command[command.index("--output") + 1]), command)
        elif command[:2] == ["uv", "venv"]:
            python = Path(command[-1]) / "bin" / "python"
            python.parent.mkdir(parents=True)
            python.write_text("synthetic interpreter placeholder")
        elif "rebind" in command:
            workspace = command[command.index("--workspace") + 1]
            stdout = json.dumps({"status": "upgraded", "workspace": workspace}).encode()
        return subprocess.CompletedProcess(command, 0, stdout, b"")

    def build(self, output: Path, command: list[str]) -> None:
        revision = command[command.index("--revision") + 1]
        built = manifest().model_copy(
            update={
                "code_revision": self.revision or revision,
                "source_hash": source_hash(self.home.mirror, revision),
            }
        )
        (output / "wheels").mkdir(parents=True)
        (output / "wheels" / built.artifacts[0].filename).write_bytes(b"synthetic wheel")
        (output / "uv.lock").write_bytes(b"synthetic lock")
        (output / "requirements.txt").write_bytes(requirements(built))
        (output / "release.json").write_bytes(canonical(built))


@pytest.fixture
def updater(tmp_path: Path, synthetic_cairn_home: Path) -> dict:
    source = channel(tmp_path)
    home = Home(synthetic_cairn_home)
    config = UpdaterConfig(repository=str(source.work), path=os.environ["PATH"])
    home.save_config(config)
    return {"home": home, "channel": source, "config": config, "tmp": tmp_path}


def no_skills(home: Home, config: object) -> dict:
    return {"skipped": "synthetic"}


def install_fake_runtime(home: Home, tag: str, sha: str, commit: str = "c" * 40) -> None:
    root = home.runtime(sha)
    (root / "venv" / "bin").mkdir(parents=True)
    (root / "venv" / "bin" / "python").write_text("placeholder")
    info = RuntimeInfo(
        release_tag=tag,
        commit=commit,
        release_sha256=sha,
        worker_image="sha256:" + "2" * 64,
        installed_at=now(),
    )
    (root / "runtime.json").write_bytes(canonical(info))


def test_channel_head_is_adopted_only_for_a_higher_release_number(updater: dict) -> None:
    home, source, config = updater["home"], updater["channel"], updater["config"]
    first = source.release("0.2.0")
    release = service.newest_release(home, config)
    assert release is not None and (release.tag, release.commit) == ("v0.2.0", first)
    install_fake_runtime(home, "v0.2.0", "a" * 64, commit=first)
    home.set_current("a" * 64)
    # Commits without a version bump are development, not a release.
    source.commit({"src/cairn/x.py": b"X = 1\n"})
    assert service.newest_release(home, config) is None
    later = source.release("0.3.0")
    assert service.newest_release(home, config).commit == later  # type: ignore[union-attr]
    # Disagreeing version declarations are refused.
    source.commit({"src/cairn/__init__.py": b'__version__ = "0.3.9"\n'})
    source.commit({"pyproject.toml": b'[project]\nname = "cairn-workbench"\nversion = "0.4.0"\n'})
    with pytest.raises(Conflict, match="versions differ"):
        service.newest_release(home, config)


def test_rewritten_stable_history_is_refused(updater: dict) -> None:
    home, source, config = updater["home"], updater["channel"], updater["config"]
    first = source.release("0.2.0")
    service.newest_release(home, config)  # Mirror now holds the installed commit.
    install_fake_runtime(home, "v0.2.0", "a" * 64, commit=first)
    home.set_current("a" * 64)
    source.git("reset", "-q", "--hard", "HEAD~1")
    source.release("0.3.0")
    with pytest.raises(Denied, match="fast-forward"):
        service.newest_release(home, config)
    result = service.run(home, runner=FakeRunner(home), refresh_skills=no_skills)
    assert result["status"] == "failed" and home.current_runtime().commit == first  # type: ignore[union-attr]


def test_cycle_installs_verifies_rebinds_and_switches(updater: dict) -> None:
    home, source = updater["home"], updater["channel"]
    workspaces = [str(updater["tmp"] / "kb-one"), str(updater["tmp"] / "kb-two")]
    home.save_config(updater["config"].model_copy(update={"workspaces": workspaces}))
    commit = source.release("0.2.0")
    runner = FakeRunner(home)
    result = service.run(home, runner=runner, refresh_skills=no_skills)
    assert result["status"] == "updated" and result["release_tag"] == "v0.2.0"
    current = home.current_runtime()
    assert current is not None and current.commit == commit
    assert set(result["workspaces"]) == set(workspaces)
    order = [" ".join(c[:4]) for c in runner.commands]
    assert order[0].startswith("docker build") and "check-runtime" in " ".join(runner.commands[5])
    # Verification precedes any knowledge-base rebind.
    first_rebind = next(i for i, c in enumerate(runner.commands) if "rebind" in c)
    assert all("rebind" not in " ".join(c) for c in runner.commands[:first_rebind])
    assert any("check-worker" in c for c in runner.commands[:first_rebind])
    state = home.state()
    assert state.notice == "Cairn updated to v0.2.0 (was None)." and not state.notice_shown
    assert service.run(home, runner=runner, if_due=True)["status"] == "not_due"
    assert service.run(home, runner=runner, refresh_skills=no_skills)["status"] == "up_to_date"


@pytest.mark.parametrize("step", ["check-runtime", "check-worker", "init --synthetic", "pip"])
def test_failed_verification_keeps_previous_runtime(updater: dict, step: str) -> None:
    home, source = updater["home"], updater["channel"]
    install_fake_runtime(home, "v0.1.0", "a" * 64)
    home.set_current("a" * 64)
    home.save_config(updater["config"].model_copy(update={"workspaces": ["/synthetic/kb"]}))
    source.release("0.2.0")
    runner = FakeRunner(home, fail=step)
    result = service.run(home, runner=runner, refresh_skills=no_skills)
    assert result["status"] == "failed" and result["skills"] == {"skipped": "synthetic"}
    assert home.current_runtime().release_tag == "v0.1.0"  # type: ignore[union-attr]
    assert not any("rebind" in c for c in runner.commands)
    assert sorted(p.name for p in home.runtimes.iterdir()) == ["a" * 64]
    assert home.state().errors


def test_build_that_does_not_match_signed_source_is_refused(updater: dict) -> None:
    home = updater["home"]
    updater["channel"].release("0.2.0")
    result = service.run(home, runner=FakeRunner(home, revision="b" * 40), refresh_skills=no_skills)
    assert result["status"] == "failed" and "channel source" in result["reason"]
    assert home.current_runtime() is None


def test_failed_rebind_is_reported_and_retried(updater: dict) -> None:
    home = updater["home"]
    home.save_config(updater["config"].model_copy(update={"workspaces": ["/synthetic/kb"]}))
    updater["channel"].release("0.2.0")
    result = service.run(home, runner=FakeRunner(home, fail="rebind"), refresh_skills=no_skills)
    assert result["status"] == "updated"
    assert result["workspaces"]["/synthetic/kb"]["status"] == "failed"
    retry = service.run(home, runner=FakeRunner(home), refresh_skills=no_skills)
    assert retry["status"] == "up_to_date"
    assert retry["workspaces"]["/synthetic/kb"]["status"] == "upgraded"


def test_concurrent_run_reports_busy(updater: dict) -> None:
    home = updater["home"]
    with home.lock():
        assert service.run(home, runner=FakeRunner(home))["status"] == "busy"


def test_old_runtimes_are_collected_unless_still_bound(updater: dict) -> None:
    home = updater["home"]
    for index, tag in enumerate(["v0.1.0", "v0.2.0", "v0.3.0", "v0.4.0"]):
        install_fake_runtime(home, tag, str(index) * 64)
    kb = updater["tmp"] / "bound-kb"
    kb.mkdir()
    (kb / "workspace.json").write_text(json.dumps({"runtime_release_hash": "0" * 64}))
    config = updater["config"].model_copy(update={"workspaces": [str(kb)]})
    assert service.collect(home, config, keep=set()) == ["v0.2.0"]
    assert sorted(p.name for p in home.runtimes.iterdir()) == ["0" * 64, "2" * 64, "3" * 64]


def running_from(home: Home, sha: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "prefix", str(home.runtime(sha) / "venv"))


def test_prelaunch_serves_a_knowledge_base_from_its_bound_runtime(
    updater: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = updater["home"]
    install_fake_runtime(home, "v0.1.0", "a" * 64)
    install_fake_runtime(home, "v0.2.0", "b" * 64)
    running_from(home, "b" * 64, monkeypatch)
    kb = updater["tmp"] / "kb"
    kb.mkdir()
    (kb / "workspace.json").write_text(json.dumps({"runtime_release_hash": "a" * 64}))
    calls: list[tuple] = []
    monkeypatch.setattr(os, "execv", lambda *args: calls.append(args))
    monkeypatch.delenv(launch.REEXEC, raising=False)
    launch._prelaunch(["search", "x", "--workspace", str(kb)])
    assert calls and calls[0][0] == home.python("a" * 64)
    assert calls[0][1][-2:] == ["--workspace", str(kb)]
    assert launch.bound_runtime(home, ["--workspace", str(kb)], {launch.REEXEC: "1"}) is None
    (kb / "workspace.json").write_text(json.dumps({"runtime_release_hash": "b" * 64}))
    assert launch.bound_runtime(home, [f"--workspace={kb}"], {}) is None


def test_prelaunch_notice_and_background_check(
    updater: dict, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    home = updater["home"]
    install_fake_runtime(home, "v0.2.0", "b" * 64)
    running_from(home, "b" * 64, monkeypatch)
    state = home.state()
    state.notice, state.notice_shown = "Cairn updated to v0.2.0 (was v0.1.0).", False
    home.save_state(state)
    spawned: list[list[str]] = []
    monkeypatch.setattr(
        launch.subprocess, "Popen", lambda command, **kwargs: spawned.append(command)
    )
    monkeypatch.delenv("CAIRN_NO_AUTO_UPDATE")
    launch._prelaunch(["inbox"])
    assert "Cairn updated to v0.2.0" in capsys.readouterr().err
    assert spawned and spawned[0][-4:] == ["update", "run", "--if-due", "--quiet"]
    launch._prelaunch(["inbox"])
    assert capsys.readouterr().err == ""
    spawned.clear()
    launch._prelaunch(["update", "status"])
    assert not spawned
    monkeypatch.setenv("CAIRN_NO_AUTO_UPDATE", "1")
    launch._prelaunch(["inbox"])
    assert not spawned
    monkeypatch.setattr(sys, "prefix", "/synthetic/checkout/.venv")
    monkeypatch.delenv("CAIRN_NO_AUTO_UPDATE")
    launch._prelaunch(["inbox"])
    assert not spawned  # Development checkouts never self-update.


def test_launchd_and_cron_schedules(updater: dict, tmp_path: Path) -> None:
    home, config = updater["home"], updater["config"]
    calls: list[list[str]] = []

    def fake(command: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        calls.append(command)
        if command == ["crontab", "-l"]:
            existing = b"0 1 * * * owner-job\n5 * * * * old # cairn-auto-update\n"
            return subprocess.CompletedProcess(command, 0, existing, b"")
        if command == ["crontab", "-"]:
            calls.append([kwargs["input"].decode()])  # type: ignore[union-attr]
        return subprocess.CompletedProcess(command, 0, b"", b"")

    user = tmp_path / "synthetic-user-home"
    result = schedule.install(home, config, user_home=user, platform="darwin", run=fake)
    plist = Path(result["path"])
    assert result["status"] == "scheduled" and plist.is_file()
    import plistlib

    loaded = plistlib.loads(plist.read_bytes())
    assert loaded["ProgramArguments"][-4:] == ["update", "run", "--if-due", "--quiet"]
    assert loaded["EnvironmentVariables"]["CAIRN_HOME"] == str(home.root)
    assert schedule.remove(user_home=user, platform="darwin", run=fake)["status"] == "removed"
    assert not plist.exists()
    calls.clear()
    assert (
        schedule.install(home, config, user_home=user, platform="linux", run=fake)["status"]
        == "scheduled"
    )
    table = calls[-1][0]
    assert "owner-job" in table and table.count("# cairn-auto-update") == 1
    assert "old # cairn" not in table
    shim = schedule.write_shim(home, tmp_path / "bin")
    assert shim.stat().st_mode & 0o111 and "-I -B -m cairn" in shim.read_text()


def test_cli_status_and_setup_requirements(tmp_path: Path) -> None:
    runner = CliRunner()
    status = runner.invoke(app, ["update", "status"])
    assert status.exit_code == 0 and json.loads(status.stdout)["configured"] is False
    assert runner.invoke(app, ["update", "run"]).exit_code != 0
    code = tmp_path / "code"
    code.mkdir()
    refused = runner.invoke(
        app,
        [
            "init",
            "--workspace",
            str(tmp_path / "kb"),
            "--code-root",
            str(code),
            "--synthetic",
            "--auto-update",
        ],
    )
    assert refused.exit_code != 0 and not (tmp_path / "kb").exists()
    unreachable = ["update", "setup", "--repository", str(tmp_path / "absent"), "--no-schedule"]
    assert runner.invoke(app, unreachable).exit_code != 0


def test_cli_enable_registers_and_disable_unregisters(
    updater: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    from test_activation import passing_probe

    from cairn.storage import activation, upgrade

    monkeypatch.setattr(activation, "verify_runtime", lambda _: {"synthetic_test_double": True})
    monkeypatch.setattr(upgrade, "verify_runtime", lambda _: {"synthetic_test_double": True})
    monkeypatch.setattr(activation, "invoke_worker", passing_probe)
    from cairn.records.runtime import REQUIRED_REVIEWS
    from cairn.storage.workspace import Workspace

    release = updater["tmp"] / "release.json"
    release.write_bytes(canonical(manifest()))
    ws = Workspace.init(
        updater["tmp"] / "private-mode-fixture",
        code_roots=[updater["tmp"] / "code"],
        release=release,
        release_sha256=digest(release.read_bytes()),
        statement="Synthetic fixture owner review; not a real activation.",
        acknowledgements=REQUIRED_REVIEWS.copy(),
    )
    runner = CliRunner()
    enabled = runner.invoke(app, ["update", "enable", "--workspace", str(ws.root)])
    assert enabled.exit_code == 0, enabled.output
    assert updater["home"].config().workspaces == [str(ws.root)]  # type: ignore[union-attr]
    assert upgrade.active_authorization(Workspace(ws.root)) is not None
    disabled = runner.invoke(app, ["update", "disable", "--workspace", str(ws.root)])
    assert disabled.exit_code == 0, disabled.output
    assert updater["home"].config().workspaces == []  # type: ignore[union-attr]
    assert upgrade.active_authorization(Workspace(ws.root)) is None


def test_repository_version_declarations_agree() -> None:
    """The updater refuses a release whose two version declarations differ."""
    import re
    import tomllib

    root = Path(__file__).resolve().parents[1]
    declared = tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"]
    package = re.search(r'__version__ = "([^"]+)"', (root / "src/cairn/__init__.py").read_text())
    assert package is not None and package.group(1) == declared
