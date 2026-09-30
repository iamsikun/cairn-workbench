"""Fixed trusted WSL owner-device launcher. Never execute in an inference container."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import signal
import sys
import tempfile
from pathlib import Path
from typing import Literal
from uuid import uuid4

from cairn.adapters.isolation import _docker, _local_engine, bounded_process, container_command
from cairn.errors import Blocked, Denied
from cairn.library.reader_models import DeviceProbe, ReaderJob
from cairn.records.models import Digest, Model, canonical, now
from cairn.records.runtime import ImageID, ProbeResult


class RunnerConfig(Model):
    schema_version: Literal[1] = 1
    image: ImageID
    model_hash: Digest
    projection_hash: Digest
    model_path: str = "/opt/cairn-models/model.gguf"
    projection_path: str = "/opt/cairn-models/mmproj.gguf"


def checked_artifact(path: str, expected: str) -> None:
    file = Path(path)
    if not file.is_relative_to("/opt/cairn-models") or any(
        p.is_symlink() for p in (file, *file.parents)
    ):
        raise Denied("model artifacts require the dedicated model directory")
    checksum = hashlib.sha256()
    with file.open("rb") as stream:
        if not file.is_file():
            raise Denied("model artifact is not a file")
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(block)
    if checksum.hexdigest() != expected:
        raise Denied("model artifact hash mismatch")


def gpu_profile(config: RunnerConfig, entrypoint: str = "python") -> list[str]:
    profile = container_command(config.image, entrypoint=entrypoint)
    substitutions = {
        "--memory=512m": "--memory=40g",
        "--cpus=1": "--cpus=8",
        "--pids-limit=64": "--pids-limit=512",
        "--tmpfs=/tmp:rw,noexec,nosuid,size=64m,mode=1777": (
            "--tmpfs=/tmp:rw,noexec,nosuid,size=512m,mode=1777"
        ),
    }
    profile = [substitutions.get(item, item) for item in profile]
    return [
        *profile[:-1],
        "--gpus=device=0",
        "--mount",
        f"type=bind,source={config.model_path},target=/models/model.gguf,readonly",
        "--mount",
        f"type=bind,source={config.projection_path},target=/models/mmproj.gguf,readonly",
        profile[-1],
    ]


def invoke(config: RunnerConfig, packet: bytes, module: str, job_id: str | None = None) -> bytes:
    env = dict(os.environ)
    _local_engine(env)
    volumes = json.loads(
        _docker(["image", "inspect", "--format", "{{json .Config.Volumes}}", config.image], env=env)
    )
    if volumes not in (None, {}):
        raise Denied("GPU image declares persistent volumes")
    name = "cairn-gpu-" + (job_id or uuid4().hex)
    profile = gpu_profile(config)
    try:
        _docker(
            [
                "create",
                *(a for a in profile[2:-1] if a != "--rm"),
                "--name",
                name,
                config.image,
                "-m",
                module,
            ],
            env=env,
        )
        code, result = bounded_process(
            ["docker", "start", "--attach", "--interactive", name],
            packet,
            timeout=1800,
            stdout_limit=32 * 1024 * 1024,
            env=env,
        )
        state = json.loads(_docker(["inspect", "--format", "{{json .State}}", name], env=env))
        if code or state.get("Running") or state.get("ExitCode") != 0 or state.get("OOMKilled"):
            raise Blocked("gpu_job_failed")
        return result
    finally:
        _docker(["rm", "--force", "--volumes", name], env=env)


def serve(config: RunnerConfig, raw: bytes) -> bytes:
    packet = json.loads(raw)
    if packet.get("operation") == "cancel":
        from pydantic import TypeAdapter

        from cairn.records.models import ID

        if set(packet) != {"operation", "job_id", "image"} or packet["image"] != config.image:
            raise Denied("invalid cancellation request")
        job_id = TypeAdapter(ID).validate_python(packet["job_id"])
        if not job_id.startswith("read_"):
            raise Denied("invalid reader identity")
        env = dict(os.environ)
        _local_engine(env)
        _docker(["rm", "--force", "--volumes", "cairn-gpu-" + job_id], env=env)
        return canonical({"job_id": job_id, "cancelled": True})
    checked_artifact(config.model_path, config.model_hash)
    checked_artifact(config.projection_path, config.projection_hash)
    if packet.get("operation") == "probe":
        if set(packet) != {"operation", "nonce", "image", "model_hash", "projection_hash"}:
            raise Denied("invalid probe request")
        if any(
            packet[key] != getattr(config, key)
            for key in ("image", "model_hash", "projection_hash")
        ):
            raise Denied("device configuration mismatch")
        with tempfile.TemporaryDirectory(prefix="cairn-probe-") as folder:
            canary = Path(folder) / "synthetic-canary"
            token = uuid4().hex
            canary.write_text(token)
            response = invoke(
                config,
                canonical(
                    {"operation": "probe", "nonce": packet["nonce"], "canary_path": str(canary)}
                ),
                "cairn.adapters.worker",
            )
            result = ProbeResult.model_validate_json(response)
            if canary.read_text() != token or not all(result.checks.values()):
                raise Denied("device isolation probe failed")
        code, gpu = bounded_process(
            ["nvidia-smi", "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader"],
            b"",
            timeout=10,
            stdout_limit=4096,
        )
        if code or not gpu.strip():
            raise Blocked("gpu_unavailable")
        return canonical(
            DeviceProbe(
                nonce=packet["nonce"],
                image=config.image,
                model_hash=config.model_hash,
                projection_hash=config.projection_hash,
                result=result,
                host_canary_preserved=True,
                gpu=gpu.decode().strip(),
                at=now(),
            )
        )
    if packet.get("operation") != "read" or set(packet) != {"operation", "job", "data"}:
        raise Denied("invalid device request")
    job = ReaderJob.model_validate(packet["job"])
    if job.model_hash != config.model_hash or job.projection_hash != config.projection_hash:
        raise Denied("job model artifacts changed")
    return invoke(config, raw, "cairn.library.reader_worker", job.id)


def main() -> None:
    if sys.argv[1:] != ["serve"]:
        raise SystemExit("Only the fixed serve operation is supported")
    config = RunnerConfig.model_validate_json(Path("/etc/cairn-device.json").read_bytes())
    raw = sys.stdin.buffer.read(48 * 1024 * 1024 + 1)
    if len(raw) > 48 * 1024 * 1024:
        raise Denied("device input budget exceeded")
    if json.loads(raw).get("operation") == "cancel":
        sys.stdout.buffer.write(serve(config, raw))
        return

    def interrupted(signum: int, frame: object) -> None:
        raise Blocked("owner_device_connection_interrupted")

    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGHUP, interrupted)
    # Owner-created directory, not /tmp: untrusted jobs cannot replace the lock inode.
    with Path("/var/lib/cairn-device/gpu.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise Blocked("gpu_busy") from exc
        sys.stdout.buffer.write(serve(config, raw))


if __name__ == "__main__":
    main()
