from __future__ import annotations

import json
import os
import re
import selectors
import subprocess
import time
from pathlib import Path
from uuid import uuid4

from cairn.errors import Blocked, CairnError, Denied

DOCKER_PROGRAM = ["docker"]
WORKER_TIMEOUT = 90.0
OUTPUT_LIMIT = 32 * 1024 * 1024
ERROR_LIMIT = 64 * 1024


def container_command(image: str, *, entrypoint: str | None = None) -> list[str]:
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", image):
        raise Blocked("isolation requires a pinned local image ID")
    args = [
        "docker",
        "run",
        "--rm",
        "--pull=never",
        "--network=none",
        "--log-driver=none",
        "--no-healthcheck",
        "--restart=no",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--pids-limit=64",
        "--memory=512m",
        "--cpus=1",
        "--user=65532:65532",
        "--tmpfs=/tmp:rw,noexec,nosuid,size=64m,mode=1777",
        "--interactive",
    ]
    if entrypoint:
        args += ["--entrypoint", entrypoint]
    return [*args, image]


def bounded_process(
    command: list[str],
    raw: bytes,
    *,
    timeout: float,
    stdout_limit: int,
    stderr_limit: int = ERROR_LIMIT,
    env: dict[str, str] | None = None,
    cwd: Path | None = None,
) -> tuple[int, bytes]:
    """Drain both pipes without unbounded buffering; never return worker diagnostics."""
    deadline = time.monotonic() + timeout
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            cwd=cwd,
            bufsize=0,
        )
    except OSError as exc:
        raise Blocked("isolation_unavailable") from exc
    output = bytearray()
    errors = 0
    offset = 0
    assert process.stdin and process.stdout and process.stderr
    try:
        with selectors.DefaultSelector() as selector:
            for stream in (process.stdout, process.stderr):
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, selectors.EVENT_READ)
            if raw:
                os.set_blocking(process.stdin.fileno(), False)
                selector.register(process.stdin, selectors.EVENT_WRITE)
            else:
                process.stdin.close()
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise Blocked("worker_timeout")
                for key, _ in selector.select(min(remaining, 0.25)):
                    if key.fileobj is process.stdin:
                        try:
                            offset += os.write(key.fd, memoryview(raw)[offset : offset + 65536])
                        except BrokenPipeError:
                            offset = len(raw)
                        if offset == len(raw):
                            selector.unregister(process.stdin)
                            process.stdin.close()
                    else:
                        data = os.read(key.fd, 65536)
                        if not data:
                            selector.unregister(key.fileobj)
                        elif key.fileobj is process.stdout:
                            if len(output) + len(data) > stdout_limit:
                                raise CairnError("worker stdout exceeds output budget")
                            output.extend(data)
                        else:
                            errors += len(data)
                            if errors > stderr_limit:
                                raise CairnError("worker stderr exceeds diagnostic budget")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise Blocked("worker_timeout")
            return process.wait(timeout=remaining), bytes(output)
    except subprocess.TimeoutExpired as exc:
        raise Blocked("worker_timeout") from exc
    finally:
        if process.poll() is None:
            process.kill()
        process.wait()
        for stream in (process.stdin, process.stdout, process.stderr):
            stream.close()


def _docker(arguments: list[str], *, env: dict[str, str]) -> bytes:
    status, output = bounded_process(
        [*DOCKER_PROGRAM, *arguments], b"", timeout=30, stdout_limit=65536, env=env
    )
    if status:
        raise Blocked("docker_control_unavailable")
    return output


def _local_engine(env: dict[str, str]) -> None:
    # No private packet goes to an SSH/TCP/remote Docker context. Check the endpoint
    # before create/start; context inspection reads configuration without a data packet.
    explicit = env.get("DOCKER_HOST")
    if explicit and not explicit.startswith("unix:///"):
        raise Denied("local-only workers require a local Unix-socket Docker engine")
    try:
        endpoint = json.loads(
            _docker(["context", "inspect", "--format", "{{json .Endpoints.docker.Host}}"], env=env)
        )
    except (ValueError, TypeError) as exc:
        raise Blocked("docker_endpoint_unverified") from exc
    if not isinstance(endpoint, str) or not endpoint.startswith("unix:///"):
        raise Denied("local-only workers require a local Unix-socket Docker context")


def invoke_worker(image: str, raw: bytes) -> bytes:
    if len(raw) > 48 * 1024 * 1024:
        raise CairnError("job exceeds input budget")
    profile = container_command(image)
    env = dict(os.environ)
    _local_engine(env)
    try:
        volumes = json.loads(
            _docker(["image", "inspect", "--format", "{{json .Config.Volumes}}", image], env=env)
        )
    except (ValueError, TypeError) as exc:
        raise Blocked("worker_image_profile_unverified") from exc
    if volumes not in (None, {}):
        raise Denied("worker images must not declare persistent volumes")
    name = "cairn-worker-" + uuid4().hex
    # Create before supplying input: a start timeout can always name the owned container.
    create = [
        "create",
        *(arg for arg in profile[2:-1] if arg != "--rm"),
        "--name",
        name,
        "--label",
        "cairn.worker=true",
        image,
    ]
    container_id: str | None = None
    try:
        created = _docker(create, env=env).decode().strip()
        if not re.fullmatch(r"[0-9a-f]{64}", created):
            raise Blocked("worker_container_identity_unverified")
        container_id = created
        status, output = bounded_process(
            [*DOCKER_PROGRAM, "start", "--attach", "--interactive", container_id],
            raw,
            timeout=WORKER_TIMEOUT,
            stdout_limit=OUTPUT_LIMIT,
            env=env,
        )
        if status:
            raise Blocked("worker_failed")
        state = _docker(
            ["inspect", "--format", "{{.State.Running}} {{.State.ExitCode}}", container_id], env=env
        )
        if state.strip() != b"false 0":
            raise Blocked("worker_did_not_complete_successfully")
        return output
    finally:
        if container_id is not None:
            try:
                _docker(["rm", "--force", "--volumes", container_id], env=env)
            except CairnError as exc:
                raise Blocked(f"worker_cleanup_unverified: {container_id}") from exc
        else:
            # A failed create never received source bytes and never started. Remove
            # any partially-created, randomly named object without touching other jobs.
            try:
                _docker(["rm", "--force", "--volumes", name], env=env)
            except CairnError:
                pass
