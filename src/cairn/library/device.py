"""Owner-device transport; remote inference is never labeled same-machine local."""

import os
from collections.abc import Callable
from pathlib import Path
from uuid import uuid4

from cairn.adapters.isolation import bounded_process
from cairn.errors import Blocked, Conflict, Denied
from cairn.library.reader_models import DeviceConfig, DeviceProbe
from cairn.library.store import commit_unlocked
from cairn.records.models import canonical, digest
from cairn.storage.files import RootFS
from cairn.storage.workspace import Workspace


def device_path(device_id: str) -> str:
    from pydantic import TypeAdapter

    from cairn.records.models import ID

    TypeAdapter(ID).validate_python(device_id)
    return f"receipts/library/devices/{device_id}.json"


def load_device(ws: Workspace, device_id: str) -> DeviceConfig:
    value = DeviceConfig.model_validate_json(ws.fs.read(device_path(device_id)))
    if value.id != device_id:
        raise Conflict("device identity mismatch")
    return value


def ssh_command(config: DeviceConfig) -> list[str]:
    path = Path(config.known_hosts)
    if not path.is_absolute() or any(p.is_symlink() for p in (path, *path.parents)):
        raise Denied("device host keys require a dedicated absolute file")
    raw = RootFS(path.parent).read(path.name, limit=65536)
    if digest(raw) != config.known_hosts_hash:
        raise Denied("enrolled host keys changed")
    command = [
        "ssh",
        "-T",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=10",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        "UpdateHostKeys=no",
        "-o",
        "ForwardAgent=no",
        "-o",
        "ClearAllForwardings=yes",
        "-o",
        "ControlMaster=no",
        "-o",
        "GlobalKnownHostsFile=/dev/null",
        "-o",
        f"UserKnownHostsFile={path}",
        config.ssh_alias,
    ]
    # The only remote command is installed owner code. Imported text is stdin data.
    if config.command == "windows_wsl":
        command += [
            "wsl.exe",
            "--distribution",
            "Cairn",
            "--exec",
            "/opt/cairn-device/bin/cairn-device",
            "serve",
        ]
    else:
        command += ["/opt/cairn-device/bin/cairn-device", "serve"]
    return command


def exchange(config: DeviceConfig, packet: bytes, *, timeout: float = 1800) -> bytes:
    if len(packet) > 48 * 1024 * 1024:
        raise Denied("device packet exceeds budget")
    code, output = bounded_process(
        ssh_command(config),
        packet,
        timeout=timeout,
        stdout_limit=32 * 1024 * 1024,
        env=dict(os.environ),
    )
    if code:
        raise Blocked("owner_device_unavailable")
    return output


def enroll(
    ws: Workspace,
    config: DeviceConfig,
    transport: Callable[[DeviceConfig, bytes], bytes] | None = None,
) -> DeviceConfig:
    if transport is not None and not ws.config.synthetic:
        raise Denied("injected device transport is synthetic-only")
    nonce = uuid4().hex
    packet = canonical(
        {
            "operation": "probe",
            "nonce": nonce,
            "image": config.image,
            "model_hash": config.model_hash,
            "projection_hash": config.projection_hash,
        }
    )
    response = (transport or exchange)(config, packet)
    probe = DeviceProbe.model_validate_json(response)
    if (
        probe.nonce != nonce
        or probe.result.nonce != nonce
        or probe.image != config.image
        or probe.model_hash != config.model_hash
        or probe.projection_hash != config.projection_hash
        or not all(probe.result.checks.values())
        or not probe.gpu
    ):
        raise Denied("owner-device isolation probe did not pass")
    config.probe = probe
    with ws.lock(write=True):
        ws.policy.scope(config.scope)
        commit_unlocked(ws, {device_path(config.id): canonical(config)}, "device_enroll")
    return config


def require_device(ws: Workspace, device_id: str, scope: str) -> DeviceConfig:
    device = load_device(ws, device_id)
    if device.scope != scope or device.probe is None:
        raise Denied("device is not enrolled for this scope")
    quality = device.quality_review
    if not ws.config.synthetic and (
        quality is None
        or quality.model_hash != device.model_hash
        or quality.projection_hash != device.projection_hash
        or quality.image != device.image
    ):
        raise Blocked("owner_device_quality_and_memory_pilot_pending")
    probe = device.probe
    if (
        probe.image != device.image
        or probe.model_hash != device.model_hash
        or probe.projection_hash != device.projection_hash
        or not all(probe.result.checks.values())
    ):
        raise Denied("device profile changed; probe and enroll again")
    return device


def revoke(ws: Workspace, device_id: str) -> None:
    with ws.lock(write=True):
        device = load_device(ws, device_id)
        device.probe = None
        commit_unlocked(ws, {device_path(device_id): canonical(device)}, "device_revoke")
