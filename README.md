# Cairn Workbench

Cairn compiles selected evidence into a reviewable Markdown wiki and scoped project
context. Sources and human notes are preserved. Models propose changes; the owner
approves and applies them.

The software repository is named `cairn-workbench`. The separately configured private
knowledge-base directory is named `cairn`. The Python package and CLI remain `cairn`.

M0–M3 reference acceptance is complete. See [the build plan](CAIRN_BUILD_PLAN.md) and
[acceptance tracking](docs/acceptance.md). Do not use this checkout with private data.

M0 and M1 now have an executable synthetic workflow: capture, text/PDF/conversation
extraction, bounded proposals, exact owner approval, recoverable apply, local history,
scoped evidence/synthesis search, staged owner edits, and backup/restore. M2 adds selected
CSL-JSON bibliography import, project framing, attributed session receipts, explicit
decision adoption, bounded context packs, and repository-staleness checks. The supplied
manual second-session response passes the narrow design-level continuity review, with
receipt-format and citation limits recorded. M3 includes structured financial snapshots,
exact Decimal calculations, dated financial notes, sourced life hubs, and direct evidence
review, audited owner scopes/grants, and complete-request route checks. Cloud execution
remains unavailable. Explicit backed-up workspace migration and the
[synthetic evaluation report](docs/evaluation.md) are implemented. The
[requirements audit](docs/requirements.md) and installed-release checks are complete;
the [manual M2 result](docs/research-continuity.md#recorded-manual-result) closes the last
milestone gate. This is not owner approval for private deployment.

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
`repository inspect`, `context`, `finch`, `policy`, `release`, `schema`, and `doctor`. Pass
`--workspace` (or `CAIRN_WORKSPACE`) and use `--json`
for structured command output. Development `init` and `restore` use `--synthetic`.
Private initialization and restore require a reviewed installed release, explicit owner
acknowledgements, and a fresh worker-isolation probe.
The [schema migration runbook](docs/schema-migrations.md) covers explicit format changes,
pending-approval invalidation, backups, and interrupted-migration recovery.

Read the [architecture](docs/architecture.md), [threat model](docs/threat-model.md),
[processing policy](docs/privacy.md), [recovery procedure](docs/recovery.md), and
[agent protocol](docs/agent-integration.md) before choosing an execution profile.
The [review procedure](docs/review.md) explains terminal/Markdown diffs, local evidence
links, dated conflicts, and the distinction between quote support and owner approval.

The [research workflow and manual continuity procedure](docs/research-continuity.md)
explain the M2 distinction between preserved session suggestions and adopted decisions.
The [synthetic context fixture](examples/continuity/context.json), supplied response, and
separate reviewer assessment retain the manual trial. The owner's verdict remains
"unclear"; the reviewer explains the observed pass without inferring owner approval.

The [personal domain workflows](docs/personal-domains.md) cover `finance import`,
`finance calculate`, `finance note`, `life import`, and `evidence`. Calculation inputs
come from preserved structured sources, with owner/account/date/unit/currency separation.

## Requested HTML and writing packets

Cairn now provides explicit offline HTML views for project context, extractive queries,
evidence, paper readings, proposals, catalogs and journal feeds. Quill-guided explanation
and feedback packets preserve owner approval and scoped evidence. See
[HTML views](docs/html-views.md) for commands and [acceptance](docs/acceptance.md) for
executed checks and deployment limits. The portable `cairn-html` skill consumes owner
exports; it grants no workspace access and does not generate unsolicited pages.

## Automatic Finch paper reading

Paper reading uses Finch automatically. Library readings already capture evidence and
stage reading proposals; they bind the bundled Finch guidance to each job. When a private
workspace is initialized and no Finch is available, `cairn init` runs Finch's own
installer, which links Finch into every detected agent (Claude Code, Codex, Gemini CLI,
Cursor, Copilot, OpenCode) and schedules Finch's daily update. Pass `--no-finch` to skip it
or `--no-finch-auto-update` to install without the scheduled update. An existing Finch is
left untouched. Finch carries its own Cairn handoff guide, so in a configured agent
session, every Finch invocation inside the knowledge base captures its supplied
discussion and stages a validated concept-note proposal before returning the answer.
Approval and canonical apply remain owner operations. See
[Finch setup and handoff](docs/finch-reading.md) for installation, packets, retries,
processing consent and the explicit pending state when no owner launcher is configured.
