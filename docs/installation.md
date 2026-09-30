# Reviewed offline installation

The public checkout is a development environment. Private initialization and private
restore remain denied while the activation gate is being completed. The release tools
below prepare and verify software with synthetic files; they do not activate a private
workspace or prove that a model is useful.

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
`requirements.txt`, the wheelhouse, and `trial.json`. It is an ignored public build
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

The reference trial for source revision `58f03a6574b56ec9221659d05786cf25d7baa867` passed:
15 distributions and 871 files verified on `linux-aarch64`, CPython 3.13.11. The release
manifest digest is `794b659af81e0e10907909d5cbff82f76704cb86890209b2993a7d1bbf6a7a4c`.
The [committed synthetic report](evidence/release-trial.json) records the workflow and
rejection checks. The local bundle is under `dist/release-58f03a6574b56ec9221659d05786cf25d7baa867/`.

## Before private activation

Complete the manual M2 continuity evaluation, the remaining release audit, and an owner
review of the exact installation, worker image, processing policy, and backup destination.
Acquire dependencies and local model assets without private input. Use an owner runtime
that can access the selected local Docker engine; never give a model worker or development
container its socket. Workers receive only bounded packets and retain no owner mounts.
The reviewed-installation activation command and private restore gate remain pending.
Do not create or attach the owner's actual private workspace during these development
trials, and do not substitute the synthetic-mode flag for real activation.
