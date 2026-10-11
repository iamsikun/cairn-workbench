# Cairn restructuring build plan

Approved 2026-10-11. The direct-save brief is the baseline; the previous plan remains in
docs/legacy/build-plan-v3.md. Historical test passes do not establish this release.
Use synthetic data and execute contributor code in the documented native environment.

| Milestone | Deliverable | Exit evidence |
| --- | --- | --- |
| R1 Requirements | Contributor rules, brief, plan, README, architecture; legacy fixtures | Schemas 1–3 read without rewriting |
| R2 Persistence | Schema 4, shared saves, neutral writer, revisions/recent/undo | Retry, no-op, conflict, crash, undo and index-failure tests |
| R3 Knowledge | Paper identity, learning notebooks, explanations, questions, corrections | Follow-up preservation, graph and collection tests |
| R4 Integration | Ordinary init, six MCP tools, CLI, connections, optional native extraction | Synthetic settings and stdio trials; partial sources |
| R5 Presentation | Visual inputs, HTML, freshness, snapshots, feedback, scenarios | Failure recovery, offline rendering and visual QA |
| R6 Transition | Legacy migration, backup/restore, launcher retirement, installed package | Inventory, crash, updater-race and package trials |

Implementation status, 2026-10-11: R1–R6 are implemented and their automated synthetic
gates passed at `a67a0993d1ccc0842279fffa1de727cc0bb5d39d`. See
[acceptance evidence](docs/acceptance.md) for the requirements-to-test matrix, package
trial and remaining actual-client, semantic-quality and real-machine transition gates.
The package is local and unpublished; these results do not authorize private deployment.

## Contracts and implementation

Extract reusable safe storage and transaction mechanics, not approval wrappers. Add
shared saving and connection services; retain legacy readers separately. Keep the six
record types. Represent unavailable source bytes/extraction honestly. Store explained
relationships and original attributed observations durably.

Requests bind the connection collection, operation key, revisions and content. Lost
responses retry without duplicates. A stale member aborts a ready multi-note bundle.
Save, enrichment, index and view states are separate. The connected agent resumes
semantic work; Cairn runs no independent model. Preserve original observations and
user corrections. Markdown and visual resources are canonical; generated HTML tracks
all inputs, preserves snapshots and routes feedback to source. No implicit scenario saves.

Finch guides reading and Quill develops prose in the current agent. Cairn owns only
persistent integration instructions. It never installs or edits those skills.
Research is the default collection; every interface enforces it before retrieval.

## Verification and commits

Make small local milestone commits and maintain docs/acceptance.md as work proceeds.
Run tests, lint, typing, schema generation and package checks with locked native tools.
Native resource limits and synthetic test environments do not establish OS isolation.
Missing checks remain unverified. Preserve applicable legacy compatibility tests.

Cover retries, concurrent/external edits, crash boundaries, undo, index recovery,
identity/versioning, partial sources, observations, explained links, collection metadata
leakage, connection idempotency, pending enrichment, visual freshness, deterministic
scenarios, backup integrity, migration and updater/launcher races.

Demonstrate synthetic cross-client reading instructions, Quill revision and requested
HTML. Simulated stdio clients are not actual Claude Code/Codex trials. Record any
unavailable client or semantic evaluation explicitly.

## Rollout

Exercise legacy schemas throughout development. Migration backs up before writes,
resolves incomplete transactions, preserves IDs/history/library data and never accepts
pending proposals. Explicitly map ambiguous collections. Retire periodic and launch-time
updates with active-process checks. Keep rollback artifacts and never use an old runtime
on migrated data. No private workspaces, actual homes/settings/schedules, deployment,
pushes, tags, remotes or publication are part of this run.
