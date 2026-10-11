# Native synthetic development

Use macOS or Linux, Python 3.12+, `uv`, Git, and Node 24. No Docker daemon, images,
worker activation, model account, or private inputs are needed. Native execution is
not a filesystem or network sandbox. Work only with this public checkout and synthetic
scratch; never use a real knowledge base, credentials, client settings, or schedules.

## Acquire dependencies

Acquisition may use networking. Keep it separate from acceptance runs:

```sh
UV_NO_CONFIG=1 UV_CACHE_DIR="$PWD/.cache/uv" uv sync --locked
cd vendor/answer-me-with-html
npm ci --ignore-scripts --userconfig /dev/null
```

Use npm from the Node 24 installation. HTML acceptance additionally requires native
Chrome/Chromium, `ffmpeg`/`ffprobe`, and system speech synthesis (`say` on macOS or
`espeak-ng` on Linux) for the retained generic renderer regression suite. Linux CI
installs Noto fonts. Keep Chromium's sandbox enabled: do not use `--no-sandbox` or the
retired container wrapper. Browser profiles and downloads are temporary synthetic data.
`AM_CHROME` may select the browser executable.

Acquire Node 20, 22, and 24 separately for portable-package trials. Set
`CAIRN_NODE20`, `CAIRN_NODE22`, and `CAIRN_NODE24` to their absolute executable paths;
Node 24 on PATH supplies the last default. Use official architecture-specific Node
archives verified against their release's `SHASUMS256.txt`, or your CI tool setup.
No check downloads missing tools. A missing mandatory tool is a failure, not a skip.

## Run acceptance

From the repository root:

```sh
bash scripts/check.sh
bash scripts/check_html.sh
# Requires a clean, locally committed checkout; writes a new dist/release-REVISION:
bash scripts/release_check.sh
```

The common runner strips inherited application/credential environment variables, selects
synthetic state/cache directories, disables update checks, and places a rejecting Docker
sentinel on PATH. It never changes the invoking shell's home or settings. These controls
reduce accidental configuration use; they do not enforce a host security boundary.
The Python suite also overrides home discovery with a synthetic directory.

`check.sh` runs pytest (including schema parity), Ruff, mypy, the continuity packet,
129-check synthetic gold set, and a physical 260MiB backup/restore trial. Outputs go to
`dist/`. Legacy authorization fixtures are constructed only in tests; worker launch,
activation, rebinding and updater installation/enabling return retirement errors.
Existing installation retirement, archive validation and explicit schema-1–3 migration
remain covered. Tests never change actual launchd/cron jobs or agent settings.

`check_html.sh` copies renderer source into scratch, builds application and generic
bundles twice and compares them with the committed resources, runs renderer/browser
regressions, compares two portable ZIPs, and exercises Node 20/22/24 with ordinary and
space/non-ASCII installation paths. It captures desktop/narrow, light/dark, print,
feedback, reduced-motion and offline-page evidence under `dist/`. Inspect screenshots
when changing visual behavior. Local browser protocol traffic is expected; the page
request checks reject external resource requests, not all host network activity.

`release_check.sh` explicitly acquires locked wheels and builds a native version-2
release manifest. Its separate trial installs only from the wheelhouse using
`--offline --no-index --require-hashes` in a fresh temporary environment. It verifies
installed CLI/MCP saving, migration, connections in synthetic settings, HTML, recovery,
backup/restore, undo and rejection of altered installed files. It neither installs a
real user launcher nor migrates owner data. Version-1 release manifests remain readable
and strict for historical validation; version 2 contains no worker image or activation.

## Resource and compatibility limits

Native subprocesses enforce deadlines, stdout/stderr budgets and cleanup of their owned
process group. They do not confine a child that deliberately creates another session.
PDF extraction limits input, pages, text, CPU time and elapsed time. Linux additionally
limits address space to 512MiB; macOS has no equivalent address-space limit here.
Failed parsing retains immutable original bytes and reports extraction failure.
Node is optional for ordinary installed saves and required for requested HTML.

## Maintaining generated files

Run `.venv/bin/python scripts/export_schemas.py` after model changes; parity tests
compare every exported schema. For renderer changes, build from the locked vendor
snapshot with Node 24, then regenerate provenance:

```sh
(cd vendor/answer-me-with-html && node scripts/build.mjs)
(cd vendor/answer-me-with-html && node scripts/build-application.mjs ../../src/cairn/presentation/resources/application.mjs)
.venv/bin/python scripts/html_provenance.py
```

Both builders remove machine-dependent path comments. Never hand-edit generated bundles.
Keep third-party licenses and source hashes. Cairn never installs or edits Finch or Quill.
Historical container evidence stays in `docs/acceptance.md` and `docs/legacy`; it does not
establish native acceptance. Record native test results separately, distinguishing
protocol checks from actual agent trials and semantic quality. No remote, push, publish,
private deployment or actual installation changes are part of contributor work.
