"""Retired updater entrypoints must not touch state, schedules, or networking."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cairn.cli import app
from cairn.errors import Blocked
from cairn.updater import launch, schedule, service
from cairn.updater.home import Home, UpdaterConfig


@pytest.mark.parametrize("args", [
    ["update", "setup"], ["update", "run"], ["update", "schedule"],
    ["update", "enable", "--workspace", "/synthetic/absent"],
])
def test_retired_cli_does_not_read_or_change_state(args, synthetic_cairn_home, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("retired operation touched external state")

    monkeypatch.setattr(Home, "from_env", forbidden)
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 5, result.output
    assert "retired" in result.output and "direct-save" in result.output
    assert list(synthetic_cairn_home.iterdir()) == []


def test_updater_library_and_schedule_retire_before_side_effects(tmp_path, monkeypatch):
    home = Home(tmp_path / "absent")
    config = UpdaterConfig(repository="https://example.invalid/synthetic")

    def forbidden(*args, **kwargs):
        raise AssertionError("retired operation launched a command")

    with pytest.raises(Blocked, match="retired"):
        service.run(home, runner=forbidden)
    with pytest.raises(Blocked, match="retired"):
        service.install(home, None, config, forbidden)
    with pytest.raises(Blocked, match="retired"):
        schedule.install(home, config, user_home=tmp_path, run=forbidden)
    with pytest.raises(Blocked, match="retired"):
        schedule.write_shim(home, tmp_path / "bin")
    monkeypatch.setattr(Home, "from_env", forbidden)
    launch.prelaunch(["search", "anything"])
    launch._prelaunch(["update", "run"])
    assert not home.root.exists() and not (tmp_path / "bin").exists()


def test_update_status_remains_readable():
    result = CliRunner().invoke(app, ["update", "status"])
    assert result.exit_code == 0
    assert json.loads(result.stdout)["configured"] is False


def test_repository_version_declarations_agree() -> None:
    """The updater refuses a release whose two version declarations differ."""
    import re
    import tomllib

    root = Path(__file__).resolve().parents[1]
    declared = tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"]
    package = re.search(r'__version__ = "([^"]+)"', (root / "src/cairn/__init__.py").read_text())
    assert package is not None and package.group(1) == declared
