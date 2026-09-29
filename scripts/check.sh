#!/usr/bin/env bash
set -euo pipefail
repo_dir="$(cd "$(dirname "$0")/.." && pwd)"
docker build --target development -t cairn-dev:local "$repo_dir"
docker build --target base -t cairn-worker:local "$repo_dir"
image_id="$(docker image inspect cairn-dev:local --format '{{.Id}}')"
worker_id="$(docker image inspect cairn-worker:local --format '{{.Id}}')"
profile=(--rm --pull=never --network=none --read-only --cap-drop=ALL
  --security-opt=no-new-privileges --pids-limit=64 --memory=512m --cpus=1
  --user=65532:65532 --tmpfs=/tmp:rw,noexec,nosuid,size=128m,mode=1777)
docker run "${profile[@]}" "$image_id" pytest -p no:cacheprovider
docker run "${profile[@]}" "$image_id" ruff check src tests scripts
docker run "${profile[@]}" "$image_id" mypy
probe_dir="$(mktemp -d /tmp/cairn-synthetic-canary.XXXXXX)"
trap 'rm -f "$probe_dir/canary" "$probe_dir/job.json" "$probe_dir/result.json" "$probe_dir/extraction.json"; rmdir "$probe_dir"' EXIT
printf '%s\n' 'SYNTHETIC-CANARY' > "$probe_dir/canary"
docker run "${profile[@]}" "$image_id" python scripts/isolation_probe.py "$probe_dir/canary"
test "$(cat "$probe_dir/canary")" = 'SYNTHETIC-CANARY'
docker run "${profile[@]}" --interactive --entrypoint python "$worker_id" - "$probe_dir/canary" < "$repo_dir/scripts/isolation_probe.py"
docker run "${profile[@]}" "$image_id" python scripts/worker_roundtrip.py make "$worker_id" > "$probe_dir/job.json"
docker run "${profile[@]}" --interactive "$worker_id" < "$probe_dir/job.json" > "$probe_dir/result.json"
cat "$probe_dir/job.json" "$probe_dir/result.json" | docker run "${profile[@]}" --interactive "$image_id" python scripts/worker_roundtrip.py verify
docker run "${profile[@]}" "$image_id" python scripts/worker_roundtrip.py make-extraction | docker run "${profile[@]}" --interactive "$worker_id" > "$probe_dir/extraction.json"
docker run "${profile[@]}" --interactive "$image_id" python scripts/worker_roundtrip.py verify-extraction < "$probe_dir/extraction.json"
for kind in bibliography receipt finance life; do
  docker run "${profile[@]}" "$image_id" python scripts/worker_roundtrip.py "make-$kind" |
    docker run "${profile[@]}" --interactive "$worker_id" |
    docker run "${profile[@]}" --interactive "$image_id" python scripts/worker_roundtrip.py "verify-$kind"
done
docker run "${profile[@]}" "$image_id" python scripts/prepare_continuity.py --output /tmp/manual-handoff
