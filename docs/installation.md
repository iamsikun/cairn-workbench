# Reviewed offline installation

The public checkout is a development environment. Private initialization and private
restore require a verified installation, explicit owner review, and a fresh isolation
probe. Development trials use synthetic files only; they do not activate the owner's
private workspace or prove that a model is useful. The manual continuity gate and the
remaining release audit are still pending.

## Prepare a reference bundle

Run `bash scripts/check.sh`, commit the reviewed public changes locally, then run
`bash scripts/release_check.sh`. The release script requires a clean checkout. Build-time
network access obtains only public packages; the manifest records the exact source
revision, source/lock hashes, wheel hashes, package versions and installed file hashes,
Python binary/version/implementation/platform, worker image, and adapter versions.
Dependencies are selected from the production closure of `uv.lock`, downloaded from its
locked wheel URLs, and checked against its sizes and SHA-256 digests. No dependency
resolution or source build is permitted during installation into the fresh runtime.

The resulting `dist/release-REVISION/` contains `release.json`, `release.sha256`, `uv.lock`,
`requirements.txt`, the wheelhouse, `trial.json`, and `worker-profile.json`. It is a public build
artifact. Keep the reviewed manifest digest separately; a checksum stored alongside an
untrusted replacement bundle is not an independent trust anchor. Inspect the local
revision and acceptance evidence before treating an artifact as reviewed. A manifest
does not provide a publisher signature or certify the host/interpreter's integrity.

The Docker reference bundle targets the exact Linux platform and interpreter recorded
in its manifest. It is not a macOS wheelhouse. A different deployment target needs its
own compatible, reviewed bundle and installation trial; do not override the platform
check or run an editable checkout as a substitute.

## Offline installation trial

The release trial runs with networking disabled, no host mounts or credentials, a
read-only root, dropped capabilities, and a non-root user. Its executable `/runtime`
tmpfs supports loading the freshly installed binary dependency; ordinary `/tmp` remains
non-executable. The installation phase uses `uv pip install --offline --no-index
--find-links WHEELHOUSE --only-binary :all: --require-hashes -r requirements.txt` in a
new, unseeded virtual environment. `UV_COMPILE_BYTECODE=0` prevents installation-time
bytecode generation. See [uv's hash-checking behavior](https://docs.astral.sh/uv/pip/compatibility/#hash-checking-support)
and [lockfile export documentation](https://docs.astral.sh/uv/concepts/projects/export/)
for the upstream mechanisms; Cairn's requirements file contains only the selected wheels.

Invoke the installed runtime as `RUNTIME/bin/python -I -B -m cairn`. The `-I` flag avoids
current-directory/PYTHONPATH imports; `-B` prevents new bytecode. `release check-runtime
MANIFEST --sha256 REVIEWED_DIGEST --json` requires a dedicated environment, an exact
interpreter/platform match, matching distributions and files, and an installed Cairn
origin. It rejects editable metadata, extra site-packages files and bytecode, modified
package files, and mismatched versions. Generated installer metadata is excluded from
wheel-file comparison. The reviewed manifest also pins uv's environment bootstrap files.
The inventory uses [Python distribution metadata](https://docs.python.org/3/library/importlib.metadata.html).

`release check-bundle DIRECTORY --sha256 REVIEWED_DIGEST --json` validates the locked
artifacts and the exact installation requirements before installation. A trusted verifier
must perform this check; running an untrusted program to verify itself is insufficient.
The checks detect accidental drift within an owner-reviewed setup. They cannot protect
against a compromised OS, Python interpreter, installer, or owner account.

The trial verifies installed imports, synthetic capture/extraction/proposal/review/apply,
source-aware query, backup and restore. It then changes a package file, adds an inert
unreviewed `.pth`, and marks installation metadata editable, checking rejection each time.
Only synthetic files are involved. Runtime verification reports `private_ready: false`:
live worker-profile verification and explicit release activation are separate gates.

The new trial attempts activation with synthetic review acknowledgements but without an
accessible Docker engine. It requires a blocked result and no destination. The host
script separately probes the exact manifest-bound worker image with 64 MiB scratch,
a fresh nonce, and an unmounted synthetic canary. No daemon socket is exposed to
contributor Python. These component checks do not claim a successful private activation
on the owner's target machine.

The reference trial for source revision `58f03a6574b56ec9221659d05786cf25d7baa867` passed:
15 distributions and 871 files verified on `linux-aarch64`, CPython 3.13.11. The release
manifest digest is `794b659af81e0e10907909d5cbff82f76704cb86890209b2993a7d1bbf6a7a4c`.
The [committed synthetic report](evidence/release-trial.json) records the workflow and
rejection checks. The local bundle is under `dist/release-58f03a6574b56ec9221659d05786cf25d7baa867/`.

## Owner activation after release review

Complete the manual M2 continuity evaluation, the remaining release audit, and an owner
review of the exact installation, worker image, processing policy, and backup destination.
Acquire dependencies and local model assets without private input. Use an owner runtime
that can access the selected local Docker engine; never give a model worker or development
container its socket. Workers receive only bounded packets and retain no owner mounts.
Do not create or attach the owner's actual private workspace during development trials,
and do not substitute the synthetic-mode flag for real activation.

After completing those reviews, use the installed interpreter on a compatible owner
machine. The paths below are generic examples. `REVIEWED_DIGEST` comes from the owner's
independently reviewed release; each acknowledgement records a completed review.

```sh
/srv/cairn-runtime/bin/python -I -B -m cairn init \
  --workspace /srv/cairn-private --code-root /srv/cairn-code \
  --release /srv/cairn-release/release.json --release-sha256 REVIEWED_DIGEST \
  --statement "I reviewed this release, continuity trial, and recovery procedure." \
  --acknowledge release_review --acknowledge manual_continuity --acknowledge backup_restore
```

The command verifies consent and installation before probing the manifest's pinned
worker. The probe contains only a fresh nonce and a synthetic canary path; all 13 checks
must pass and the host canary must remain unchanged. Missing, failed, or replayed checks
block initialization. The workspace is initialized in an owner-only sibling directory
and published after validation. Configuration binds the exact release digest, worker
image, and immutable `receipts/runtime/` approval. The exact manifest is retained at
`policy/runtime-release.json`.

Subsequent private-workspace opens and locked operations verify that binding and the
installed package inventory. A changed installation or worker requires separate owner
maintenance; it cannot silently become the runtime for existing private data.
`--inline-synthetic` never bypasses isolation in private mode. A custom client image must
be part of the reviewed release, not a new command-line override.

`doctor --workspace PATH --probe-worker --json` reports installation, SQLite FTS5, and a
fresh worker profile. Without the probe, readiness remains false because the current
engine was not checked. Synthetic workspaces never report private readiness. Readiness
covers those checks and stored owner review; it does not certify model quality or complete
security. `release check-worker IMAGE --json` runs the same synthetic probe independently.
Diagnostics do not download models, change policy, start services, or grant cloud access.

Approval authority remains the owner process's exclusive filesystem access. These flags
do not sandbox an agent with owner shell/daemon access. Workers have no approval, apply,
init, restore, or release-mutation endpoint and no owner mounts.
