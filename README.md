# Cairn

Cairn compiles selected evidence into a reviewable Markdown wiki and scoped project
context. Sources and human notes are preserved. Models propose changes; the owner
approves and applies them.

Implementation is in progress. See [the build plan](CAIRN_BUILD_PLAN.md) and
[acceptance tracking](docs/acceptance.md). Do not use this checkout with private data.

M0 and M1 now have an executable synthetic workflow: capture, text/PDF/conversation
extraction, bounded proposals, exact owner approval, recoverable apply, local history,
scoped evidence/synthesis search, staged owner edits, and backup/restore. M2 adds selected
CSL-JSON bibliography import, project framing, attributed session receipts, explicit
decision adoption, bounded context packs, and repository-staleness checks. Its manual
second-agent usefulness gate is pending. M3 now includes structured financial snapshots,
exact Decimal calculations, dated financial notes, sourced life hubs, and direct evidence
review, audited owner scopes/grants, and complete-request route checks. Cloud execution
remains unavailable. Explicit backed-up workspace migration and the
[synthetic evaluation report](docs/evaluation.md) are implemented. The final requirements
audit is in progress.

Python package: `cairn`; command: `cairn`. Development uses synthetic workspaces outside
the checkout. A private deployment requires a reviewed, pinned installation and a
verified execution boundary. No network or cloud processing is enabled by default.

Run `bash scripts/check.sh` to build the pinned development and worker images and execute
the tests, lint, strict typing, isolation probes, and installed packet/extraction trials.
The checks use synthetic data and do not mount a private workspace or host home.
For a clean committed checkout, `bash scripts/release_check.sh` prepares a pinned
wheelhouse and runs a separate offline installed-CLI trial. The
[installation runbook](docs/installation.md) describes its verified target and the
owner activation gate. Actual private deployment remains separate from development.

The CLI provides `init`, `capture`, `ingest`, `proposal show`, `validate`, `approve`,
`apply`, `recover`, `search`, `query`, `edit`, `lint`, `rebuild-index`, `backup`, `restore`,
`client run`, `project create`, `bibliography import`, `receipt import`, `decision adopt`,
`repository inspect`, `context`, `policy`, `release`, `schema`, and `doctor`. Pass
`--workspace` (or `CAIRN_WORKSPACE`) and use `--json`
for structured command output. Development `init` and `restore` use `--synthetic`.
Private initialization and restore require a reviewed installed release, explicit owner
acknowledgements, and a fresh worker-isolation probe.
The [schema migration runbook](docs/schema-migrations.md) covers explicit format changes,
pending-approval invalidation, backups, and interrupted-migration recovery.

Read the [architecture](docs/architecture.md), [threat model](docs/threat-model.md),
[processing policy](docs/privacy.md), [recovery procedure](docs/recovery.md), and
[agent protocol](docs/agent-integration.md) before choosing an execution profile.

The [research workflow and manual continuity procedure](docs/research-continuity.md)
explain the M2 distinction between preserved session suggestions and adopted decisions.
The [synthetic context fixture](examples/continuity/context.json) is ready for a manually
started second session; deterministic protocol success is not semantic acceptance.

The [personal domain workflows](docs/personal-domains.md) cover `finance import`,
`finance calculate`, `finance note`, `life import`, and `evidence`. Calculation inputs
come from preserved structured sources, with owner/account/date/unit/currency separation.
