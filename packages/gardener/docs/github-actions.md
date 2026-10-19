# Gardening on GitHub Actions

`cairn-garden` can garden a knowledge base that is its own **private** GitHub repository, on
GitHub-hosted runners. A run does not need your Mac to be on, the Zotero app, a local login or a
home folder from an earlier run.

How it fits together:

- **The workbench repository** (public) ships the reusable workflow
  [`.github/workflows/garden.yml`](../../../.github/workflows/garden.yml).
- **Your knowledge base repository** holds only two small files:
  - `.github/workflows/cairn-garden.yml`, which calls a pinned release of that workflow;
  - `cairn-workbench.toml`, the settings.
- **Each run** follows these steps:
  1. Install the pinned workbench and the agent CLI.
  2. Restore the gardener's state from the knowledge base's `garden-state` branch.
  3. Run whatever is due.
  4. Push the reports, the note changes and the new state together.

The Cairn core still never runs a model. The gardener launches the agent CLI, as it does on a
Mac.

For a Mac checkout of the same KB, add the optional
[local Git sync](local-sync.md) to the workbench setup. It commits and pushes
local edits before the daily cloud run, and pulls cloud changes into the local checkout
after it.

## What lives where

| What | Where | Durable? |
|---|---|---|
| Notes | `research/` on the default branch | Git history |
| Reports and the readable run log | `gardening/` on the default branch | Git history |
| Settings | `cairn-workbench.toml` on the default branch | Git history |
| Completed periods, delivered discoveries, the Zotero write budget and creation ledger, applied proposals, the write gate, compact run receipts | `garden/` on the `garden-state` branch | Git history of that branch, never merged |
| Journal catalog (database, snapshots, pages) | the Actions cache | Best effort; it can be rebuilt |
| Agent output, gathered evidence, logs | a run artifact | 14 days |
| Recovery copy of the collection, reports and exported state before publication | the same private run artifact | 14 days; for diagnosing and recovering a failed publish, never a substitute for the state branch |
| Credentials | repository secrets | Never written anywhere |

Correctness never depends on the cache or the artifacts. If they expire, a run rebuilds the
catalog or simply has less to read for diagnosis.

## 1. Settings

Add `cairn-workbench.toml` at the root of the knowledge base repository:

```toml
collection = "research"            # `workspace` is set by the workflow

[garden]
workspace_id = "my-kb"             # required: state follows this name, not the checkout path
agent = "claude"
claude_daily_model = "haiku"
claude_weekly_model = "sonnet"
timezone = "America/Chicago"
zotero_backend = "web"             # the Zotero Web API; no Zotero app
zotero_user_id = 1234567           # your Zotero user ID (zotero.org/settings/keys)
catalog_max_age_days = 8
catalog_required = false           # true: the weekly review fails without a fresh catalog
```

Also commit a `.gitignore` containing `.cairn.lock`.

Never commit `zotero.key` or any other credential. `cairn-garden lint` accepts these files at the
root of the knowledge base and still reports anything else:

- `.git`, `.github`, `.gitignore`, `.gitattributes`
- `cairn-workbench.toml`, `catalog-preferences.yaml`

## 2. Credentials

Add these as repository secrets (Settings → Secrets and variables → Actions):

| Secret | What | Scope |
|---|---|---|
| `CLAUDE_CODE_OAUTH_TOKEN` | Created with `claude setup-token`; uses your Claude subscription | Or use `ANTHROPIC_API_KEY` (billed per token). For `agent = "codex"`, use `CODEX_API_KEY` and set the workflow input `agent-cli: "@openai/codex"`. |
| `ZOTERO_API_KEY` | A key from zotero.org/settings/keys | Personal library: read and write access. No group or notes access. |
| `OPENALEX_API_KEY` | Optional free key from openalex.org/settings/api | Required by OpenAlex for pagination beyond the first page. Without it, OpenAlex coverage remains incomplete and the catalog reports that limitation; Crossref and publisher harvesting still run. |

Two notes on the agent and the token:

- **Agent usage:** each daily run is one agent call with the daily model, and each weekly run is
  one call with the weekly model. A not-due trigger installs nothing and calls no model.
- **Repository token:** the workflow pushes with the run's `GITHUB_TOKEN` and asks only for
  `contents: write`. If the default branch is protected, allow GitHub Actions to push to it, or
  garden a branch instead.

The gardener checks the Zotero key against `/keys/current` before writing. A key for another
library, or one without write access, is refused. Evidence records the library and the key's
user, never the key itself.

## 3. The caller workflow

```sh
cairn-garden ci template > .github/workflows/cairn-garden.yml
```

The template is pinned to the installed release, both in `uses:` and in `version:`. Keep the two
equal when you upgrade.

**Triggers.** It runs hourly from 12:43 to 20:43 UTC every day, off the busy top and half of
the hour. GitHub often starts scheduled runs hours late or drops them, so the hourly triggers
are mostly catch-ups; one with nothing due takes seconds. In both Central Standard and
Central Daylight Time this includes:

- a trigger after 07:30 for the daily digest;
- on Mondays, a trigger after 10:30 for the weekly review;
- later triggers that catch up when GitHub delays or drops a scheduled run.

The runner itself decides what is due, in your configured timezone, exactly as `--scheduled`
does on a Mac:

- A trigger that finds nothing due records that once in `gardening/index.md`. It calls no
  model.
- A period that completed is never run twice.
- A missed Monday is caught up later in the week.

**Concurrency.** All runs share one concurrency group with `cancel-in-progress: false`. Two runs
never change the knowledge base or its state at the same time, and a run that may be writing
to Zotero is never cancelled for a newer one.

**The weekly review and the catalog.** The weekly review first restores the catalog from the
Actions cache. Unless the catalog was refreshed within the last six days (earlier in this weekly
cycle), it runs `cairn-catalog update`, so every review reads a catalog refreshed that week. The
refreshed catalog is cached after the review, so its storage cleanup is retained by the next
runner rather than restoring old recovery editions. It is cached even when the review fails. The
review also checks freshness itself:

- a stale catalog is a warning in the report and the run log;
- with `catalog_required = true`, a stale catalog fails the run;
- a missing catalog is reported as an unavailable source.

The generated status block in existing catalog notes links to the GitHub run for cloud
refreshes. Temporary runner paths are not useful after the job exits. Local refreshes retain
their local catalog links, and either mode preserves note content outside that status block.

**Aster.** Set `aster: pinned` in the caller's `with:` block to collect with
[Aster](https://github.com/iamsikun/aster) as well, at the release the workbench `version`
pins (`cairn skills pin aster`), the same one `cairn skills install` puts on a Mac. A tag or
commit instead installs that one. Every run that has a period due installs it, restores Aster's data log from the Actions cache, runs `aster refresh` and caches
the log again, before the digest or review reads it. Aster's settings are `aster.yaml` in the
knowledge base repository (`aster-config` names another file); without it, Aster's default
fields apply. A failed refresh is a warning, not a failure. Aster's data is a small log, so
it needs neither the disk space nor the priming run of the catalog. If the cache is evicted,
the next refresh starts again from the past week.

**First catalog build.** The first build downloads the full public catalog and is bounded by
the job's 240-minute timeout. Run `mode: catalog` manually once to prime the cache. Caches
unused for seven days are evicted. The weekly refresh normally keeps the cache alive; otherwise
the next refresh rebuilds it.

The full catalog includes hundreds of thousands of exported notes and offline browser assets.
Before restoring or building it, the workflow removes unused Android, .NET, Swift, Haskell and
CodeQL SDKs from its disposable GitHub-hosted Ubuntu runner and requires 30 GiB of free space.
Node, Python, Git and the knowledge base are retained. Do not copy this cleanup step to a
self-hosted runner.

## 4. Publication and your own edits

`cairn-garden ci publish` commits only changes inside the collection and `gardening/`, as the
`cairn-garden` bot. Anything else in the checkout stops publication. The commit and the new
state are pushed in **one atomic push**: either both arrive or neither does.

- **You pushed while it ran.** The gardener rebases its commit on yours and pushes again. It
  never force-pushes.
- **Both changed the same lines** (say, you edited the digest the run was appending to). The
  gardener pushes its commit to a `garden/<run-id>` branch, does not advance the state, and
  fails the job. The period stays due, so the next trigger runs it again on top of your
  version. Delete the side branch once you have taken what you want from it.
- **The push failed for any other reason.** The job fails and the summary says
  "NOT published". Nothing is presented as delivered.

The workflow supplies a bot Git identity for rebases as well as the initial commits. Before
publication it saves the collection, reports and the supported state export in the private
diagnostic artifact. This preserves the actual receipts and write ledger if publication fails;
keep these files intact when recovering, rather than rebuilding verification flags by hand.

On your own machine, `git pull --rebase` before editing and push soon after. Ticking a proposal
is an ordinary edit to `gardening/weekly/…`; the next weekly run applies it.

## 5. Interruptions and what happens next

| Interrupted | Next run |
|---|---|
| Before publication: report, notes and state are lost together | The period is still due and runs again. Zotero writes already made are found by identifier and not repeated. Collection additions are idempotent. Proposals approved meanwhile are applied again, correctly, because their effects were not published either. The daily write budget may undercount that one lost run. |
| Mid-POST to Zotero, with the outcome unknown | The receipt stays pending. If the item appears in the library, it is confirmed. A new attempt (with a new write token) happens only after 12 hours, and only if the whole library still lacks the identifier. |
| Zotero throttled the run (HTTP 429 or 503) | `Retry-After` and `Backoff` are honoured for a bounded time; then the step fails and the work stays pending. |
| The state branch is missing | `restore` fails. Only the very first run may start empty (`allow-empty-state`). |
| The state branch is corrupt | `restore` fails. Restore an earlier commit of `garden-state`, which is a deliberate, manual non-fast-forward push. Or start empty: discovery, the budget and the write gate start over, and Zotero identities still prevent duplicates. |

The step summary of every run shows three things separately: execution (per mode, with warnings
and errors), publication, and overall completion. It also shows the pending approvals in the
latest weekly review. The readable history is `gardening/index.md`.

## 6. Rollout

Use a disposable private repository and a test Zotero library first, then repeat for the real
ones.

1. **Back up** your knowledge base. Run `cairn-garden migrate-reports` locally if it still has
   0.6.0-style reports. Push it to a new private repository with `cairn-workbench.toml`,
   `.gitignore` and the caller workflow.
2. **Retire the Mac schedule first:** run `cairn-garden schedule --remove`. Two schedulers must
   never run against the same library: they keep separate state.
3. **Add the secrets.** Then run the workflow manually with `mode: daily`, `scheduled: false`
   and `allow-empty-state: true`. That flag is for the first run only.
4. **Run `mode: weekly` manually** with `scheduled: false`.
5. **Run `mode: enable-zotero-writes`** once a daily and a weekly run have each created an item
   and added an item to a collection, both verified by read-back. Until then, scheduled runs
   sync Zotero read-only. Once enabled, writes stay on across upgrades: every write is still
   checked against the key's library and write access and read back. After a change to the
   Zotero write code or the configuration, the run warns, and its writes re-verify the gate;
   if they fail to verify, or the library changes, writes pause. Set
   `zotero_strict_write_gate = true` to close the gate on any such change instead. A paused
   gate is reported as "Scheduled Zotero writes are paused", with the reason, in the run's
   warnings, its step summary and an annotation on the run page.
6. **Let the schedule run.** Check `gardening/index.md` and the step summaries for a few days.

To go back to the Mac:

1. Disable the workflow.
2. Pull the repository.
3. Note that the gardener's local state does not follow automatically.
4. Run daily and weekly by hand, then `cairn-garden schedule`.
