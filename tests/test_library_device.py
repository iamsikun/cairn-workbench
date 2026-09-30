from pathlib import Path

import pytest
from test_library_reader import enrolled

from cairn.errors import Denied
from cairn.library.device import ssh_command
from cairn.library.device_runner import RunnerConfig, gpu_profile, serve
from cairn.records.models import canonical, digest


def test_ssh_host_identity_is_pinned(ws, tmp_path: Path) -> None:
    config = enrolled(ws)
    keys = tmp_path / "synthetic-known-hosts"
    keys.write_text("synthetic.example ssh-ed25519 SYNTHETIC-NOT-A-REAL-KEY\n")
    config.known_hosts = str(keys)
    config.known_hosts_hash = digest(keys.read_bytes())
    command = ssh_command(config)
    assert "StrictHostKeyChecking=yes" in command and "ForwardAgent=no" in command
    assert command[-2:] == ["/opt/cairn-device/bin/cairn-device", "serve"]
    config.command = "windows_wsl"
    assert "wsl.exe" in ssh_command(config)
    keys.write_text("changed synthetic host key")
    with pytest.raises(Denied, match="host keys changed"):
        ssh_command(config)


def test_gpu_profile_exposes_only_pinned_model_files() -> None:
    config = RunnerConfig(image="sha256:" + "1" * 64, model_hash="2" * 64, projection_hash="3" * 64)
    command = gpu_profile(config)
    assert "--network=none" in command and "--read-only" in command
    assert "--cap-drop=ALL" in command and "--gpus=device=0" in command
    mounts = [command[i + 1] for i, value in enumerate(command) if value == "--mount"]
    assert len(mounts) == 2 and all("readonly" in value for value in mounts)
    assert all("source=/opt/cairn-models/" in value for value in mounts)
    assert not any("docker.sock" in value or "home" in value for value in command)


def test_cancel_cannot_target_an_arbitrary_container(monkeypatch) -> None:
    config = RunnerConfig(image="sha256:" + "1" * 64, model_hash="2" * 64, projection_hash="3" * 64)
    with pytest.raises(Denied):
        serve(
            config,
            canonical(
                {"operation": "cancel", "job_id": "unrelated_container", "image": config.image}
            ),
        )
    calls = []
    monkeypatch.setattr("cairn.library.device_runner._local_engine", lambda _: None)
    monkeypatch.setattr("cairn.library.device_runner._docker", lambda args, **_: calls.append(args))
    serve(
        config, canonical({"operation": "cancel", "job_id": "read_example", "image": config.image})
    )
    assert calls == [["rm", "--force", "--volumes", "cairn-gpu-read_example"]]
