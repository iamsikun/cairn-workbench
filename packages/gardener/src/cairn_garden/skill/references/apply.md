# Applying approved proposals

The user approves an item by ticking it (`- [ ]` → `- [x]`) in a weekly report,
`gardening/weekly/garden-weekly-*.md`, in any editor or by asking an agent to tick it. Reports
are plain Markdown files, not Cairn notes: edit them directly, not through the MCP tools.

1. Run `cairn-garden apply` (all weekly reports) or `cairn-garden apply garden-weekly-2026-w42` (one report). It runs every
   ticked item that carries an action comment and marks it `✅ … (applied DATE: result)`.
   Use `--dry-run` to preview.
2. Items in `needs_agent` have no action or one the engine cannot run (merges, splits, rewrites,
   memory edits). Do them by hand with `get_note` / `save_note`, following the rules in SKILL.md:
   keep the user's words, never delete a note (a merged note becomes a short pointer to its
   successor), and then edit the checklist line to `- [x] ✅ … (applied DATE: what you did)`.
3. Unticked items are left alone until the next weekly run, which restates the ones still worth
   doing and marks the rest `- [-] … (superseded by run …)`. Only the latest run's unticked items
   count as "open" in the metrics; ticking a superseded item still approves it.
4. Finish with `cairn-garden commit -m "apply: <summary>"`.

## Action comments

Place one JSON object at the end of the item line: `<!-- action: {...} -->`.

| op | Fields | Effect |
|---|---|---|
| `link` | `from`, `to`, `reason`, optional `both: true`, `reverse_reason` | Adds `- [[to]] — reason` under `## Related` in `from` (with a neutral backlink unless `reverse_reason` is supplied) |
| `retag` | `note`, `add: [topic, ...]` | Adds topics to a note (creates missing topics) |
| `topic` | `title`, `body`, `broader: [...]`, `aliases`, `seeds: [paper, ...]` | Creates the topic and a to-read note for each seed |
| `paper` | `title`, `doi` or `source` (`arxiv:ID`), `url`, `authors`, `year`, `topics`, `why` | Imports from the journal catalog when the DOI is there; otherwise creates a to-read paper note, with Aster's metadata and abstract when Aster has the DOI |

Anything else (`merge`, `split`, `archive`, `memory`) is written as `{"op":"manual", ...}` and handled by the agent.

Dry runs return executable `planned` actions separately from `needs_agent` and `invalid`; they
never mark an action applied. Each action is journaled, retries finish missing seeds and tagging,
and checklist updates merge into the latest revision without replacing concurrent edits.
