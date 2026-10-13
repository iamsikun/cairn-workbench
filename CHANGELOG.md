# Changelog

## 0.6.0 — optional catalog and gardener packages

The journal catalog and the kb-gardener tooling that lived inside a knowledge base are now
optional packages of this repository. The knowledge base holds notes only; tools, data
and run state live outside it. The core is unchanged.

- `cairn-catalog` (`packages/catalog`): the public journal catalog with its offline
  browser, catalog app (`serve --open`), incremental `update`, search and `import-paper`.
  Its data and preferences live in `~/.local/share/cairn-workbench/catalog` and
  `~/.config/cairn-workbench/`, configured in `~/.config/cairn-workbench/config.toml`.
- `cairn-garden` (`packages/gardener`): daily digests and weekly reviews drafted by your
  own Claude Code or Codex agent, with proposals you approve, Zotero sync through the
  bundled local extension, and the `kb-gardener` skill (`cairn-garden skill`). Run state,
  logs and the private note history live in `~/.local/state/cairn-workbench/garden/`.
- `cairn-garden schedule` installs the launchd jobs after both workflows pass readiness;
  `--catalog` adds a weekly `cairn-catalog update`.
- `cairn-garden migrate` moves an existing kb-gardener install and in-workspace catalog
  to this layout, with `--dry-run` and `--rollback`. It renames on one filesystem and
  copies or deletes nothing.
- `cairn-garden lint` reports anything in the knowledge base that is not a note.
- The gardener's private history now includes idea notes.
- Removed from the gardener: the upstream issue drafts (`workbench-scan`,
  `workbench-issue`).
- The Zotero extension is unchanged, so installed copies keep working.

## 0.5.0 — ideation notes

Brainstorming is saved like reading. While you develop a research idea with the agent, it
keeps an idea note, files it under topics and links it to papers.

- New `idea` notes in `ideation/`. The body is the current account, followed by dated
  `## Minutes` that Cairn only appends to. An entry that is already recorded is not added
  again.
- Ideas have a `status` (`seed`, `exploring`, `testing`, `parked`, `developed`) and a
  `next_action`. A status change needs its reason in the minutes. A save marked as a
  review cannot change the status and sets `last_review`, not `last_discussed`.
- New MCP tool `save_idea`. `search` filters by any kind and by status. `list_topics`
  counts ideas. `cairn search` takes `--kind` and `--status`, and the query is optional.
- Every save tool accepts `slug` to rename a note; the old title becomes an alias.
- Updates keep front matter, topics and aliases that are not passed again. Before, a
  field that was not resent was dropped.
- Knowledge bases without an `ideation/` folder keep working.

## 0.4.0 — minimal rewrite

Cairn is rebuilt around a single workflow. While you read a paper with Finch in Claude
Code or Codex, the agent saves a note and links it into a network of topics.

- Notes are plain Markdown in Obsidian layout (`papers/`, `topics/`, `notes/`), named by
  readable slugs. `topics:` front matter and `[[wikilinks]]` connect them.
- Five MCP tools: search, get_note, list_topics, save_reading, save_note. Saves create
  missing topics and suggest related existing ones.
- Updates require the note's current revision, so hand edits are never clobbered.
- `cairn connect` delegates to `claude mcp add` / `codex mcp add`.
- HTML pages are rendered in Python. Node and the vendored renderer are gone.
- Removed:
  - Legacy formats: workspace schemas 1–4, migration, backup/restore, undo and journals.
  - The proposal/approval workflow, policies and the auto-updater.
  - The worker adapters, release tooling, library feeds and finance/life ingest.
  - PDF capture and the JSON schemas.
  - Earlier history is in git before this release.
