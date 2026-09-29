# Cairn

Cairn compiles selected evidence into a reviewable Markdown wiki and scoped project
context. Sources and human notes are preserved. Models propose changes; the owner
approves and applies them.

Implementation is in progress. See [the build plan](CAIRN_BUILD_PLAN.md) and
[acceptance tracking](docs/acceptance.md). Do not use this checkout with private data.

M0 and M1 now have an executable synthetic workflow: capture, text/PDF/conversation
extraction, bounded proposals, exact owner approval, recoverable apply, local history,
scoped evidence/synthesis search, staged owner edits, and backup/restore. M2 research
continuity and M3 domain/release work are still pending.

Python package: `cairn`; command: `cairn`. Development uses synthetic workspaces outside
the checkout. A private deployment requires a reviewed, pinned installation and a
verified execution boundary. No network or cloud processing is enabled by default.

Run `bash scripts/check.sh` to build the pinned development and worker images and execute
the tests, lint, strict typing, isolation probes, and installed packet/extraction trials.
The checks use synthetic data and do not mount a private workspace or host home.

The CLI provides `init`, `capture`, `ingest`, `proposal show`, `validate`, `approve`,
`apply`, `recover`, `search`, `query`, `edit`, `lint`, `rebuild-index`, `backup`, `restore`,
`client run`, and `doctor`. Pass `--workspace` (or `CAIRN_WORKSPACE`) and use `--json`
for structured command output. `init` currently requires `--synthetic`; private activation
will require a reviewed installation rather than an editable checkout.

Read the [architecture](docs/architecture.md), [threat model](docs/threat-model.md),
[processing policy](docs/privacy.md), [recovery procedure](docs/recovery.md), and
[agent protocol](docs/agent-integration.md) before choosing an execution profile.
