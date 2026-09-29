import json
import sys
from pathlib import Path

import pytest

from cairn.adapters import isolation
from cairn.errors import Blocked, CairnError, Denied

FAKE_DOCKER = r"""
import json, os, pathlib, sys, time
root = pathlib.Path(os.environ["SYNTHETIC_ENGINE"])
args = sys.argv[1:]
with (root / "calls.jsonl").open("a") as stream:
    stream.write(json.dumps(args) + "\n")
if args[:2] == ["context", "inspect"]:
    print(json.dumps(os.environ.get("SYNTHETIC_ENDPOINT", "unix:///synthetic/docker.sock")))
elif args[:2] == ["image", "inspect"]:
    print(os.environ.get("SYNTHETIC_VOLUMES", "null"))
elif args[0] == "create":
    (root / "created").write_text("a" * 64)
    print("a" * 64)
elif args[0] == "start":
    data = sys.stdin.buffer.read()
    (root / "input").write_bytes(data)
    mode = os.environ.get("SYNTHETIC_MODE", "echo")
    if mode == "timeout":
        time.sleep(300)
    elif mode == "stdout":
        while True:
            os.write(1, b"SECRET-IN-DIAGNOSTICS" * 4096)
    elif mode == "stderr":
        while True:
            os.write(2, b"SECRET-IN-DIAGNOSTICS" * 4096)
    elif mode == "failure":
        print("SECRET-IN-DIAGNOSTICS", file=sys.stderr)
        sys.exit(2)
    else:
        sys.stdout.buffer.write(data)
elif args[0] == "rm":
    if os.environ.get("SYNTHETIC_CLEANUP_FAILURE"):
        sys.exit(1)
    (root / "removed").write_text(args[-1])
elif args[0] == "inspect":
    print("false 7" if os.environ.get("SYNTHETIC_MODE") == "state_failure" else "false 0")
else:
    sys.exit(2)
"""


@pytest.fixture
def engine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    script = tmp_path / "fake_docker.py"
    script.write_text(FAKE_DOCKER)
    monkeypatch.setattr(isolation, "DOCKER_PROGRAM", [sys.executable, str(script)])
    monkeypatch.setenv("SYNTHETIC_ENGINE", str(tmp_path))
    monkeypatch.delenv("DOCKER_HOST", raising=False)
    monkeypatch.setattr(isolation, "WORKER_TIMEOUT", 0.3)
    monkeypatch.setattr(isolation, "OUTPUT_LIMIT", 4096)
    return tmp_path


@pytest.mark.parametrize(
    "mode", ["echo", "timeout", "stdout", "stderr", "failure", "state_failure"]
)
def test_owned_worker_cleanup_and_bounded_streams(
    engine: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    monkeypatch.setenv("SYNTHETIC_MODE", mode)
    data = b"Synthetic selected private packet"
    if mode == "echo":
        assert isolation.invoke_worker("sha256:" + "0" * 64, data) == data
    else:
        with pytest.raises(CairnError) as failure:
            isolation.invoke_worker("sha256:" + "0" * 64, data)
        assert "SECRET-IN-DIAGNOSTICS" not in str(failure.value)
    assert (engine / "removed").read_text() == "a" * 64
    calls = [json.loads(line) for line in (engine / "calls.jsonl").read_text().splitlines()]
    creation = next(call for call in calls if call[0] == "create")
    assert "--log-driver=none" in creation and "--network=none" in creation
    assert "--read-only" in creation and "--no-healthcheck" in creation
    assert calls[-1] == ["rm", "--force", "--volumes", "a" * 64]
    assert (engine / "input").read_bytes() == data


def test_cleanup_failure_is_not_reported_as_success(
    engine: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SYNTHETIC_CLEANUP_FAILURE", "1")
    with pytest.raises(Blocked, match="worker_cleanup_unverified"):
        isolation.invoke_worker("sha256:" + "0" * 64, b"synthetic")


@pytest.mark.parametrize(
    "setting,value",
    [
        ("DOCKER_HOST", "tcp://remote.invalid:2375"),
        ("SYNTHETIC_ENDPOINT", "ssh://remote.invalid"),
        ("SYNTHETIC_VOLUMES", '{"/private":{}}'),
    ],
)
def test_unverified_route_or_implicit_volume_rejected_before_packet(
    engine: Path,
    monkeypatch: pytest.MonkeyPatch,
    setting: str,
    value: str,
) -> None:
    monkeypatch.setenv(setting, value)
    with pytest.raises(Denied):
        isolation.invoke_worker("sha256:" + "0" * 64, b"must not leave launcher")
    assert not (engine / "input").exists() and not (engine / "created").exists()


def test_closed_output_pipes_do_not_bypass_worker_deadline() -> None:
    command = [sys.executable, "-c", "import os,time; os.close(1); os.close(2); time.sleep(300)"]
    with pytest.raises(Blocked, match="worker_timeout"):
        isolation.bounded_process(command, b"", timeout=0.2, stdout_limit=100)
