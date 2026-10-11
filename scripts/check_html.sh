#!/usr/bin/env bash
set -euo pipefail
repo_dir="$(cd "$(dirname "$0")/.." && pwd)"
# Acquire this image separately as documented; never install during processing.
renderer_image="$(docker image inspect "${1:-answer-html-dev:portable}" --format '{{.Id}}')"
development_image="$(docker image inspect cairn-dev:local --format '{{.Id}}')"
mkdir -p "$repo_dir/dist"
profile=(--rm --pull=never --network=none --read-only --cap-drop=ALL
  --security-opt=no-new-privileges --log-driver=none --no-healthcheck --restart=no
  --user=65532:65532 --pids-limit=768 --memory=4g --cpus=3
  --tmpfs=/tmp:rw,exec,nosuid,size=2g,mode=1777
  --mount "type=bind,source=$repo_dir,target=/work,readonly"
  --mount "type=bind,source=$repo_dir/dist,target=/work/dist")
docker run "${profile[@]}" --workdir /work -e PYTHONPATH=/work/src "$development_image" \
  sh -c 'python scripts/package_html.py && python scripts/package_html.py --output dist/cairn-html-repeat.zip && cmp dist/cairn-html.zip dist/cairn-html-repeat.zip'
docker run "${profile[@]}" --workdir /work -e PYTHONPATH=/work/src "$development_image" \
  python scripts/notebook_demo.py --output /work/dist/notebook-demo
docker run "${profile[@]}" --workdir /work \
  -e AM_CHROME=/work/vendor/answer-me-with-html/scripts/chromium-isolated.sh "$renderer_image" \
  node scripts/notebook_browser.mjs /work/dist/notebook-demo
docker run "${profile[@]}" --tmpfs=/build:rw,exec,nosuid,size=1g,mode=1777 \
  -e AM_E2E=1 -e AM_BROWSER_OUTPUT=/work/dist/browser-html \
  -e AM_CHROME=/build/scripts/chromium-isolated.sh "$renderer_image" sh -c '
    cp -R /work/vendor/answer-me-with-html/. /build
    ln -s /opt/dependencies/node_modules /build/node_modules
    cd /build
    node scripts/check-isolation.mjs
    node scripts/build-application.mjs /tmp/application-first.mjs
    node scripts/build-application.mjs /tmp/application-second.mjs
    cmp /tmp/application-first.mjs /tmp/application-second.mjs
    cmp /tmp/application-first.mjs /work/src/cairn/presentation/resources/application.mjs
    node scripts/build.mjs
    cmp skills/answer-me-with-html/scripts/am.mjs /work/vendor/answer-me-with-html/skills/answer-me-with-html/scripts/am.mjs
    node --test --test-concurrency=2 --test-timeout=180000 test/*.test.js > /work/dist/renderer-tests.log 2>&1
    node scripts/smoke-portable.mjs > /work/dist/generic-node-smoke.json
    python3 -m zipfile -e /work/dist/cairn-html.zip /tmp/installed
    node /work/scripts/html_smoke.mjs /tmp/installed/cairn-html > /work/dist/html-node-smoke.json
  '
printf 'HTML acceptance passed; renderer image %s\n' "$renderer_image"
