# Working on Cairn

Read KNOWLEDGE_WORKBENCH_BUILD_BRIEF.md and CAIRN_BUILD_PLAN.md before changing boundaries.
The approved direct-save restructuring supersedes proposal-only and managed-runtime
requirements. Historical requirements and evidence remain under docs/legacy.

Develop and execute contributor code only in the documented development container with
synthetic data. Never inspect or mount a real private workspace, home, credentials, or
Docker socket. Acquisition may use networking; processing containers have no network,
owner filesystem, or credentials. A skipped isolation check is not a pass.

New-format Cairn connects the owner's existing agent to a fixed collection (research by
default). Ordinary saves need no cloud grant, proposal, approval, activation, or terminal
acknowledgement. Client/model metadata is provenance, not authorization. Collection
filtering governs Cairn tools, not independent filesystem access by the agent.

Keep original source bytes immutable and user contributions attributed and recoverable.
Saving never verifies a claim or adopts a decision. Preserve six record types, stable IDs,
source locators, safe paths, a recoverable writer, revision checks, and schema parity.
Markdown and editable visual resources are authoritative; indexes and HTML are derived.
Persist readings independently of extraction, enrichment, indexing, and rendering;
report their states honestly. Use operation keys for retries and compensating undo.

Cairn never launches a semantic agent. Finch supplies reading method and Quill supplies
writing method inside the owner's agent. Do not install, vendor, edit, or update either
skill. Cairn owns connection instructions and contracts. New MCP exposes only capture,
search, get_note, list_topics, save_reading, and save_note.

Keep legacy validators/readers for migration, backups, and historical provenance.
Never reinterpret pending proposals as saved knowledge or bypass legacy authorization
by pretending a real workspace is synthetic. Migration is explicit, backed up, journaled,
and tested on schemas 1–3. Retire scheduled and startup updates through a verified
transition handling active processes and retaining rollback artifacts. Package upgrades
do not implicitly migrate data. No real schedules or installations change in development.

Use small milestone commits and maintain docs/acceptance.md with executed evidence.
Run meaningful failure-mode tests in the container. Keep protocol tests separate from
actual Claude Code/Codex trials and semantic quality. Never add a remote, push, publish,
deploy, migrate private data, or change actual client settings in contributor work.
