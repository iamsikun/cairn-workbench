#!/usr/bin/env bash
set -euo pipefail
repo_dir="$(cd "$(dirname "$0")/.." && pwd)"
cd "$repo_dir"
if [[ ! -x .venv/bin/python ]]; then
  printf '%s\n' 'Acquire native dependencies first: UV_NO_CONFIG=1 uv sync --locked' >&2
  exit 1
fi
exec .venv/bin/python scripts/native_checks.py html
