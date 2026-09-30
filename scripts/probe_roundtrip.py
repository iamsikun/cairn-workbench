"""Make/verify a fresh real-engine probe without exposing the daemon to Python."""

import json
import sys
from uuid import uuid4

from cairn.records.models import canonical
from cairn.records.runtime import ProbeRequest, ProbeResult

if sys.argv[1] == "make":
    sys.stdout.buffer.write(canonical(ProbeRequest(nonce=uuid4().hex, canary_path=sys.argv[2])))
elif sys.argv[1] == "verify":
    lines = sys.stdin.buffer.read().splitlines()
    if len(lines) != 2:
        raise ValueError("probe requires exactly one request and one response")
    request = ProbeRequest.model_validate_json(lines[0])
    result = ProbeResult.model_validate_json(lines[1])
    assert result.nonce == request.nonce and all(result.checks.values())
    print(
        json.dumps(
            {
                "installed_worker_probe": "passed",
                "checks": len(result.checks),
                "image": sys.argv[2] if len(sys.argv) == 3 else None,
            }
        )
    )
else:
    raise ValueError("unsupported probe trial operation")
