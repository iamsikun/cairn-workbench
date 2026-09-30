#!/usr/bin/env bash
set -euo pipefail
repo_dir="$(cd "$(dirname "$0")/.." && pwd)"
cd "$repo_dir"
if [[ -n "$(git status --porcelain --untracked-files=all)" ]]; then
  printf '%s\n' 'Release preparation requires a clean, locally committed checkout.' >&2
  exit 1
fi
revision="$(git rev-parse HEAD)"
docker build --target base -t cairn-worker:local "$repo_dir"
worker_id="$(docker image inspect cairn-worker:local --format '{{.Id}}')"
docker build --target release --build-arg "CAIRN_REVISION=$revision" \
  --build-arg "CAIRN_WORKER_IMAGE=$worker_id" -t cairn-release:local "$repo_dir"
image_id="$(docker image inspect cairn-release:local --format '{{.Id}}')"
destination="$repo_dir/dist/release-$revision"
if [[ -e "$destination" ]]; then
  printf '%s\n' 'This release output already exists; preserve it and choose a new revision.' >&2
  exit 1
fi
mkdir -p "$destination"
export_id="$(docker create --network=none --read-only --entrypoint /bin/true "$image_id")"
cleanup() { docker rm --force --volumes "$export_id" >/dev/null; }
trap cleanup EXIT
docker cp "$export_id:/opt/release/." "$destination"
profile=(--rm --pull=never --network=none --read-only --cap-drop=ALL
  --log-driver=none --no-healthcheck --restart=no --security-opt=no-new-privileges
  --pids-limit=64 --memory=512m --cpus=1 --user=65532:65532
  --tmpfs=/tmp:rw,noexec,nosuid,size=128m,mode=1777
  --tmpfs=/runtime:rw,exec,nosuid,size=256m,mode=1777)
docker run "${profile[@]}" "$image_id" > "$destination/trial.json"
cat "$destination/trial.json"
