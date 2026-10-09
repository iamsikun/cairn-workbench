#!/bin/sh
# Test-only wrapper: the container supplies the process/filesystem/network boundary.
# Never use this wrapper to browse private or untrusted host content.
export XDG_CONFIG_HOME=/tmp/chromium-config
export XDG_CACHE_HOME=/tmp/chromium-cache
exec /usr/bin/chromium --no-sandbox --disable-dev-shm-usage --disable-breakpad --disable-background-networking --disable-component-update --disable-sync --disable-extensions "$@"
