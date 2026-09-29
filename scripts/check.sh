#!/usr/bin/env bash
set -euo pipefail
repo_dir="$(cd "$(dirname "$0")/.." && pwd)"
docker build --target development -t cairn-dev:local "$repo_dir"
image_id="$(docker image inspect cairn-dev:local --format '{{.Id}}')"
profile=(--rm --pull=never --network=none --read-only --cap-drop=ALL
  --security-opt=no-new-privileges --pids-limit=64 --memory=512m --cpus=1
  --user=65532:65532 --tmpfs=/tmp:rw,noexec,nosuid,size=128m,mode=1777)
docker run "${profile[@]}" "$image_id" pytest -p no:cacheprovider
docker run "${profile[@]}" "$image_id" ruff check src tests scripts
docker run "${profile[@]}" "$image_id" mypy
probe_dir="$(mktemp -d /tmp/cairn-synthetic-canary.XXXXXX)"
trap 'rm -f "$probe_dir/canary"; rmdir "$probe_dir"' EXIT
printf '%s\n' 'SYNTHETIC-CANARY' > "$probe_dir/canary"
docker run "${profile[@]}" "$image_id" python scripts/isolation_probe.py "$probe_dir/canary"
test "$(cat "$probe_dir/canary")" = 'SYNTHETIC-CANARY'
