# Local Git sync

When GitHub Actions gardens a private KB, the Mac's checkout and the cloud checkout
need to exchange changes. The gardener package includes this as an optional setup
step; no separate script, model call or Codex automation is needed. Notes reach GitHub
a few minutes after you stop editing (quick sync), and two daily times also pull the
cloud gardener's work.

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
cairn-garden sync setup                           # quick sync, plus 07:15 and 13:15
cairn-garden sync status                          # settings, loaded jobs, latest result, log
cairn-garden sync run                             # deliberately sync now
cairn-garden sync setup --at 06:45 --at 12:45      # change the daily times
cairn-garden sync setup --quiet-minutes 5          # wait 5 minutes after the last edit
cairn-garden sync setup --no-quick                 # daily times only; removes quick sync
cairn-garden sync remove                          # unload/remove both sync jobs
```

Re-running setup changes the installed jobs in place, so an existing installation gains
quick sync by running `cairn-garden sync setup` again. Every setup run writes all the
settings, so repeat any `--at` or `--quiet-minutes` you want to keep.

Setup also accepts `--remote NAME` and `--branch BRANCH`, and pins both the checkout
path and remote URL. It never initializes Git, adds remotes or installs cloud workflows.
Changing a remote or moving the checkout requires setup again. `garden-state` is
reserved for the cloud runner and cannot be selected. Scheduling requires macOS;
manual sync and setup previews also work on other Unix systems.

## Quick sync

A second job checks the KB every minute. When notes in the KB's collections or report
folder have changed, and the newest change is older than the **quiet period** (2 minutes
by default), it runs a sync. From the last save to the push takes at most the quiet
period plus about a minute. A reading session saves a note after each step; saves less
than the quiet period apart become one commit, so a session gives one commit or a few,
not one per save. It catches saves through Cairn's MCP server, the gardener's local
writes and edits made by hand in an editor.

When nothing changed, the check is local: one `git status` limited to the note folders
and one look at whether local commits are unpushed. It makes no network call, writes no
log line and keeps no process running between checks. Unpushed commits left by an
earlier failure are pushed without waiting for new edits.

A note that Cairn is writing holds `.cairn.lock`; the sync waits for it, or defers as
`busy` and tries again a minute later. A gardener run holding its locks defers the same
way, without a log line.

**Failures back off.** When a sync fails (no network, an authentication or GitHub
problem, or something that needs attention such as a conflict or an unexpected file),
quick sync waits 2, 4, 8, 16 and then 30 minutes between attempts, and returns to normal
after the next success. Local commits are always kept. The log records the first
failure, the switch to 30-minute retries, a reminder once a day while it still fails,
and the recovery; `sync status` shows the current error and the next retry time under
`last_run.backoff`.

Turn quick sync off with `cairn-garden sync setup --no-quick`, which keeps the daily
times; turn it on again with `cairn-garden sync setup`.

## Daily times

The defaults are **07:15 and 13:15 in the Mac's local timezone**. The morning sync
pushes local notes before the gardener's 07:30 daily period; the afternoon sync pulls
that day's digest, since GitHub often starts scheduled runs hours late. Keep the Mac
and the cloud gardener in the same timezone, or choose `--at` accordingly (repeat it for
several times). The schedule follows the Mac's timezone and daylight-saving changes.

The daily times remain the safety net beside quick sync, and the only times that pull
the cloud gardener's work when you have not edited anything. Each time is a slot that
must succeed once. The job also wakes hourly: if a slot was
deferred because the gardener or a note save held a lock, or failed on the network,
the next hourly check retries it; otherwise the check exits without touching Git. A
Cairn save in progress is waited for up to 30 seconds rather than skipped.

The user must remain logged in. A calendar event missed during sleep runs after
waking; multiple missed events become one run. It does not wake the Mac.
See [Apple's scheduling documentation](https://developer.apple.com/library/archive/documentation/MacOSX/Conceptual/BPSystemStartup/Chapters/ScheduledJobs.html).
If the Mac wakes after the cloud gardener has started, that cloud run uses the last
pushed notes. Network failures retain local commits. An explicit `sync run` is always
available and does not count as a scheduled slot.

Run setup from the installed tool (`uv tool install`), not with `uv run` inside a
project: the job runs the interpreter that ran setup, and setup refuses a project's
environment because the job would then follow that checkout's current branch.

## The journal catalog on the Mac

GitHub Actions refreshes only the catalog edition in its own cache. The Studio and the catalog
pages on the Mac read the Mac's edition, which nothing refreshes unless you schedule it:

```sh
cairn-garden schedule --catalog --only            # Monday 09:00: cairn-catalog update --keep-notes
cairn-garden schedule --remove                    # remove it again
```

`--only` installs that job without local gardening and needs no readiness check.
`--keep-notes` leaves the status block in the catalog notes to the cloud refresh, so the
two refreshes do not take turns rewriting it. The catalog pages show the edition's date and
age in their footer, and the home page warns when it is more than a week old.

## What a run does

1. Under the note and gardener locks, commit local modifications/deletions to tracked
   files and new Markdown notes/reports inside the KB's collections/report folder.
2. Fetch the configured notes branch, releasing the writer locks during network waits.
3. Snapshot any further local edits, then fast-forward, or place the unpushed local
   commits on top of the remote history.
4. Push a fixed commit without force; retry at most three times if a cloud commit races it.

The commit message says what changed: `reading: <title>`, `idea: <title>`, `topic:
<title>`, `note: <title>` or `report: <name>` for one note (by its `kind`, else its
folder), and `notes: <title A>, <title B> and N more` for several, with every note
listed in the message body. Titles come from the front matter, else the file name.

Unpushed commits are replayed one by one in Git's object store, as `git rebase` would,
and the checkout moves only once the result matches what a merge would give, so history
stays linear without a merge commit. A merge is kept instead when replaying cannot be
done safely: the unpushed commits include a merge, a commit conflicts when replayed on
its own (for example an edit and its revert, against a remote edit of the same lines),
or Git is older than 2.40. Pushed history is never rewritten.

Existing Git ignore rules apply. Unexpected untracked files, pre-staged edits,
another branch, an existing Git operation, or a changed remote stop the run.
Conflicts are checked with `git merge-tree` before changing live notes; the job
records the two commit IDs and leaves both histories available for a manual merge.
Conflict markers never reach the notes.
No conflict is resolved automatically. Empty snapshots produce no commits.

The optional sync does not depend on agent/Zotero readiness or enable local gardening.
It does not touch the cloud `garden-state` branch, Zotero credentials or write gates.
Updating the gardener package still changes its release hash, so local gardening
readiness needs a verified daily and weekly again. The Zotero write gate stays open; a change
to the Zotero write code is re-verified by the next scheduled write.

## Files and migration

Per-KB settings, the latest run status, locks and rotating logs live under
`$CAIRN_GARDEN_STATE/workspaces/<workspace-key>/sync/` (the default state root is
`~/.local/state/cairn-workbench/garden`). These local files are excluded from the
cloud state export. Logs retain the current 1 MiB file and three older files.
The LaunchAgents are `org.cairn-workbench.sync.<workspace-key>` (the daily
times) and `org.cairn-workbench.sync.<workspace-key>.quick` (quick sync) in
`~/Library/LaunchAgents/`. The quick job sends its own error output to `/dev/null`;
its failures are in the rotating `sync.log`. It runs the installed package through its Python
interpreter, so normal package upgrades update the code used by the job.
`sync remove` unloads and removes both jobs; it preserves settings, logs and all Git
history for later inspection/manual use.

To replace a previously installed custom scheduler, select its plist explicitly:

```sh
cairn-garden sync setup --replace-plist ~/Library/LaunchAgents/old-sync.plist --dry-run
cairn-garden sync setup --replace-plist ~/Library/LaunchAgents/old-sync.plist
```

After the managed job is registered, setup unloads the old job and renames its plist
to `.plist.disabled`. Its script, configuration and logs remain available. An existing
disabled backup is never overwritten. Reinstalling the managed schedule changes
the existing job; it does not create an additional scheduler.
