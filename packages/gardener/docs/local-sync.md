# Local Git sync

When GitHub Actions gardens a private KB, the Mac's checkout and the cloud checkout
need to exchange changes. The gardener package includes this as an optional setup
step; no separate script, model call or Codex automation is needed.

## Setup

Install `cairn-garden` as described in its README. The shared workbench settings must
already identify the local checkout:

```toml
# ~/.config/cairn-workbench/config.toml
workspace = "~/knowledge"
collection = "research"
```

The KB must be its own Git repository with a configured `origin` remote, a `main`
branch, at least one commit, a Git author/committer identity, and `.cairn.lock` in
its `.gitignore`. Git 2.38 or newer is required. Authenticate Git in an interactive
terminal first, using a credential helper or SSH agent; the scheduler never prompts
and does not store credentials. Notes are private if the remote repository is private.

```sh
cairn-garden sync setup --dry-run                  # preview; no writes or network calls
cairn-garden sync setup                           # enable daily sync at 07:15
cairn-garden sync status                          # settings, loaded job, latest result, log
cairn-garden sync run                             # deliberately sync now
cairn-garden sync setup --at 06:45                 # change the daily time
cairn-garden sync remove                          # unload/remove just the sync schedule
```

Setup also accepts `--remote NAME` and `--branch BRANCH`, and pins both the checkout
path and remote URL. It never initializes Git, adds remotes or installs cloud workflows.
Changing a remote or moving the checkout requires setup again. `garden-state` is
reserved for the cloud runner and cannot be selected. Scheduling requires macOS;
manual sync and setup previews also work on other Unix systems.

## Timing

The default is **once daily at 07:15 in the Mac's local timezone**, before the
gardener's default 07:30 daily period. Keep the Mac and the cloud gardener in the
same timezone, or choose `--at` accordingly. The schedule follows the Mac's timezone
and daylight-saving changes. There is no 15-minute polling or login-triggered sync.

The user must remain logged in. A `StartCalendarInterval` missed during sleep runs
after waking; multiple missed events become one run. It does not wake the Mac.
A missed event while powered off or logged out waits until the next calendar event.
See [Apple's scheduling documentation](https://developer.apple.com/library/archive/documentation/MacOSX/Conceptual/BPSystemStartup/Chapters/ScheduledJobs.html).
If the Mac wakes after the cloud gardener has started, that cloud run uses the last
pushed notes. Network failures retain local commits and retry at the next daily
event; use `sync run` for an earlier retry. A scheduled run skips if today's scheduled
sync already succeeded. An explicit `sync run` always remains available.

## What a run does

1. Under the note and gardener locks, commit local modifications/deletions to tracked
   files and new Markdown notes/reports inside the KB's collections/report folder.
2. Fetch the configured notes branch, releasing the writer locks during network waits.
3. Snapshot any further local edits and fast-forward or merge the remote history.
4. Push a fixed commit without force; retry at most three times if a cloud commit races it.

Existing Git ignore rules apply. Unexpected untracked files, pre-staged edits,
another branch, an existing Git operation, or a changed remote stop the run.
Conflicts are checked with `git merge-tree` before changing live notes; the job
records the two commit IDs and leaves both histories available for a manual merge.
No conflict is resolved automatically. Empty snapshots produce no commits.

The optional sync does not depend on agent/Zotero readiness or enable local gardening.
It does not touch the cloud `garden-state` branch, Zotero credentials or write gates.
Updating the gardener package still changes its normal release hash: reverify local
gardening/write gates as usual when upgrading.

## Files and migration

Per-KB settings, the latest run status, locks and rotating logs live under
`$CAIRN_GARDEN_STATE/workspaces/<workspace-key>/sync/` (the default state root is
`~/.local/state/cairn-workbench/garden`). These local files are excluded from the
cloud state export. Logs retain the current 1 MiB file and three older files.
The LaunchAgent is `org.cairn-workbench.sync.<workspace-key>` in
`~/Library/LaunchAgents/`. It runs the installed package through its Python
interpreter, so normal package upgrades update the code used by the job.
`sync remove` preserves settings, logs and all Git history for later inspection/manual use.

To replace a previously installed custom scheduler, select its plist explicitly:

```sh
cairn-garden sync setup --replace-plist ~/Library/LaunchAgents/old-sync.plist --dry-run
cairn-garden sync setup --replace-plist ~/Library/LaunchAgents/old-sync.plist
```

After the managed job is registered, setup unloads the old job and renames its plist
to `.plist.disabled`. Its script, configuration and logs remain available. An existing
disabled backup is never overwritten. Reinstalling the managed schedule changes
the existing job; it does not create an additional scheduler.
