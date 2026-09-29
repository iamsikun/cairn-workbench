from __future__ import annotations

import re
import subprocess

from cairn.adapters.protocol import Job, Result
from cairn.errors import Blocked, CairnError, Denied
from cairn.records.models import canonical


def container_command(image: str, *, entrypoint: str | None = None) -> list[str]:
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", image):
        raise Blocked("isolation requires a pinned local image ID")
    args = [
        "docker",
        "run",
        "--rm",
        "--pull=never",
        "--network=none",
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


class ClientPacketProvider:
    """JSON packet interface to a reviewed local client image.

    The trusted owner launches the client with no mounts, shell tools, credentials,
    or external network. The response is still untrusted until proposal validation.
    """

    def __init__(self, image: str):
        self.image = image

    def generate(self, job: Job) -> Result:
        if job.execution_image != self.image:
            raise Denied("job does not bind this execution image")
        raw = canonical(job)
        try:
            return Result.model_validate_json(invoke_worker(self.image, raw))
        except ValueError as exc:
            raise CairnError("invalid worker result") from exc


def invoke_worker(image: str, raw: bytes) -> bytes:
    if len(raw) > 48 * 1024 * 1024:
        raise CairnError("job exceeds input budget")
    try:
        result = subprocess.run(
            container_command(image), input=raw, capture_output=True, timeout=90, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Blocked("isolation_unavailable") from exc
    if result.returncode:
        raise Blocked("worker_failed_or_isolation_unavailable")
    if len(result.stdout) > 32 * 1024 * 1024:
        raise CairnError("worker result exceeds output budget")
    return result.stdout
