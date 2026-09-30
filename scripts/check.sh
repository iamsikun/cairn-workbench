#!/usr/bin/env bash
set -euo pipefail
repo_dir="$(cd "$(dirname "$0")/.." && pwd)"
docker build --target development -t cairn-dev:local "$repo_dir"
docker build --target base -t cairn-worker:local "$repo_dir"
image_id="$(docker image inspect cairn-dev:local --format '{{.Id}}')"
worker_id="$(docker image inspect cairn-worker:local --format '{{.Id}}')"
profile=(--rm --pull=never --network=none --read-only --cap-drop=ALL
  --log-driver=none --no-healthcheck --restart=no
  --security-opt=no-new-privileges --pids-limit=64 --memory=512m --cpus=1
  --user=65532:65532 --tmpfs=/tmp:rw,noexec,nosuid,size=128m,mode=1777)
docker run "${profile[@]}" "$image_id" pytest -p no:cacheprovider
docker run "${profile[@]}" "$image_id" ruff check src tests scripts
docker run "${profile[@]}" "$image_id" mypy
probe_dir="$(mktemp -d /tmp/cairn-synthetic-canary.XXXXXX)"
lifecycle_id=""
cleanup() {
  if [[ -n "$lifecycle_id" ]]; then
    docker rm --force --volumes "$lifecycle_id" >/dev/null
  fi
  rm -f "$probe_dir/canary" "$probe_dir/job.json" "$probe_dir/result.json" "$probe_dir/extraction.json" "$probe_dir/probe.json" "$probe_dir/probe-result.json"
  rmdir "$probe_dir"
}
trap cleanup EXIT
printf '%s\n' 'SYNTHETIC-CANARY' > "$probe_dir/canary"
docker run "${profile[@]}" "$image_id" python scripts/isolation_probe.py "$probe_dir/canary"
test "$(cat "$probe_dir/canary")" = 'SYNTHETIC-CANARY'
docker run "${profile[@]}" --interactive --entrypoint python "$worker_id" - "$probe_dir/canary" < "$repo_dir/scripts/isolation_probe.py"
docker run "${profile[@]}" "$image_id" python scripts/probe_roundtrip.py make "$probe_dir/canary" > "$probe_dir/probe.json"
docker run "${profile[@]}" --interactive "$worker_id" < "$probe_dir/probe.json" > "$probe_dir/probe-result.json"
cat "$probe_dir/probe.json" "$probe_dir/probe-result.json" | docker run "${profile[@]}" --interactive "$image_id" python scripts/probe_roundtrip.py verify
test "$(cat "$probe_dir/canary")" = 'SYNTHETIC-CANARY'
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
docker run "${profile[@]}" "$image_id" python scripts/evaluate_goldset.py --output /tmp/goldset.json

# Real-engine lifecycle check. All contributor Python executes inside the no-mount
# worker; no Docker socket or owner filesystem is exposed to any container.
lifecycle_id="$(docker create "${profile[@]:1}" --interactive "$worker_id")"
docker start --attach --interactive "$lifecycle_id" < "$probe_dir/job.json" > "$probe_dir/result.json"
test "$(docker inspect --format '{{.State.Running}}' "$lifecycle_id")" = false
docker rm --force --volumes "$lifecycle_id" >/dev/null
lifecycle_id=""
cat "$probe_dir/job.json" "$probe_dir/result.json" | docker run "${profile[@]}" --interactive "$image_id" python scripts/worker_roundtrip.py verify
lifecycle_id="$(docker create "${profile[@]:1}" --interactive --entrypoint python "$worker_id" -c 'import subprocess,time; subprocess.Popen(["sleep","300"]); time.sleep(300)')"
docker start "$lifecycle_id" >/dev/null
test "$(docker inspect --format '{{.State.Running}}' "$lifecycle_id")" = true
docker rm --force --volumes "$lifecycle_id" >/dev/null
if docker inspect "$lifecycle_id" >/dev/null 2>&1; then
  exit 1
fi
lifecycle_id=""
printf '%s\n' '{"real_engine_create_start_remove":"passed","running_worker_and_child_removed":true}'
