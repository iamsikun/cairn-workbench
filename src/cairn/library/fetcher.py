"""Public metadata transport. It has network, but no model, private mounts, or secrets."""

import base64
import json
import os
import sys
from uuid import uuid4

from cairn.adapters.isolation import _docker, _local_engine, bounded_process, container_command
from cairn.errors import Blocked, Denied
from cairn.records.models import canonical
from cairn.storage.workspace import Workspace


def fetch_isolated(ws: Workspace, url: str, hosts: set[str]) -> bytes:
    image = ws.config.worker_image
    if not image:
        raise Blocked("public_fetcher_image_unavailable")
    env = dict(os.environ)
    _local_engine(env)
    volumes = json.loads(
        _docker(["image", "inspect", "--format", "{{json .Config.Volumes}}", image], env=env)
    )
    if volumes not in (None, {}):
        raise Denied("public fetcher image declares volumes")
    profile = container_command(image, entrypoint="python")
    args = [
        arg.replace("--network=none", "--network=bridge") for arg in profile[2:-1] if arg != "--rm"
    ]
    container_id = (
        _docker(
            [
                "create",
                *args,
                "--name",
                "cairn-public-" + uuid4().hex,
                image,
                "-m",
                "cairn.library.fetcher",
            ],
            env=env,
        )
        .decode()
        .strip()
    )
    import re

    if not re.fullmatch(r"[a-f0-9]{64}", container_id):
        raise Blocked("public_fetcher_identity_unverified")
    try:
        code, output = bounded_process(
            ["docker", "start", "--attach", "--interactive", container_id],
            canonical({"url": url, "hosts": sorted(hosts)}),
            timeout=60,
            stdout_limit=12 * 1024 * 1024,
            env=env,
        )
        if code:
            raise Blocked("publication_source_unavailable")
        data = json.loads(output)
        return base64.b64decode(data["data"], validate=True)
    finally:
        _docker(["rm", "--force", "--volumes", container_id], env=env)


def main() -> None:
    from cairn.library.discovery import fetch_public

    try:
        raw = sys.stdin.buffer.read(65537)
        if len(raw) > 65536:
            raise ValueError("request too large")
        request = json.loads(raw)
        if set(request) != {"url", "hosts"}:
            raise ValueError("unsupported request")
        result = fetch_public(request["url"], set(request["hosts"]))
        sys.stdout.buffer.write(canonical({"data": base64.b64encode(result).decode()}))
    except Exception:
        sys.stderr.write("public metadata fetch failed\n")
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
