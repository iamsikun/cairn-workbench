"""Local Git synchronization for a knowledge base: quick sync after edits, and daily slots."""

from __future__ import annotations

import argparse
import contextlib
import datetime
import fcntl
import json
import logging
import logging.handlers
import math
import os
import re
import subprocess
import time
from pathlib import Path

from . import engine as g


class SyncError(Exception):
    """A sync cannot proceed without losing or publishing unintended work."""


class Busy(SyncError):
    """Another writer owns a lock; defer without changing its files."""


# Quick sync pushes once edits have been quiet this long (seconds); settings may change it.
QUIET_SECONDS = 120
# Wait after each consecutive failure, in seconds; the last value repeats.
BACKOFF = (120, 240, 480, 960, 1800)
# While a sync keeps failing, repeat the failure in the log at most this often.
REMINDER_SECONDS = 86400
# Commit message labels by note kind, in the order a message lists them.
LABELS = {"paper": "reading", "idea": "idea", "note": "note", "topic": "topic"}
ORDER = ("reading", "idea", "note", "topic", "report", "file")


def timestamp(at=None):
    moment = datetime.datetime.now(datetime.UTC) if at is None else at
    return moment.astimezone(datetime.UTC).isoformat(timespec="seconds")


def epoch(value):
    return datetime.datetime.fromisoformat(value).timestamp()


def short(title, limit=72):
    title = " ".join(str(title).split())
    return title if len(title) <= limit else title[: limit - 1].rstrip() + "…"


def state_dir(cfg):
    # Separate from cloud state: ci export/import never carries local sync settings.
    return g.workspace_state(cfg) / "sync"


def settings(cfg):
    path = state_dir(cfg) / "settings.json"
    if not path.exists():
        raise SyncError("Run `cairn-garden sync setup --dry-run`, then `sync setup` first")
    value = json.loads(path.read_text())
    if Path(value["workspace"]).resolve() != g.workspace(cfg).resolve():
        raise SyncError("Sync settings belong to a different checkout; run sync setup again")
    return value


def times(config):
    """Daily sync times; settings from before multiple times hold one `daily_time`."""
    return sorted(config.get("times") or [config["daily_time"]])


@contextlib.contextmanager
def lock(path, wait=0.0):
    deadline = time.monotonic() + wait
    with path.open("a") as handle:
        while True:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise Busy("Another process holds " + str(path)) from None
                time.sleep(0.2)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


class Sync:
    # A Cairn save holds the note lock for moments; wait for it rather than skip a sync.
    NOTE_LOCK_WAIT = 30.0

    def __init__(self, config, logger=None):
        self.config = config
        self.repo = Path(config["workspace"]).resolve()
        self.logger = logger or logging.getLogger(__name__)
        self.remote = config.get("remote", "origin")
        self.branch = config.get("branch", "main")
        self.target = f"refs/remotes/{self.remote}/{self.branch}"
        self.env = dict(os.environ)
        # Background jobs must fail instead of waiting for an interactive login/editor.
        self.env.update(
            GIT_TERMINAL_PROMPT="0",
            GCM_INTERACTIVE="never",
            GIT_ASKPASS="/usr/bin/false",
            SSH_ASKPASS="/usr/bin/false",
            GIT_SSH_COMMAND="ssh -oBatchMode=yes -oConnectTimeout=20",
            GIT_EDITOR="true",
            GIT_MERGE_AUTOEDIT="no",
        )
        # An inherited Git override must never redirect the scheduler's writes.
        for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR"):
            self.env.pop(key, None)
        self.created = []

    def git(self, *args, check=True, timeout=60, input=None, env=None):
        try:
            result = subprocess.run(
                ["git", "-C", str(self.repo), *args],
                env={**self.env, **(env or {})},
                input=input,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="surrogateescape",
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            raise SyncError(f"Git {args[0]} timed out; next scheduled run will retry") from None
        if check and result.returncode:
            raise SyncError(f"git {args[0]}: {(result.stderr or result.stdout).strip()[-3000:]}")
        return result

    def output(self, *args, **kwargs):
        return self.git(*args, **kwargs).stdout.strip()

    def validate(self):
        if Path(self.output("rev-parse", "--show-toplevel")).resolve() != self.repo:
            raise SyncError("Configured workspace is not the repository root")
        if self.output("symbolic-ref", "--quiet", "--short", "HEAD") != self.branch:
            raise SyncError(f"Checkout is not on {self.branch}; switch back to resume sync")
        if self.branch == "garden-state":
            raise SyncError("garden-state belongs to the cloud runner; sync the notes branch")
        if self.output("remote", "get-url", self.remote) != self.config["expected_remote_url"]:
            raise SyncError("Fetch remote differs from the configured repository")
        push_urls = self.output("remote", "get-url", "--push", "--all", self.remote).splitlines()
        if push_urls != [self.config["expected_remote_url"]]:
            raise SyncError("Push remote differs from the configured repository")
        for name in (
            "MERGE_HEAD",
            "CHERRY_PICK_HEAD",
            "REVERT_HEAD",
            "rebase-merge",
            "rebase-apply",
            "sequencer",
            "index.lock",
        ):
            path = Path(self.output("rev-parse", "--git-path", name))
            if not path.is_absolute():
                path = self.repo / path
            if path.exists():
                raise SyncError("Existing Git operation or lock: " + name)
        if self.output("ls-files", "--unmerged"):
            raise SyncError("Unresolved conflicts require manual attention")
        staged = self.git("diff", "--cached", "--quiet", check=False)
        if staged.returncode:
            raise SyncError("Staged changes are present; finish your commit before automatic sync")
        # Fail before staging if the user has not configured an identity.
        for role in ("GIT_AUTHOR_IDENT", "GIT_COMMITTER_IDENT"):
            self.output("var", role)

    def checkpoint(self):
        self.validate()
        untracked = [
            p
            for p in self.git("ls-files", "--others", "--exclude-standard", "-z").stdout.split("\0")
            if p
        ]
        unexpected = [
            p
            for p in untracked
            if not (
                p.startswith(tuple(self.config["note_folders"]))
                and p.endswith(".md")
                and not (self.repo / p).is_symlink()
            )
        ]
        if unexpected:
            raise SyncError("Review untracked files before sync: " + ", ".join(unexpected))
        # Existing tracked files, plus new Markdown notes/reports. Ignore rules still apply.
        self.git("add", "-u", "--", ".")
        if untracked:
            self.git("add", "--", *untracked)
        changed = self.git("diff", "--cached", "--quiet", check=False)
        if changed.returncode not in (0, 1):
            raise SyncError("Could not inspect staged snapshot")
        if changed.returncode:
            self.git("commit", "-F", "-", input=self.message())
            head = self.output("rev-parse", "HEAD")
            self.created.append(head)
            self.logger.info("Saved local changes in %s", head)

    def describe(self, status, path):
        """A staged path as (label, title): note kind and front-matter title when it has them."""
        store = g.cairn()
        parts = path.split("/")
        removed = status == "D"
        if not path.endswith(".md"):
            return "file", path + (" (removed)" if removed else "")
        meta = {}
        if not removed:
            with contextlib.suppress(OSError, UnicodeDecodeError):
                meta = store.parse(self.repo / path).meta
        kind = meta.get("kind")
        if kind not in LABELS:
            folders = {folder: name for name, folder in store.FOLDERS.items()}
            if parts[0] in store.COLLECTIONS:
                kind = folders.get(parts[1] if len(parts) > 2 else "", "note")
            elif path.startswith(tuple(self.config.get("note_folders", []))):
                kind = "report"
            else:
                kind = "file"
        title = short(meta.get("title") or Path(path).stem)
        return LABELS.get(kind, kind), title + (" (removed)" if removed else "")

    def message(self):
        """Say what changed: one note by kind and title, several by their first titles."""
        fields = self.git("diff", "--cached", "--name-status", "--no-renames", "-z").stdout
        fields = [f for f in fields.split("\0") if f]
        items = [
            self.describe(code[0], path)
            for code, path in zip(fields[::2], fields[1::2], strict=True)
        ]
        items.sort(key=lambda item: ORDER.index(item[0]) if item[0] in ORDER else len(ORDER))
        if len(items) == 1:
            return f"{items[0][0]}: {items[0][1]}\n"
        noun = "files" if all(label == "file" for label, _ in items) else "notes"
        titles = [title for _, title in items]
        if len(titles) == 2:
            subject = f"{noun}: {titles[0]} and {titles[1]}"
        else:
            subject = f"{noun}: {titles[0]}, {titles[1]} and {len(titles) - 2} more"
        lines = [f"- {label}: {title}" for label, title in items[:100]]
        if len(items) > 100:
            lines.append(f"- and {len(items) - 100} more")
        return subject + "\n\n" + "\n".join(lines) + "\n"

    def changes(self):
        """Modified, deleted and new files in the note folders, from a local status check."""
        listing = self.git(
            "--no-optional-locks",
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=all",
            "--",
            *self.config["note_folders"],
        ).stdout.split("\0")
        paths, skip = [], False
        for record in listing:
            if skip or not record:
                skip = False
                continue
            # A rename or copy record is followed by its original path.
            skip = record[0] in "RC"
            paths.append(record[3:])
        return paths

    def newest(self, paths):
        """When the newest change happened: file times, or the folder time for a deletion."""
        times = []
        for path in paths:
            target = self.repo / path
            while True:
                with contextlib.suppress(OSError):
                    times.append(target.lstat().st_mtime)
                    break
                if target == self.repo:
                    break
                target = target.parent
        return max(times, default=0.0)

    def ahead(self):
        """Whether local commits have not reached the remote branch, without a network call."""
        listed = self.git("rev-list", "-n1", f"{self.target}..HEAD", check=False)
        return listed.returncode != 0 or bool(listed.stdout.strip())

    def replay(self, merged_tree):
        """Rebase unpushed commits onto the remote branch, without touching the checkout.

        Each commit is replayed as a three-way merge in Git's object store, so a conflict
        never reaches the working tree. Returns the new head and a map of old to new commits,
        or None to keep a merge: Git older than 2.40, merge commits among the unpushed ones,
        a commit that conflicts on its own, or a result that differs from the merge.
        """
        version = re.search(r"(\d+)\.(\d+)", self.output("version"))
        if not version or tuple(map(int, version.groups())) < (2, 40):
            return None, "Git 2.40 or newer replays commits"
        base = self.output("rev-parse", self.target)
        listed = self.output("rev-list", "--reverse", "--topo-order", "--parents", f"{base}..HEAD")
        replaced = {}
        for line in listed.splitlines():
            commit, *parents = line.split()
            if len(parents) != 1:
                return None, "unpushed history contains a merge"
            tree = self.git(
                "merge-tree",
                "--write-tree",
                f"--merge-base={parents[0]}",
                base,
                commit,
                check=False,
            )
            if tree.returncode:
                return None, f"commit {commit} conflicts when replayed alone"
            tree = tree.stdout.split("\n", 1)[0].strip()
            if tree == self.output("rev-parse", base + "^{tree}"):
                replaced[commit] = None  # The remote already has this change.
                continue
            name, email, date = (
                self.git("log", "-1", "--format=%an%x00%ae%x00%aI", commit)
                .stdout.rstrip("\n")
                .split("\0")
            )
            message = self.git("log", "-1", "--format=%B", commit).stdout
            base = self.output(
                "commit-tree",
                tree,
                "-p",
                base,
                "-F",
                "-",
                input=message,
                env=dict(GIT_AUTHOR_NAME=name, GIT_AUTHOR_EMAIL=email, GIT_AUTHOR_DATE=date),
            )
            replaced[commit] = base
        if self.output("rev-parse", base + "^{tree}") != merged_tree:
            return None, "replayed result differs from the merge"
        return base, replaced

    @contextlib.contextmanager
    def writing(self):
        with contextlib.ExitStack() as stack:
            for path in self.config.get("writer_locks", []):
                stack.enter_context(lock(Path(path)))
            stack.enter_context(lock(self.repo / ".cairn.lock", self.NOTE_LOCK_WAIT))
            yield

    def integrate(self):
        with self.writing():
            # Capture notes saved during the fetch, before changing the checkout.
            self.checkpoint()
            head = self.output("rev-parse", "HEAD")
            remote_head = self.output("rev-parse", self.target)
            if (
                self.git("merge-base", "--is-ancestor", self.target, "HEAD", check=False).returncode
                == 0
            ):
                return
            ahead = self.git("merge-base", "--is-ancestor", "HEAD", self.target, check=False)
            if ahead.returncode:
                # Detect ordinary conflicts without placing conflict markers in live notes.
                preview = self.git("merge-tree", "--write-tree", "HEAD", self.target, check=False)
                if preview.returncode:
                    detail = (preview.stdout + preview.stderr).strip()[-3000:]
                    raise SyncError(
                        f"Merge needs manual attention; local {head} and remote {remote_head} "
                        f"are preserved. {detail}"
                    )
                # Unpushed commits go on top of the remote ones, so history stays linear.
                new, replaced = self.replay(preview.stdout.split("\n", 1)[0].strip())
                if new:
                    # The checkout is clean here; --keep refuses rather than overwrite a file.
                    self.git(
                        "reset",
                        "--keep",
                        new,
                        env=dict(GIT_REFLOG_ACTION=f"cairn sync: rebase onto {remote_head}"),
                    )
                    self.created = [replaced.get(c, c) for c in self.created if replaced.get(c, c)]
                    self.logger.info(
                        "Replayed %d local commits onto remote commit %s",
                        len(replaced),
                        remote_head,
                    )
                    return
                self.logger.info("Keeping a merge: %s", replaced)
            self.git("merge", "--ff", "--no-edit", "--no-stat", "--no-autostash", self.target)
            self.logger.info("Integrated remote commit %s", remote_head)

    def run(self):
        with self.writing():
            self.checkpoint()
        for attempt in range(3):
            # Fetch and push can wait on the network; never hold Cairn's note lock for them.
            self.git(
                "fetch",
                "--no-tags",
                self.remote,
                f"refs/heads/{self.branch}:{self.target}",
                timeout=90,
            )
            self.integrate()
            head = self.output("rev-parse", "HEAD")
            if head == self.output("rev-parse", self.target):
                return {"head": head, "pushed": False, "commits_created": self.created}
            # Push a fixed commit, so a concurrent manual checkout cannot change the source.
            push = self.git(
                "push",
                "--porcelain",
                self.remote,
                f"{head}:refs/heads/{self.branch}",
                check=False,
                timeout=90,
            )
            if push.returncode == 0:
                if self.output("rev-parse", self.target) != head:
                    raise SyncError("Push succeeded but tracking ref changed; retry to verify")
                return {"head": head, "pushed": True, "commits_created": self.created}
            detail = push.stdout + push.stderr
            if "[rejected]" not in detail or not any(
                word in detail for word in ("fetch first", "non-fast-forward")
            ):
                raise SyncError(
                    "Push failed; local commits are preserved: " + detail.strip()[-3000:]
                )
            self.logger.info("Remote advanced during push; retry %s/3", attempt + 1)
        raise SyncError("The remote kept advancing; retry on the next scheduled run")


def quick_due(config, status, now):
    """Why a quick tick has nothing to do, or None when it should sync. No network calls."""
    if not config.get("quick", True):
        return "quick sync is off"
    retry = (status.get("backoff") or {}).get("retry_at")
    if retry and now < epoch(retry):
        return "waiting to retry after a failure"
    worker = Sync(config)
    paths = worker.changes()
    if not paths:
        return None if worker.ahead() else "no local changes"
    age = now - worker.newest(paths)
    if 0 <= age < config.get("quiet_seconds", QUIET_SECONDS):
        return "waiting for edits to settle"
    return None


def failed(status, logger, now, error):
    """Back off after a failure; log the first, the slowest interval, then once a day."""
    backoff = status.get("backoff") or {}
    count = backoff.get("failures", 0) + 1
    delay = BACKOFF[min(count, len(BACKOFF)) - 1]
    backoff.update(failures=count, retry_at=timestamp(stamp_of(math.ceil(now + delay))))
    message = None
    if count == 1:
        backoff["since"] = timestamp(stamp_of(now))
        message = f"Sync stopped: {error}; retrying in {delay // 60} minutes"
    elif count == len(BACKOFF):
        message = (
            f"Still failing after {count} attempts; retrying every {delay // 60} minutes: {error}"
        )
    elif now - epoch(backoff.get("logged_at", backoff["since"])) >= REMINDER_SECONDS:
        message = f"Still failing since {backoff['since']} after {count} attempts: {error}"
    if message:
        backoff["logged_at"] = timestamp(stamp_of(now))
        logger.error(message)
    status["backoff"] = backoff


def stamp_of(seconds):
    return datetime.datetime.fromtimestamp(seconds, datetime.UTC)


def run(cfg, scheduled=False, stamp=None, quick=False):
    config = settings(cfg)
    config["writer_locks"] = [
        str(g.workspace_state(cfg) / f"{name}.lock") for name in ("run", "engine", "reports")
    ]
    state = state_dir(cfg)
    stamp = stamp or datetime.datetime.now().astimezone()
    now = stamp.timestamp()
    logger = logging.getLogger(__name__ + "." + g.workspace_key(cfg))
    log = None
    status_path = state / "status.json"
    try:
        with lock(state / "sync.lock"):
            # Read under the lock: another process may have just completed today's sync.
            status = g.read_json(status_path, {})
            reason = None
            if quick:
                # An idle tick ends here, after local checks only: no fetch, no log line.
                try:
                    reason = quick_due(config, status, now)
                except SyncError as error:
                    reason = str(error)
                    log = open_log(logger, state)
                    failed(status, logger, now, error)
                    status.update(status="needs_attention", error=reason, trigger="quick")
                    status["finished_at"] = timestamp()
                    g.atomic_json(status_path, status)
                    return status
            # Each daily time is one slot; hourly retries run until the latest slot succeeds.
            past = [t for t in times(config) if t <= stamp.strftime("%H:%M")]
            slot = f"{stamp.date().isoformat()}T{past[-1]}" if past else None
            if scheduled and (not slot or status.get("last_scheduled_slot") == slot):
                reason = "not due or already synchronized"
            if reason:
                return {"status": "skipped", "reason": reason}
            log = open_log(logger, state)
            trigger = "quick" if quick else "scheduled" if scheduled else "manual"
            status.update(started_at=timestamp(), status="running", trigger=trigger)
            g.atomic_json(status_path, status)
            worker = Sync(config, logger)
            try:
                result = worker.run()
                backoff = status.pop("backoff", None)
                if backoff:
                    logger.info(
                        "Recovered after %d failed attempts since %s",
                        backoff["failures"],
                        backoff["since"],
                    )
                status.update(
                    result,
                    status="success",
                    last_success_at=timestamp(),
                    last_success_day=stamp.date().isoformat(),
                    error=None,
                )
                if scheduled:
                    status["last_scheduled_slot"] = slot
                logger.info("Synchronized at %s; pushed=%s", result["head"], result["pushed"])
            except Busy as error:
                status.update(status="busy", error=str(error))
                if not quick:  # The next quick tick retries within a minute.
                    logger.info("Deferred: %s", error)
            except (SyncError, OSError) as error:
                status.update(
                    status="needs_attention", error=str(error), commits_created=worker.created
                )
                failed(status, logger, now, error)
            status["finished_at"] = timestamp()
            g.atomic_json(status_path, status)
            return status
    except Busy:
        return {"status": "busy", "reason": "another sync instance is running"}
    finally:
        if log:
            logger.removeHandler(log)
            log.close()


def open_log(logger, state):
    log = logging.handlers.RotatingFileHandler(
        state / "sync.log", maxBytes=1024 * 1024, backupCount=3
    )
    log.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(log)
    logger.setLevel(logging.INFO)
    return log


def main(argv=None):
    from . import sync_schedule

    parser = argparse.ArgumentParser(prog="cairn-garden sync", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    setup = sub.add_parser("setup", help="configure and enable quick and daily macOS sync")
    setup.add_argument("--remote", default="origin")
    setup.add_argument("--branch", default="main")
    setup.add_argument(
        "--at",
        action="append",
        metavar="HH:MM",
        help="daily Mac local time; repeat for several (default: 07:15 and 13:15)",
    )
    setup.add_argument(
        "--quiet-minutes",
        type=float,
        default=QUIET_SECONDS / 60,
        metavar="N",
        help="quick sync pushes after N minutes without edits (default: 2)",
    )
    setup.add_argument(
        "--no-quick", action="store_true", help="keep only the daily times; no quick sync"
    )
    setup.add_argument("--dry-run", action="store_true")
    setup.add_argument(
        "--replace-plist", type=Path, help="retire an explicitly selected old sync job"
    )
    once = sub.add_parser("run", help="commit, fetch, merge and push once")
    once.add_argument("--scheduled", action="store_true", help="run only if a sync time is due")
    once.add_argument(
        "--quick", action="store_true", help="run only if notes changed and edits have settled"
    )
    sub.add_parser("status", help="show settings, schedule and latest run")
    sub.add_parser("remove", help="disable quick and daily sync; preserve settings and history")
    args = parser.parse_args(argv)
    try:
        cfg = g.config()
        if args.command == "setup":
            result = sync_schedule.install(
                cfg,
                args.remote,
                args.branch,
                args.at or sync_schedule.DEFAULT_TIMES,
                args.dry_run,
                args.replace_plist,
                quick=not args.no_quick,
                quiet=round(args.quiet_minutes * 60),
            )
        elif args.command == "remove":
            result = sync_schedule.remove(cfg)
        elif args.command == "status":
            result = sync_schedule.status(cfg)
        else:
            result = run(cfg, args.scheduled, quick=args.quick)
    except (SyncError, OSError, ValueError, subprocess.SubprocessError) as error:
        result = {"status": "needs_attention", "error": str(error)}
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    return 1 if result.get("status") == "needs_attention" else 0


if __name__ == "__main__":
    raise SystemExit(main())
