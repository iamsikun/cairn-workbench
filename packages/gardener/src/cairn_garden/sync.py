"""Local Git synchronization and daily scheduling for a knowledge base."""

from __future__ import annotations

import argparse
import contextlib
import datetime
import fcntl
import json
import logging
import logging.handlers
import os
import subprocess
from pathlib import Path

from . import engine as g


class SyncError(Exception):
    """A sync cannot proceed without losing or publishing unintended work."""


class Busy(SyncError):
    """Another writer owns a lock; defer without changing its files."""


def timestamp():
    return datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds")


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


@contextlib.contextmanager
def lock(path):
    with path.open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Busy("Another process holds " + str(path)) from None
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


class Sync:
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

    def git(self, *args, check=True, timeout=60):
        try:
            result = subprocess.run(
                ["git", "-C", str(self.repo), *args],
                env=self.env,
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

    def output(self, *args):
        return self.git(*args).stdout.strip()

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
            self.git("commit", "-m", f"sync: local knowledge base changes ({timestamp()}).")
            head = self.output("rev-parse", "HEAD")
            self.created.append(head)
            self.logger.info("Saved local changes in %s", head)

    @contextlib.contextmanager
    def writing(self):
        with contextlib.ExitStack() as stack:
            for path in self.config.get("writer_locks", []):
                stack.enter_context(lock(Path(path)))
            stack.enter_context(lock(self.repo / ".cairn.lock"))
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


def run(cfg, scheduled=False, stamp=None):
    config = settings(cfg)
    config["writer_locks"] = [
        str(g.workspace_state(cfg) / f"{name}.lock") for name in ("run", "engine", "reports")
    ]
    state = state_dir(cfg)
    stamp = stamp or datetime.datetime.now().astimezone()
    logger = logging.getLogger(__name__ + "." + g.workspace_key(cfg))
    log = logging.handlers.RotatingFileHandler(
        state / "sync.log", maxBytes=1024 * 1024, backupCount=3
    )
    log.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(log)
    logger.setLevel(logging.INFO)
    status_path = state / "status.json"
    try:
        with lock(state / "sync.lock"):
            # Read under the lock: another process may have just completed today's sync.
            status = g.read_json(status_path, {})
            if scheduled and (
                stamp.strftime("%H:%M") < config["daily_time"]
                or status.get("last_scheduled_day") == stamp.date().isoformat()
            ):
                return {"status": "skipped", "reason": "not due or already synchronized today"}
            status.update(started_at=timestamp(), status="running")
            g.atomic_json(status_path, status)
            worker = Sync(config, logger)
            try:
                result = worker.run()
                status.update(
                    result,
                    status="success",
                    last_success_at=timestamp(),
                    last_success_day=stamp.date().isoformat(),
                    error=None,
                )
                if scheduled:
                    status["last_scheduled_day"] = stamp.date().isoformat()
                logger.info("Synchronized at %s; pushed=%s", result["head"], result["pushed"])
            except Busy as error:
                status.update(status="busy", error=str(error))
                logger.info("Deferred: %s", error)
            except (SyncError, OSError) as error:
                status.update(
                    status="needs_attention", error=str(error), commits_created=worker.created
                )
                logger.error("Sync stopped: %s", error)
            status["finished_at"] = timestamp()
            g.atomic_json(status_path, status)
            return status
    except Busy:
        return {"status": "busy", "reason": "another sync instance is running"}
    finally:
        logger.removeHandler(log)
        log.close()


def main(argv=None):
    from . import sync_schedule

    parser = argparse.ArgumentParser(prog="cairn-garden sync", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    setup = sub.add_parser("setup", help="configure and enable the daily macOS sync")
    setup.add_argument("--remote", default="origin")
    setup.add_argument("--branch", default="main")
    setup.add_argument("--at", default="07:15", metavar="HH:MM", help="daily Mac local time")
    setup.add_argument("--dry-run", action="store_true")
    setup.add_argument(
        "--replace-plist", type=Path, help="retire an explicitly selected old sync job"
    )
    once = sub.add_parser("run", help="commit, fetch, merge and push once")
    once.add_argument("--scheduled", action="store_true", help="run only if today's sync is due")
    sub.add_parser("status", help="show settings, schedule and latest run")
    sub.add_parser("remove", help="disable the schedule; preserve settings and history")
    args = parser.parse_args(argv)
    try:
        cfg = g.config()
        if args.command == "setup":
            result = sync_schedule.install(
                cfg, args.remote, args.branch, args.at, args.dry_run, args.replace_plist
            )
        elif args.command == "remove":
            result = sync_schedule.remove(cfg)
        elif args.command == "status":
            result = sync_schedule.status(cfg)
        else:
            result = run(cfg, args.scheduled)
    except (SyncError, OSError, ValueError, subprocess.SubprocessError) as error:
        result = {"status": "needs_attention", "error": str(error)}
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    return 1 if result.get("status") == "needs_attention" else 0


if __name__ == "__main__":
    raise SystemExit(main())
