# cairn-garden

Daily and weekly gardening for a Cairn knowledge base. Each pass checks and repairs notes,
keeps Zotero collections in step with topics, finds new papers in the journal catalog, Aster,
arXiv and Zotero, and asks your own agent (Claude Code or Codex) to write a digest or a weekly
checklist of proposals. You approve proposals by ticking them; approved actions run on the next
pass. It is optional; the Cairn core does not need it.

The agent instructions are the `kb-gardener` skill in
[`src/cairn_garden/skill/`](src/cairn_garden/skill/SKILL.md).

## Setup

```sh
uv tool install ./packages/gardener      # from the workbench checkout; provides `cairn-garden`
cairn-garden skill                       # link the skill into each detected agent (also run by `cairn skills install`)
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
zotero_backend = "auto"            # "local": the bundled Zotero extension only;
                                   # "web": the Zotero Web API only, no Zotero app needed
zotero_strict_write_gate = false   # true: pause scheduled Zotero writes after any change to
                                   # the write code or configuration until re-enabled
reports = "gardening"              # the report folder, inside the workspace
workspace_id = "my-kb"             # optional; state follows this name instead of the path
catalog_max_age_days = 8           # the weekly review warns about an older catalog...
catalog_required = false           # ...or fails, when true
aster_max_age_days = 2             # the weekly review warns when Aster has not collected since
```

`$CAIRN_WORKSPACE`, `$CAIRN_COLLECTION` and `$CAIRN_WORKBENCH_CONFIG` override the file.

## Running

```sh
cairn-garden health          # runtime checks: workspace, agent login, git, Node, Zotero,
                             # and installed versions against the KB's garden workflow pin
cairn-garden daily           # a complete verified pass, saved in gardening/daily/
cairn-garden weekly          # saved in gardening/weekly/, with proposals to tick
cairn-garden apply           # run ticked proposals now
cairn-garden readiness       # both real workflows passed on this release and configuration?
cairn-garden schedule        # then install launchd jobs (macOS); --catalog adds a Monday
                             # `cairn-catalog update`, --aster a daily 06:45 `aster refresh`;
                             # --only installs just those, without local gardening;
                             # --remove uninstalls them
```

**Aster.** When the [Aster](https://github.com/iamsikun/aster) command is installed (`aster` on
`PATH`, or `$CAIRN_ASTER`; `cairn skills install aster` installs the pinned release),
`new-papers` also asks it for papers first collected since the last
digest whose title or abstract contains a topic term, `verify` accepts a DOI that Aster collected
from an index, and an approved `paper` proposal takes Aster's title, authors, venue and abstract.
Aster's own fields decide what it collects (`aster fields`). It runs beside the journal catalog,
so both can be compared before the catalog is retired. Without Aster, nothing changes.

A pass completes only when its report is saved and verified, its citations come from the
gathered evidence, the note history is recorded and a run receipt is written. Engine commands
(`lint`, `fix-links`, `new-papers`, `zotero-sync`, `snapshot`, `verify`, `storage`, `html-audit`,
`metrics`, `archive-digests`, `commit`) print JSON and can be run on their own.

## Reports

Reports are operational Markdown, kept beside the research notes rather than among them, so they
never show up in Cairn's search, topics or metrics:

```text
<workspace>/
  research/papers/ topics/ ideation/ notes/     research notes (Cairn)
  gardening/
    daily/garden-digest-2026-10-14.md          daily digests
    weekly/garden-weekly-2026-w42.md           weekly reviews: tick proposals here
    maintenance/                               maintenance and verification records
    archive/daily/                             digests older than 14 days that nothing links to
    index.md                                   one row per run: outcome, findings, report, run id
```

Links between reports and notes are relative Markdown links (`../../research/papers/x.md`), which
work on GitHub and in Obsidian. `index.md` is generated: a failed or skipped run has no report
link, and the latest scheduled check that found nothing due is listed once per mode.

### Moving reports from 0.6.0

Up to 0.6.0 reports were research notes (`research/notes/garden-digest-*.md`,
`garden-weekly-*.md`). Daily and weekly runs refuse to start until they are moved:

```sh
cairn-garden migrate-reports --dry-run           # what moves where; writes nothing
cairn-garden migrate-reports                     # move them (add --maintenance SLUG for
                                                 # maintenance notes you want moved too)
cairn-garden lint                                # report_links and legacy_reports are empty
cairn-garden migrate-reports --rollback JOURNAL  # undo, with the journal path it printed
```

Only notes whose slug and title are a digest's or weekly review's move, plus digests archived in
the state folder; a note such as "Garden design" stays. Text, front matter, ticks and run markers
are kept; `[[links]]` in reports and research notes' links to reports become relative links. The
plan is journaled before the first write: an interrupted migration resumes when run again, a
second run finds nothing to do, and an existing different file at a destination stops it. Rollback
restores every file that was not edited since; edited files are reported and kept. Old run receipts
stay as they were and resolve through `report-moves.json`. Since 0.6.1 is a new release, run daily
and weekly once more before `readiness` (and the Zotero write gate) passes again.

### A clean install

```sh
uv tool install ./packages/gardener --with-executables-from cairn-catalog
cairn-garden skill
cairn-garden health
cairn-garden daily && cairn-garden weekly   # creates gardening/ with the first reports
cairn-garden readiness && cairn-garden schedule --catalog
```

## Unattended runs on GitHub Actions

A knowledge base that is its own private GitHub repository can be gardened by GitHub-hosted
runners, without a Mac, the Zotero app or a home folder: see
[docs/github-actions.md](docs/github-actions.md).

For a Mac checkout of that private KB, enable the optional scheduled Git sync during setup:

```sh
cairn-garden sync setup --dry-run
cairn-garden sync setup                 # 07:15 and 13:15 Mac local time
cairn-garden sync status
cairn-garden sync run                   # manual commit/fetch/merge/push
cairn-garden sync remove                # disable just the sync job
```

It preserves staged work, detects merge conflicts before changing live notes, keeps
rotating logs, and retries hourly after sleep, a busy gardener or a network failure. It does not enable local gardening or require
agent/Zotero readiness. See [local sync](docs/local-sync.md) for remote/time settings,
offline behavior and replacing an older custom scheduler.

## Where things live

| What | Where |
|---|---|
| Notes | the knowledge base's collection |
| Garden reports and their index | the knowledge base's `gardening/` |
| Settings | `~/.config/cairn-workbench/config.toml` |
| Run receipts, discovery ledger, Zotero write gate, locks | `~/.local/state/cairn-workbench/garden/workspaces/<name>-<hash>/` |
| Logs and the private Git history of the notes | `~/.local/state/cairn-workbench/garden/{logs,history}/` |
| Zotero extension credential | `~/.config/kb-gardener/zotero-local.json` (the extension reads this fixed path) |

`$CAIRN_GARDEN_STATE` moves the state folder. Nothing is written into the knowledge base except
notes and reports; `cairn-garden lint` lists anything else it finds there under `foreign_entries`
(a repository's `.git`, `.github`, `.gitignore`, `.gitattributes` and `cairn-workbench.toml` are
expected).

## Development

Tests run with the workbench's `uv run pytest`. They use temporary folders, a sandboxed home
directory and mocked network access; the Zotero bridge check needs Node.js.
