# Cairn — direct-save knowledge workbench

Approved restructuring requirements, 2026-10-11. Evidence belongs in docs/acceptance.md;
this specification does not claim completion. The previous baseline is preserved in
docs/legacy/build-brief-v3.md and superseded for new-format operation.

## Product

Connect once, read and discuss, save automatically, connect new knowledge, and continue
in another session or client. Cairn is a personal Markdown knowledge base used from an
existing agent. It does not launch an agent or require an independent model API.
Finch guides reading; Quill develops learning explanations while preserving scientific
meaning, uncertainty and observations. Both remain independent skills.

## Knowledge

Retain source, concept, project, decision, entity, and playbook records with stable IDs.
One evolving paper note preserves coverage, explanations, checkpoints, original user
contributions and questions. Topic notebooks develop intuition, prerequisites, mechanisms,
equations, examples and comparisons. Research questions connect competing explanations,
evidence, missing evidence and possible experiments.

Use topic branches and directed cross-links; topics may have multiple broader topics.
Relationships carry an explanation, supporting references when available, and distinguish
source-stated from inferred connections. Preserve aliases, renames and rejected links.
Prefer enriching existing topics. The connected agent reasons about relationships;
Cairn stores them and records unfinished enrichment for future sessions.

## Saving and scope

New state machine: validate -> prepared -> committed. Enrichment, indexing, rendering
and extraction have independent statuses. Saves need no proposals, grants, terminal
approval, runtime activation or release rebind. A saved claim remains unreviewed.
Client/model metadata is provenance, not permission.

CLI and MCP share save_reading and save_note. Bind stable identities, expected revisions
and operation keys; Cairn selects paths. Validate all targets under a lock; journal
before/after bytes and commit revision receipts with content. Identical retries return
the original result; changed payloads under the same key fail. No-op saves cause no
revision churn. Hashes detect external edits. Preserve user contributions separately
from replacement synthesis. Undo is compensating and preserves unrelated later work.

Include ready topic updates atomically, but save promptly when more enrichment is needed.
Index failures report a saved revision and pending state; search repairs or falls back
within the collection. Rendering failures preserve the last working view.
Default collection is research, including human research notes. Finance, life and
ambiguous shared content require separate selection. Filter before search ranking,
counts, backlinks, context, history and HTML. This is a tool boundary, not an agent sandbox.

## Formats

Markdown holds explanations and conclusions. Version diagram definitions, figure assets,
datasets and deterministic interactive formulas as companions. Explain visual findings
in text. Generate HTML on request, record all input revisions, support freshness and
immutable snapshots, and route feedback to source content. Support equations, citations,
captions, offline assets, print, narrow screens and reduced motion. Scenarios remain
temporary until explicitly saved. Imported material cannot authorize code or networking.

## Connection and sources

Target cairn init PATH and cairn connect claude|codex --workspace PATH. Connection manages
only Cairn-owned settings/instructions, preserves unrelated settings, is repeatable and
supports check/repair/disconnect. Expose capture, search, get_note, list_topics,
save_reading and save_note over stdio MCP. Retrieve current notes, apply Finch/Quill,
save substantive checkpoints, and report links only after confirmed persistence.
Cairn does not install, edit or update either skill.

Accept PDFs, URLs, DOIs and supplied material without mandatory extraction. Unknown
metadata stays unknown. Source bytes remain immutable and versions distinct. Native
parsers use resource limits, not claimed container-equivalent isolation. Ordinary
operation needs no Docker; contributor execution stays in the development container.

## Compatibility and delivery

Preserve bibliography, journal-library records, multilingual search, project context,
finance/life and backups. Migrate schemas 1–3 explicitly with a verified backup, inventory
checks, recoverable journal and explicit ambiguous collection mapping. Preserve pending
proposals as legacy material. Never open migrated data with the old runtime.
Retire managed scheduled and startup updates through a verified transition accounting for
active processes and rollback. Package installation does not implicitly migrate data.
No private deployment, actual settings/schedule changes, pushes or publication occur here.

Test synthetic crashes, conflicts, retries, undo, scope leakage, partial sources,
relationships, visual freshness, migration, backup and installation. Actual client
behavior and semantic quality are separate acceptance gates.
