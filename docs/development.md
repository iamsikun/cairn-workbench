# Synthetic development

Build the development image using `docker build --target development -t cairn-dev:local .`.
The build context is allowlisted in `.dockerignore`; dependency acquisition occurs before
any data processing. The base and Python dependencies are pinned by digest and `uv.lock`.

Run tests with the processing profile:

```sh
docker run --rm --pull=never --network=none --read-only --cap-drop=ALL \
  --security-opt=no-new-privileges --pids-limit=64 --memory=512m --cpus=1 \
  --log-driver=none --no-healthcheck --restart=no \
  --user=65532:65532 --tmpfs=/tmp:rw,noexec,nosuid,size=128m,mode=1777 \
  --tmpfs=/test:rw,noexec,nosuid,size=512m,mode=1777 -e TMPDIR=/test \
  cairn-dev:local
```

Use the same profile for `ruff check src tests scripts` and `mypy`. Development containers
contain only public files and create synthetic workspaces in container-local temporary
storage. Never mount a host home, private workspace, credentials, or the Docker socket.
For editing/formatting, an explicit mount of only the public checkout is acceptable.

The physical large-library trial runs `python scripts/library_backup_trial.py` with
`--memory=1g` and a 768MiB container-local `/tmp`; it preserves and restores 260MiB of
synthetic blobs. This larger test scratch space is not an inference-worker permission.
No GPU, model or agent account is required by contributor tests; the MCP server is
driven by a synthetic stdio client and simulated agent outputs are labeled.

`scripts/export_schemas.py` generates schemas from the typed models. The schema parity
test detects drift. Run it with only the public checkout writable.

Run `scripts/isolation_probe.py` inside this profile with the absolute path of a synthetic
host canary that is deliberately not mounted. It attempts canonical/policy/approval
writes, network and DNS access, and launches a hostile subprocess. A skipped or failed
probe is a failed isolation gate. Delete the synthetic canary using ordinary owner
maintenance when no longer needed; never use real private data as a canary.

The host Docker launcher is trusted. A client that can control that launcher or the Docker
daemon is outside the worker boundary. The application never mounts its daemon socket
inside a worker. This boundary does not defend against a compromised host/engine.

`examples/workspace.example.json` documents the machine-local configuration shape using
fictional paths and synthetic mode. It is not a complete workspace or private approval.
Use `cairn init /synthetic/workspace --synthetic` to create development fixtures. Direct-save
installation needs no activation. Legacy fixtures use the historical APIs and validators.
No actual owner paths, settings, runtime approvals or credentials belong in the checkout.

## Presentation resources and portable package

The Docker build acquires the pinned Node 24 image and locked npm dependencies in
separate stages, then runs the application build with `RUN --network=none`. The
worker receives just the Node binary and generated application runtime alongside
Cairn. A checkout builds without a sibling renderer project or an installed skill.
`check.sh` includes a real no-mount JSON renderer roundtrip and required isolation
probes; a skip cannot satisfy these gates.

For renderer regression tests and Chromium, acquire the separate development image
as documented in `vendor/answer-me-with-html/docs/development-portable.md`. It pins
Node 20.19.0, 22.14.0 and 24.0.0 for compatibility trials. Run processing with that
document's offline, non-root, read-only profile, public checkout only, and executable
synthetic scratch. Copy the vendor tree into scratch and link the acquired
`/opt/dependencies/node_modules`. From the vendor directory run:

```text
node scripts/build-application.mjs /work/src/cairn/presentation/resources/application.mjs
node scripts/check-isolation.mjs
node --test --test-concurrency=2 --test-timeout=180000 test/*.test.js
```

Set `AM_E2E=1` and point `AM_CHROME` at the supplied isolated Chromium wrapper.
`AM_BROWSER_OUTPUT` can select a public synthetic screenshot directory. The Cairn
application browser test fails when Chromium is unavailable. Its Chromium wrapper
is for the outer isolated container only. Capture and inspect light/dark screenshots
at desktop and narrow widths, feedback downloads, print output and request logs.

Build twice and compare the application runtime byte for byte with the committed
resource. The application uses whitespace minification to remove machine-dependent
dependency path comments. The unchanged generic CLI's historical bundle includes esbuild dependency
path comments: reproduce its original one-level build directory (`/build`) and
`/opt/dependencies/node_modules` layout when comparing its exact checksum. A different
working-directory depth changes those comments, not behavior. Never hand-edit a
bundle to force equality.

After rebuilding, use the Cairn development container with only the public checkout
writable to run:

```text
python scripts/html_provenance.py
python scripts/package_html.py
python scripts/package_html.py --output dist/cairn-html-repeat.zip
```

Compare the two ZIPs. Extract one under synthetic scratch and run
`node scripts/html_smoke.mjs EXTRACTED/cairn-html` in the renderer development image.
This exercises the packaged renderer on all three Node versions with ordinary and
space/non-ASCII install paths and without agent environment variables. The skill's
runtime directory is assembled in the portable ZIP; the repository keeps
one canonical resource copy under `src/cairn/presentation/resources`.

The separate `html_packet_trial.py prepare --output DIRECTORY` exports an entirely
synthetic packet and a checksummed synthetic backup. Supply a real agent's response
as `response.json`, then run `html_packet_trial.py import --output DIRECTORY` in the
same isolated profile. It verifies import and unchanged canonical files; a manual
review of claims, numbers and uncertainty is still required. It cannot establish a
local execution attestation or broad semantic quality.

## Maintaining the renderer snapshot

The licensed renderer source snapshot is pinned to upstream 0.5.0 commit
`19b2b5b07676d3e65c83ca9a7b6621f300b54c92`, plus the maintained portable changes and
application profile. `resources/provenance.json` records the maintained commit,
every source hash, lockfile and generated runtime. Cairn vendors no agent skills; packets
carry Cairn's own contracts.

For updates, acquire public source/dependencies separately; compare upstream changes;
retain offline defaults, explicit request routing and local modifications; synchronize
the standalone maintained renderer source; rebuild; regenerate provenance and schemas;
run regression, browser, isolation, release and package checks; then make the new
package reviewable. Existing installed skills are separate and remain unchanged by
workbench maintenance. Keep prior release bundles as rollback artifacts. Never add
remotes, update installations, export private inputs or publish packages as an
implicit part of this process.

`bash scripts/check_html.sh` combines the renderer, required browser/isolation,
rebuild and portable-runtime checks above once the separate renderer image and
`cairn-dev:local` have been acquired. It mounts only the public checkout read-only
and its synthetic `dist` output directory writable, and selects immutable local image
IDs. It fails if the required image/browser or any mandatory check is unavailable.
