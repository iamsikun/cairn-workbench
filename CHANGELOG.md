# Changelog

## Unreleased

- `fix-links` gives a paper note whose paper is in Zotero its item line,
  `- Paper: [Zotero](…) · [PDF in Zotero](…)`, after `zotero-sync` creates or finds the item.
  An existing `Paper:` line gets the item first and keeps its exact-version link; a note
  without one gets the line after its title. Notes that never had a link used to stay
  unlinked. `lint` lists the paper notes that still don't link their item
  (`unlinked_items`), and a `Paper:` item line counts as the note's own item with or without a
  list marker, as `fix-links` already read it.
- A weekly rerun no longer piles up open proposals. Once the new report is saved, every
  earlier unticked item, in this report or an older weekly, becomes `- [-] … (superseded by
  run …)`; ticked items stay as they are, and ticking a superseded item still approves it.
  The draft sees those items as `open-proposals` and restates the ones still worth doing.
  `metrics` counts open items only in each report's latest run and reports superseded ones
  separately from rejected ones, as does the Actions summary.
- `lint` no longer reports `aster.yaml`, or the file the garden workflow's `aster-config` names,
  as a foreign entry, so the weekly report stops proposing to move Aster's settings out of
  the knowledge base.
- `cairn-garden zotero-audit` lists the Zotero collections the garden filed an item in that
  none of the item's paper notes' topics justify, such as filings made before 0.8.2 because a
  topic or idea note cited the paper. It reads the run records and the creation ledger, never
  removes anything, and runs in the weekly review, which proposes each finding as a manual
  item.
- Digests and weekly reviews end with a **Run facts** section that the runner renders from the
  run's results: Zotero writes with their items, failures, gate status and pending writes,
  link repairs, lint counts, discovery status, proposal counts and warnings, plus catalog age,
  storage, HTML verification and the Zotero audit in the weekly. The drafting model writes only
  recommendations and commentary, so it can no longer leave out or deny what the run verified.
- A draft that fails validation, for example with a wikilink to a note that doesn't exist, is
  redone once with the reason in the prompt, instead of failing the run until the next
  scheduled trigger. The run records the rejection as a warning.
- `cairn-garden migrate` renames kb-gardener's old `config.toml` to `config.toml.migrated`
  once its settings are in cairn-workbench's config file (rollback restores it). The Zotero
  extension's credential stays in `~/.config/kb-gardener/`, where the installed extension reads
  it.
- `cairn-garden health` and `readiness` warn when the installed cairn packages differ from the
  release the knowledge base's own garden workflow (`.github/workflows/`) pins, and list both.
- A running `cairn mcp` server checks the installed Cairn version once a minute; after an
  upgrade its tool results carry a note that a newer version is installed and the client needs
  a restart. Results are otherwise unchanged.
- `cairn-catalog <command> -h` prints that command's usage. `browser`, `update` and the other
  commands without their own options used to ignore `-h` and run, which for `browser` meant a
  full page rebuild. Unknown options are now refused.
- The Mac's journal catalog can be kept fresh for a knowledge base gardened on GitHub Actions:
  `cairn-garden schedule --catalog --only` installs just the Monday catalog refresh, without
  local gardening or its readiness check. It runs `cairn-catalog update --keep-notes`, which
  leaves the catalog notes' status block to the cloud refresh. The catalog pages' footer shows
  the edition's age and turns to the warning colour after a week. Rebuild the pages once
  (`cairn-catalog browser`, or the next update) to see it.
- The caller template and the Actions guide say that GitHub's cron is best-effort: the hourly
  triggers are the earliest a period can run, and in practice digests land mid-morning to early
  afternoon in Chicago. Regenerate the caller (`cairn-garden ci template`) to get the comment.
- The Studio's **In KB** mark also matches catalog papers without a DOI, such as JMLR
  articles, by their page on the publisher's site: a note's `source` or `url`, with either
  scheme and with or without `www.`.

## 0.8.4 — Cairn Studio

A new optional package, `cairn-studio`: a local, read-only app for browsing the knowledge
base, built phone-first as the first step toward a phone app. It also serves the journal
catalog, marking papers already in the knowledge base. The MCP tools and the note format are
unchanged. (0.8.3 was not released separately; its changes are here.)

- `cairn-studio serve --open` serves the app on 127.0.0.1. It has Recent, a Map of every
  note as an interactive network, an Ideas board by status, Search, and a page for every note:
  topic trails, backlinks and papers that share topics. An idea's page shows its current
  account beside its minutes as a timeline marked by attribution and status changes.
- Views refresh while an agent saves, over server-sent events.
- The server reads through `cairn.store` and never writes. It answers only requests
  addressed to localhost and serves pages under a strict Content Security Policy. The
  frontend has no build step and no third-party code.
- `packages/studio/ROADMAP.md` lays out the steps from here to a phone app.
- With `cairn-catalog` installed (`cairn-studio[catalog]`), the Studio serves the catalog's
  pages, API and preference saves under `/catalog/`, so `cairn-catalog serve` is no longer
  needed day to day. Catalog papers with a paper note in the collection are marked **In KB**,
  matched by DOI or arXiv id, and link to the note. The catalog's data stays in its own
  folder; its database and raw evidence are not served.
- The catalog pages call their API by relative URL. Rebuild them once (`cairn-catalog
  browser`, or the next `cairn-catalog update`) so they work inside the Studio.

## 0.8.2 — file papers by their own notes

Zotero filing follows what a paper is about: only a paper's own note decides its collections.
The MCP tools and the note format are unchanged.

- `zotero-sync` files a paper only under the topics of its own paper note. A topic, idea or
  other note that cites a paper no longer creates it in Zotero or adds it to that note's
  collections: discussing basic concepts while reading a paper does not make the paper belong
  to that topic. Papers cited without a paper note of their own are listed under
  `cited_without_note` and nothing is written for them. Items already filed by the old rule
  are not removed.

## 0.8.1 — unattended gardening fixes

Fixes for scheduled gardening: Zotero writes stay on across upgrades, a report that shows
wikilink syntax in code no longer aborts the daily run, and the Actions workflow leaves Node 20.
The MCP tools and the note format are unchanged.

- Scheduled Zotero writes, once enabled for a library, stay on across upgrades. A change to
  the Zotero write code or the configuration is a warning, and the next scheduled run that
  writes re-verifies the gate by read-back; writes pause only if that fails or the library
  changes. Gates written by earlier releases, without a `writer` field, carry over.
  `zotero_strict_write_gate = true` keeps the old strict gate.
- The reusable `garden.yml` runs its actions on Node 24 (checkout and setup-node v7, cache v6,
  upload-artifact v7, setup-uv 10.3.0 without its unused cache) on a pinned `ubuntu-24.04`
  runner instead of `ubuntu-latest`.
- A garden report may show `[[...]]` inside inline code or a code block; only real links are
  checked. A report that links to a missing note names the missing slugs.
- `cairn skills install` prints each install command before its installer runs.

## 0.8.0 — one place to install the skills

Finch, Quill and Aster are installed and kept at tested versions by `cairn skills`, and the MCP
instructions connect them to the knowledge base. The skills themselves never name Cairn. The
MCP tools, the note format and the Zotero write path are unchanged.

- `cairn skills [status | install | remove | pin] [skill...]` installs Finch, Quill and Aster
  through their own installers at the versions this release pins (Finch 0.2.2, Quill 0.6.0,
  Aster 0.2.1), with their self-updates off, links kb-gardener, and reports versions and
  broken links.
- The MCP instructions connect the skills, which no longer name Cairn, to the notes: scouted
  items are checked against existing notes and saved only when picked, and drafts
  read notes as sources.
- The reusable Actions workflow accepts `aster: pinned`, the Aster release `cairn skills pin
  aster` names; tags and commits still work.
- `cairn-garden skill` also links into Copilot and opencode, keeps links owned elsewhere, and
  removes only its own. kb-gardener no longer claims "what's new", which belongs to Aster.

## 0.7.0 — Aster beside the journal catalog

The gardener can collect new papers with Aster as well as the journal catalog, so the two can
be compared before the catalog is retired. Aster is opt-in: without it, runs are unchanged, and
the Zotero write gate and configuration hash are unaffected. The Cairn core and its MCP tools
are unchanged.

- The gardener can use [Aster](https://github.com/iamsikun/aster) beside the journal catalog,
  so the two can be compared before the catalog is retired. When `aster` is installed,
  `new-papers` adds an `aster` source (papers Aster first collected since the last digest that
  match a topic term), `verify` accepts DOIs Aster collected from an index, and approved
  `paper` proposals take Aster's metadata and abstract. The weekly review warns when Aster is
  older than `aster_max_age_days` (2). Without Aster, nothing changes.
- `cairn-garden schedule --aster` adds a daily 06:45 `aster refresh`; the reusable Actions
  workflow takes `aster: <tag>` to install, cache and refresh Aster before each run.

## 0.6.3 — local Git sync and steadier cloud gardening

The gardener gains an optional Mac sync for a KB gardened on GitHub Actions, and fixes
found in the first days of cloud runs. The Cairn core and its MCP tools are unchanged.

- Optional local Git sync is part of the gardener setup: `cairn-garden sync setup`
  installs a macOS job that syncs at 07:15 and 13:15 by default (`--at`, repeatable), with
  wake-from-sleep catch-up, manual runs, status, rotating logs and removal. The afternoon
  time pulls the day's cloud digest, which GitHub often starts hours late.
- A sync time deferred by a busy gardener or a network failure is retried hourly, instead
  of waiting for the next day. A Cairn save in progress is waited for, not skipped.
- Setup refuses to schedule a `uv run` project environment, which would run whatever
  branch that checkout has open; the gardener's own `schedule` does the same.
- Sync snapshots local edits, merges remote changes and pushes without force. It
  protects staged work, coordinates with note/gardener writers, preflights conflicts
  and retries a racing cloud commit. Remote settings are pinned per checkout.
- `sync setup --dry-run` previews setup without writes or network calls.
  `--replace-plist` retires a selected custom scheduler without deleting its files.
- The scheduled Zotero write gate follows the Zotero write code, not the whole release.
  Before, every upgrade, including 0.6.2 itself, silently turned scheduled writes back into
  dry runs until a manual daily and weekly each wrote to Zotero again. One re-verification
  is still needed after this release, since earlier gates did not record the write code.
- Writes that were enabled and are now paused say so, with the reason, in the run warnings
  and as an annotation on the GitHub Actions run page.
- The GitHub Actions template triggers hourly from 12:43 to 20:43 UTC. With five triggers a
  day, GitHub's dropped and delayed schedules put the daily digest three to five hours late.
  Regenerate the KB's caller with `cairn-garden ci template` when upgrading.
- A completed run records its own "Latest scheduled checks" line in `gardening/index.md`.
  Before, the next trigger rewrote it, which cost each run a second cloud commit and the Mac
  an extra merge.

## 0.6.2 — fixes for unattended gardening

Fixes found while running the gardener on GitHub-hosted runners. The Cairn core and its MCP
tools are unchanged.

- Hosted runners (#4):
  - A catalog refresh starts from an empty runner.
  - The workflow reserves disk space for the full catalog and passes `OPENALEX_API_KEY`.
  - Gate activation installs the agent CLI.
  - Publication rebases with a bot identity.
  - Run diagnostics keep a recovery copy of the reports and state.
  - Catalog status links to durable run pages.
- Archived digests keep working links. Archiving moved a digest one folder deeper without
  rewriting its relative links, so the weekly review failed once a digest was archived.
- The scheduled Zotero write gate stays open after the verified run's digest is archived.
  Before, scheduled syncs silently became read-only about two weeks after writes were enabled.
- Notes whose file names are not plain ASCII, such as accented paper titles, are published.
  Before, publication failed and the run's state never advanced.
- A paper whose metadata cannot be verified, such as a DataCite DOI or a paper during a
  Crossref outage, is still never created in Zotero. It is now a warning (`unverified`)
  instead of failing the whole run.
- Catalog fixes:
  - A JMLR or RePEc outage is a warning and no longer discards the rest of a catalog refresh.
  - `Retry-After` given as an HTTP date is honoured.
- On Actions, the catalog is refreshed on every weekly review, not every other one, and a
  refreshed catalog is cached even when a later step fails. `cairn-garden ci catalog-fresh`
  takes `--max-age`.
- Temporary files inside the report folder are not taken for reports.

A new release reopens the readiness and Zotero write gates. Run daily and weekly once, then
`enable-zotero-writes`.

## 0.6.1 — gardening reports and unattended runs

Garden reports move out of the research notes into their own folder. The gardener can run on
GitHub-hosted runners for a knowledge base kept in a private GitHub repository. The Cairn core
and its MCP tools are unchanged.

- Daily digests and weekly reviews are saved in `<workspace>/gardening/` (`daily/`,
  `weekly/`, `maintenance/`, `archive/`) instead of `research/notes/`.
  - Cairn's search, topics and metrics no longer see them.
  - Their links to notes are relative Markdown links that work on GitHub and in Obsidian.
  - The folder is set with `[garden] reports`.
- `gardening/index.md` lists every run: outcome, findings, report link and run id. A failed or
  skipped run never looks like a delivered report, and a check that found nothing due is
  listed once per mode.
- `cairn-garden migrate-reports` moves existing reports, with `--dry-run`, a journal, resume
  after an interruption, a refusal when a destination conflicts, and `--rollback`. Daily and
  weekly runs refuse to start until reports have been moved.
- Reports are recognized by slug and title. A research note such as "Garden design" is no
  longer skipped by lint, metrics or Zotero sync.
- Apply, proposal metrics, digest archiving, lint and the private history all use the report
  folder. Readiness and the Zotero write gate find migrated reports.
- With `zotero_backend = "web"`, the gardener uses the Zotero Web API for reads and writes, and
  no Zotero app is needed.
  - Writes are read back.
  - Throttling is waited out.
  - A creation whose outcome is unknown is reconciled by identifier, never duplicated.
  - The scheduled write gate accepts Web evidence tied to the key's library.
- `workspace_id` makes state and evidence independent of the checkout path.
- `cairn-garden ci` and the reusable workflow `.github/workflows/garden.yml` garden a private
  knowledge base repository on GitHub Actions:
  - state lives on a `garden-state` branch;
  - reports and state are published in one atomic push, and nothing is ever force-pushed;
  - a step summary shows execution, publication and completion;
  - `ci template` prints the thin caller workflow.
  See `packages/gardener/docs/github-actions.md`.
- The weekly review warns about a stale journal catalog (`catalog_max_age_days`), or fails with
  `catalog_required = true`.
- `cairn-garden lint` accepts a repository's `.git`, `.github`, `.gitignore`, `.gitattributes`,
  `cairn-workbench.toml` and `catalog-preferences.yaml`.
- New code and instructions mean new release and configuration hashes: run daily and weekly
  once before `readiness` and the Zotero write gate pass again. The Zotero extension is
  unchanged.

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
