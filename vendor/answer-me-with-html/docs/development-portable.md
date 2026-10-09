# Isolated development

This project is standalone. Do not bind a real workspace, user home, credentials, or a Docker socket into contributor processing. Use a staging copy containing public source and synthetic fixtures only. Do not add a Git remote or publish as part of maintenance.

## Acquire dependencies separately

Build `dev/Dockerfile` in a temporary build context. Put the committed package.json and package-lock.json there. Download official Linux ARM64 Node archives for 20.19.0, 22.14.0, and 24.0.0 from nodejs.org, verify each against that release's SHASUMS256.txt, and extract the directories named in the Dockerfile into the context. The image acquires Debian packages and lockfile npm dependencies during this separate network-enabled phase; it runs no project code. Use equivalent verified architecture builds on other platforms and record them.

The image is an input to processing, not evidence of isolation by itself. Invoke it with `--network=none`, `--read-only`, `--cap-drop=ALL`, `--security-opt=no-new-privileges`, a non-root UID, resource limits, no credential environment, and no Docker socket. Mount only the public staging copy at `/work`. A temporary executable scratch mount is needed for upstream mock-executable tests; it contains synthetic data only. Chromium's test wrapper disables its sandbox because the outer container provides the processing boundary. Do not use that wrapper outside this environment.

Example (substitute the public staging path):

```text
docker run --rm --pull=never --network=none --read-only --cap-drop=ALL --security-opt=no-new-privileges --pids-limit=768 --memory=4g --cpus=3 --log-driver=none --no-healthcheck --restart=no --user=65532:65532 --tmpfs=/tmp:rw,exec,nosuid,size=1g,mode=1777 -e TMPDIR=/tmp -e AM_HOME=/tmp/am-state -e AM_CHROME=/work/scripts/chromium-isolated.sh -e AM_E2E=1 --mount type=bind,source=/path/to/public-staging,target=/work answer-html-dev:portable sh scripts/check-portable.sh
```

`check-isolation.mjs` is a mandatory gate and fails rather than skipping. Record Docker's actual image ID, mount list, network mode, capabilities and read-only setting as independent host-side evidence. A skipped process-ownership fixture is unrelated to, and cannot replace, this isolation gate.

## Validation

`scripts/check-portable.sh` builds, runs the full upstream suite and portable regressions with Chromium, checks the copied skill on Node 20/22/24, writes provenance/licenses, and checks deterministic rebuilds. Review browser screenshots from `AM_BROWSER_OUTPUT` when used. For historical comparison, run `node scripts/snapshot.mjs d178109 --portable-policy-diff` with that imported baseline available. This flag accepts only the exact added CSP and reduced-motion CSS; any other output difference or patch instability fails.

No live cloud provider, agent product, or external website is exercised in processing. Fake-provider tests prove control flow, not voice or semantic quality. Report executed checks, failures, and skips separately in `docs/acceptance.md`.
