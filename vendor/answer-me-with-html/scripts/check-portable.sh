#!/bin/sh
set -eu
node scripts/check-isolation.mjs
if [ ! -e node_modules ]; then ln -s /opt/dependencies/node_modules node_modules; fi
npm run build
node --test --test-concurrency=2 --test-timeout=180000 test/*.test.js
node scripts/smoke-portable.mjs
node scripts/package-portable.mjs
sha256sum skills/answer-me-with-html/scripts/am.mjs > /tmp/bundle-first.sha256
npm run build
sha256sum -c /tmp/bundle-first.sha256
