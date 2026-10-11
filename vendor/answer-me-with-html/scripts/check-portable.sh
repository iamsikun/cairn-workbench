#!/bin/sh
set -eu
# Dependencies and native tools must already be acquired; see development-portable.md.
: "${CAIRN_NODE20:?select an acquired Node 20 executable}"
: "${CAIRN_NODE22:?select an acquired Node 22 executable}"
: "${CAIRN_NODE24:?select an acquired Node 24 executable}"
: "${AM_HOME:?select a synthetic renderer state directory}"
node scripts/build.mjs
node --test --test-concurrency=2 --test-timeout=180000 test/*.test.js
node scripts/smoke-portable.mjs
node scripts/package-portable.mjs
