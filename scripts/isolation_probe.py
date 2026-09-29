"""Execute inside the exact dev/worker profile; nonzero exit means failed isolation.

No private input is used. Pass the path of an unmounted synthetic host canary to
exercise attempted access. This probe deliberately executes an adversarial child.
"""

import json
import os
import socket
import subprocess
import sys
from pathlib import Path


def denied_write(path: str) -> bool:
    try:
        Path(path).write_text("unauthorized")
    except OSError:
        return True
    return False


checks = {
    "non_root": os.getuid() != 0,
    "canonical_write_denied": denied_write("/owner/vault/wiki/compromised.md"),
    "policy_write_denied": denied_write("/owner/policy/workspace.json"),
    "approval_write_denied": denied_write("/owner/approvals/forged.json"),
    "read_only_root": denied_write("/opt/cairn/unauthorized"),
    "no_docker_socket": not Path("/var/run/docker.sock").exists(),
    "no_host_home": not Path("/Users").exists(),
    "no_credentials": not any(
        key in os.environ
        for key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "AWS_SECRET_ACCESS_KEY")
    ),
}
if len(sys.argv) != 2:
    raise SystemExit("an unmounted synthetic canary path is required")
checks["private_canary_unreadable"] = not Path(sys.argv[1]).exists()
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
        "-c",
        """
import socket
from pathlib import Path
try:
    Path('/owner/approvals/forged.json').write_text('{"approved": true}')
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
)
checks["hostile_subprocess_contained"] = child.returncode == 0
print(json.dumps({"passed": all(checks.values()), "checks": checks}, sort_keys=True))
raise SystemExit(0 if all(checks.values()) else 1)
