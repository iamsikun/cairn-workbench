"""Frozen worker profile for validating historical receipts; never executed."""

import re
from typing import NoReturn

from cairn.errors import Blocked


def retired(operation: str) -> NoReturn:
    raise Blocked(
        f"{operation} is retired. Install the native Cairn package and use the direct-save "
        "workflow; migrate legacy workspaces explicitly. Use retire-installation for "
        "managed installations."
    )


def historical_worker_profile(image: str, *, entrypoint: str | None = None) -> list[str]:
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", image):
        raise Blocked("legacy profile requires a pinned image ID")
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
