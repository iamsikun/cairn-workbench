#!/usr/bin/env bash
set -euo pipefail
repo_dir="$(cd "$(dirname "$0")/.." && pwd)"
cd "$repo_dir"
if [[ ! -x .venv/bin/python ]]; then
  printf '%s\n' 'Acquire native dependencies first: UV_NO_CONFIG=1 uv sync --locked' >&2
  exit 1
fi
if [[ -n "$(git status --porcelain --untracked-files=all)" ]]; then
  printf '%s\n' 'Release preparation requires a clean, locally committed checkout.' >&2
  exit 1
fi
revision="$(git rev-parse HEAD)"
destination="$repo_dir/dist/release-$revision"
if [[ -e "$destination" ]]; then
  printf '%s\n' 'Release output exists; preserve it and choose a new revision.' >&2
  exit 1
fi
# Acquisition is explicit; only the subsequent installation/trial is offline.
.venv/bin/python scripts/native_checks.py acquire-release "$destination" "$revision"
exec .venv/bin/python scripts/native_checks.py release "$destination"
