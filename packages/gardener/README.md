# cairn-garden

Daily and weekly gardening for a Cairn knowledge base. Each pass checks and repairs notes,
keeps Zotero collections in step with topics, finds new papers in the journal catalog, arXiv
and Zotero, and asks your own agent (Claude Code or Codex) to write a digest or a weekly
checklist of proposals. You approve proposals by ticking them; approved actions run on the next
pass. It is optional; the Cairn core does not need it.

The agent instructions are the `kb-gardener` skill in
[`src/cairn_garden/skill/`](src/cairn_garden/skill/SKILL.md).

## Setup

```sh
uv tool install ./packages/gardener      # from the workbench checkout; provides `cairn-garden`
cairn-garden skill                       # link the skill into ~/.claude/skills and ~/.agents/skills
```

Settings live in `~/.config/cairn-workbench/config.toml`, shared with `cairn-catalog`:

```toml
workspace = "~/knowledge"
collection = "research"

[garden]
agent = "claude"                   # or "codex"; scheduled runs launch this CLI
claude_daily_model = "haiku"
claude_weekly_model = "sonnet"
timezone = "America/Chicago"
contact_email = "you@example.org"  # optional; sent to Crossref/arXiv as a polite contact
interests = []                     # extra discovery terms besides your leaf topics
zotero_user_id = 1234567           # for Zotero writes (see the local-zotero reference)
zotero_backend = "auto"            # "local" uses the bundled Zotero extension only
```

`$CAIRN_WORKSPACE`, `$CAIRN_COLLECTION` and `$CAIRN_WORKBENCH_CONFIG` override the file.

## Running

```sh
cairn-garden health          # runtime checks: workspace, agent login, git, Node, Zotero
cairn-garden daily           # a complete verified pass, saved as "Garden digest YYYY-MM-DD"
cairn-garden weekly          # saved as "Garden weekly YYYY-Www", with proposals to tick
cairn-garden apply           # run ticked proposals now
cairn-garden readiness       # both real workflows passed on this release and configuration?
cairn-garden schedule        # then install launchd jobs (macOS); --catalog adds a Monday
                             # `cairn-catalog update`; --remove uninstalls them
```

A pass completes only when its report is saved and verified, its citations come from the
gathered evidence, the note history is recorded and a run receipt is written. Engine commands
(`lint`, `fix-links`, `new-papers`, `zotero-sync`, `snapshot`, `verify`, `storage`, `html-audit`,
`metrics`, `archive-digests`, `commit`) print JSON and can be run on their own.

## Where things live

| What | Where |
|---|---|
| Notes and garden reports | the knowledge base |
| Settings | `~/.config/cairn-workbench/config.toml` |
| Run receipts, discovery ledger, Zotero write gate, locks | `~/.local/state/cairn-workbench/garden/workspaces/<name>-<hash>/` |
| Logs and the private Git history of the notes | `~/.local/state/cairn-workbench/garden/{logs,history}/` |
| Zotero extension credential | `~/.config/kb-gardener/zotero-local.json` (the extension reads this fixed path) |

`$CAIRN_GARDEN_STATE` moves the state folder. Nothing is written into the knowledge base except
notes; `cairn-garden lint` lists anything else it finds there under `foreign_entries`.

## Development

Tests run with the workbench's `uv run pytest`. They use temporary folders, a sandboxed home
directory and mocked network access; the Zotero bridge check needs Node.js.
