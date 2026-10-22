---
name: kb-gardener
description: Maintain and grow the user's Cairn research knowledge base on a daily or weekly cadence. Use when asked to garden, tidy, audit, organize or self-improve the knowledge base; to run the daily digest of new papers or the weekly review; to find missing papers, links, ideas or new topics worth reading; to fix note links that point to local files or sync notes with Zotero collections; to prune old catalog snapshots or optimize storage, memory or the HTML catalog views; or to apply approved garden proposals ("apply garden proposals"). Also used by the scheduled kb-gardener runs.
license: MIT
metadata:
  author: Sikun Xu
  version: "0.8.4"
---

# kb-gardener: keeping the knowledge base organized and growing

The Cairn knowledge base (the `workspace` and `collection` in `~/.config/cairn-workbench/config.toml`)
holds paper, topic, idea and other notes, connected by `[[slug]]` links and `topics:` front matter. This skill
improves it in a loop: **checks and fixes** (mechanical), **proposals** (judgment, approved by the
user), and **metrics** (to see whether the changes helped).

## Modes

Pick the mode from the request; scheduled runs name it explicitly.

| Mode | When | Read |
|---|---|---|
| `daily` | Every morning, or "daily digest" | [references/daily.md](references/daily.md) |
| `weekly` | Monday, or "weekly review", "garden the KB", "find gaps", "new topics" | [references/weekly.md](references/weekly.md) |
| `apply` | "apply garden proposals", or the start of a weekly run | [references/apply.md](references/apply.md) |

Always also read [references/link-policy.md](references/link-policy.md) and
[references/note-formats.md](references/note-formats.md) before writing a note.

## Verified workflows

Use `cairn-garden daily|weekly` to execute a full pass. Use `cairn-garden health` for runtime
checks and `cairn-garden readiness` to confirm both real-agent workflows passed on the installed
release and configuration. `cairn-garden schedule` refuses to enable schedules until that check
passes; `cairn-garden skill` links this skill without enabling them. Completion requires a saved report,
validated citations, history commits and a durable run receipt. `mark` cannot bypass those checks.
Runs use a kernel-owned lock, released on process exit.

Schedules check every 15 minutes and catch up after sleep: daily after 07:30 and weekly Monday
after 10:30 in the configured timezone (default America/Chicago). Successful periods are not rerun.
Readable reports and their log live in the workspace's `gardening/` folder, beside (not inside)
the research collection. Run evidence, logs and the private Git history of the notes live in the
gardener's state folder (`~/.local/state/cairn-workbench/garden/`), never in the workspace.
Unattended runs on GitHub Actions keep that state on the knowledge base's `garden-state` branch
(`cairn-garden ci`). Source outages are warnings with retained checkpoints; agent,
persistence, history or missing-asset failures prevent completion. Local Zotero writes use the authenticated desktop extension described in
[references/local-zotero.md](references/local-zotero.md). Scheduled writes require separate real
import and collection-update evidence from both workflows on this exact release/configuration.
Until enabled, scheduled sync stays read-only. A failed write or read-back prevents completion;
a closed Zotero app leaves local write workflows pending for the next scheduled attempt.

## Tools

The engine is the `cairn-garden` command (package `cairn-garden` in cairn-workbench). Run
`cairn-garden <command>` from any directory; every command prints JSON.

| Command | Purpose |
|---|---|
| `lint` | Broken links, orphans, empty topics, incomplete papers, paper notes that do not link their Zotero item (`unlinked_items`), forbidden local references, reading positions, broken report links, reports still among the research notes (`legacy_reports`), and anything in the workspace that is not a note or report (`foreign_entries`) |
| `zotero-sync [--dry-run]` | File each paper that has its own paper note into the Zotero collections of that note's topics, never because another note cites it; create verified missing items (local extension or explicitly selected Web API); list papers cited without a note under `cited_without_note` |
| `fix-links [--dry-run]` | Point papers that are in Zotero to their Zotero item and PDF, and give each paper note whose paper is in Zotero its `Paper:` item line; replace local file references |
| `new-papers [--record]` | New papers from the journal catalog, Aster, arXiv and Zotero, pre-filtered by the user's topics |
| `zotero-gaps` | Papers in Zotero collections linked from topic notes that have no Cairn note |
| `zotero-audit` | Collections the garden filed items in that no paper note's own topics justify, such as filings made by citation before 0.8.2 (read-only) |
| `snapshot [--days 7]` | Compact map of all notes, links, backlinks, headings, recent changes |
| `verify --doi X / --arxiv X / --title X` | Confirm that a paper exists before recommending it |
| `storage [--apply]` | Prune old catalog snapshots (keeps the newest successful edition) and optimize SQLite |
| `html-audit [--verify]` | Sizes and staleness of the catalog HTML views and asset bundles |
| `metrics [--dry-run]` | Record health metrics; shows last week's for comparison |
| `apply [note] [--dry-run]` | Run ticked proposals that carry an action |
| `archive-digests` | Move unreferenced daily digests older than 14 days to `gardening/archive/` |
| `migrate-reports [--dry-run]` | Move reports saved as research notes by 0.6.0 into `gardening/` |
| `commit -m MSG` | Record note changes in the private history (in the state folder) |

For a KB gardened on GitHub Actions, optional `cairn-garden sync setup --dry-run`
previews the Mac's Git sync. `sync setup` enables it at 07:15 and 13:15 Mac local time;
`sync run`, `sync status` and `sync remove` run, inspect and disable it. It commits
local edits, fetches/merges the notes branch and pushes, preserving both histories
on conflicts. It is separate from local gardening schedules and cloud `garden-state`.

For reading and writing notes, prefer the Cairn MCP tools when they are connected (`search`,
`get_note`, `list_topics`, `save_note`, `save_reading`). Updating a note needs its current
`revision` from `get_note`; on a rejected save, get the note again, merge and retry.

## Rules

- **Zotero first, never local files.** A paper that is in Zotero is referenced by its Zotero item
  (`zotero://select/library/items/KEY`) and PDF, not by a web URL. A paper not yet in Zotero uses
  its DOI/arXiv/publisher URL until `zotero-sync` adds it. Never write `/private/tmp`, `/tmp`,
  `research/resources/...`, `~/.codex/attachments` or `file://` paths into a note.
- **The workspace holds knowledge, not tools.** Besides notes it holds only the readable garden
  reports in `gardening/`. Code, skills, views, catalog data, raw evidence and run state live outside it, in cairn-workbench's packages and their data and state folders. Report
  `foreign_entries` from `lint` instead of adding to them.
- **Only verified papers.** Every paper you recommend must come from a tool result (`new-papers`,
  `zotero-gaps`, the catalog) or pass `verify`. Never cite from memory alone.
- **The user's words stay theirs.** Never rewrite, merge away or reattribute the user's own
  observations or questions. Append; do not restructure reading notes without approval.
- **Never delete a note.** Retiring, merging or splitting notes is a proposal.
- **Safe fixes apply automatically**: link repair (`fix-links`), Zotero collection sync
  (`zotero-sync`), snapshot pruning (`storage --apply`), archiving unreferenced digests. Approved link actions add explicit backlinks. Everything
  else goes into the weekly proposal checklist for the user to tick.
- **Report only what tool results confirm.** If a source was unavailable (Zotero closed, arXiv
  down), say so in the note instead of guessing.
- **Be economical.** Work from the JSON the engine returns. Open a full note only when a decision
  needs it.
- Let the verified runner save reports and acknowledge completion. Standalone maintenance commands
  do not count as a completed daily or weekly workflow.
