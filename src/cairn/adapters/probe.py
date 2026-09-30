"""Fixed synthetic isolation checks; never run this probe in the owner process."""

import os
import socket
import subprocess
import sys
from pathlib import Path

from cairn.records.runtime import ProbeRequest, ProbeResult


def _denied_write(path: str) -> bool:
    try:
        Path(path).write_text("synthetic unauthorized write")
    except OSError:
        return True
    return False


def probe(request: ProbeRequest) -> ProbeResult:
    checks = {
        "non_root": os.getuid() != 0,
        "canonical_write_denied": _denied_write("/owner/vault/wiki/compromised.md"),
        "policy_write_denied": _denied_write("/owner/policy/workspace.json"),
        "approval_write_denied": _denied_write("/owner/approvals/forged.json"),
        "read_only_root": _denied_write("/opt/cairn/unauthorized"),
        "no_docker_socket": not Path("/var/run/docker.sock").exists(),
        "no_host_home": not Path("/Users").exists(),
        "no_credentials": not any(
            key in os.environ
            for key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "AWS_SECRET_ACCESS_KEY")
        ),
    }
    try:
        with Path(request.canary_path).open("rb") as stream:
            stream.read(1)
        checks["private_canary_unreadable"] = False
    except OSError:
        checks["private_canary_unreadable"] = True
    for address in ("198.51.100.1", "1.1.1.1"):
        try:
            with socket.create_connection((address, 443), timeout=0.3):
                checks[f"no_egress_{address}"] = False
        except OSError:
            checks[f"no_egress_{address}"] = True
    try:
        socket.getaddrinfo("example.invalid", 443)
        checks["no_dns"] = False
    except OSError:
        checks["no_dns"] = True
    child = subprocess.run(
        [
            sys.executable,
            "-I",
            "-B",
            "-c",
            """
import socket
from pathlib import Path
try:
    Path('/owner/approvals/forged.json').write_text('{"approved":true}')
    raise SystemExit(9)
except OSError:
    pass
try:
    socket.create_connection(('198.51.100.1', 443), timeout=0.3)
    raise SystemExit(10)
except OSError:
    pass
""",
        ],
        check=False,
        capture_output=True,
        timeout=5,
    )
    checks["hostile_subprocess_contained"] = child.returncode == 0
    return ProbeResult(nonce=request.nonce, checks=checks)
