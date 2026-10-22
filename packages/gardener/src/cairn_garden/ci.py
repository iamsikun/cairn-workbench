"""Unattended gardening of a knowledge base that is its own Git repository (GitHub Actions).

A hosted runner starts empty, so the gardener's correctness-critical state travels with the
knowledge base: on a separate branch (`garden-state` by default) that ordinary history never
merges. `restore` imports it before a run; `publish` commits the run's note and report changes
and the new state, and pushes both in one atomic push, so a report is never delivered without
its state or the other way round. Nothing is force-pushed.

    cairn-garden ci restore [--branch B] [--allow-empty]
    cairn-garden ci publish [--branch B] [--target BRANCH] [--remote origin]
    cairn-garden ci due daily|weekly            exit 0 when due (and set a step output)
    cairn-garden ci catalog-fresh [--max-age D] exit 0 when the journal catalog is fresh
    cairn-garden ci summary [--mode M]          execution, publication and completion
    cairn-garden ci state-export DIR | state-import DIR [--allow-empty]
    cairn-garden ci template [--version vX.Y.Z] the caller workflow for the knowledge base
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from datetime import timedelta
from pathlib import Path

from . import __version__, reports
from . import engine as g

# Correctness-critical state: completed periods, delivered discoveries, the daily write budget
# and creation ledger, applied proposals, the write gate and report moves. Raw evidence (facts,
# agent output), logs, caches, the catalog and the private history stay behind.
STATE_FILES = (
    "state.json",
    "discoveries.json",
    "zotero-writes.json",
    "actions.json",
    "zotero-writes-enabled.json",
    "report-moves.json",
)
JOURNALS = ("metrics.jsonl",)
RECEIPTS = ("manifest.json", "report.json", "zotero-sync.json")
RECENT_DAYS = 60
FOLDER = "garden"
BOT = ["-c", "user.name=cairn-garden", "-c", "user.email=cairn-garden@users.noreply.github.com"]


class StateError(RuntimeError):
    """Durable state is missing or unreadable; a run must not start from nothing by accident."""


# State ------------------------------------------------------------------------------------------


def kept_runs(cfg) -> dict[str, bool]:
    """Run folders to keep: those state or the write gate rely on (in full), recent ones (receipt)."""
    state = g.load_state(cfg)
    gate = g.read_json(g.state_dir(cfg) / "zotero-writes-enabled.json", {})
    needed = {v for k, v in state.items() if k.startswith(("last_run_", "zotero_verified_"))}
    needed |= set((gate.get("runs") or {}).values())
    cutoff = (g.now(cfg) - timedelta(days=RECENT_DAYS)).strftime("%Y%m%dT%H%M%S")
    runs = {}
    for folder in sorted((g.state_dir(cfg) / "runs").glob("*")):
        if folder.name in needed:
            runs[folder.name] = True
        elif folder.name >= cutoff:
            runs[folder.name] = False
    return runs


def export_state(cfg, dest: Path) -> dict:
    target = Path(dest) / FOLDER
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    source = g.state_dir(cfg)
    files = []
    for name in STATE_FILES + JOURNALS:
        if (source / name).exists():
            shutil.copy2(source / name, target / name)
            files.append(name)
    for run, full in kept_runs(cfg).items():
        for name in RECEIPTS if full else RECEIPTS[:1]:
            path = source / "runs" / run / name
            if path.exists():
                (target / "runs" / run).mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target / "runs" / run / name)
                files.append(f"runs/{run}/{name}")
    g.atomic_json(
        target / "meta.json",
        {"workspace": g.workspace_identity(cfg), "version": __version__, "files": len(files)},
    )
    return {"exported": len(files), "to": str(target)}


def validate(path: Path) -> None:
    try:
        if path.suffix == ".jsonl":
            for line in path.read_text().splitlines():
                if line.strip():
                    json.loads(line)
        else:
            value = json.loads(path.read_text())
            if not isinstance(value, dict):
                raise ValueError("not a JSON object")
    except (OSError, ValueError) as error:
        raise StateError(f"durable state file {path.name} is corrupt: {error}") from None


def import_state(cfg, src: Path, allow_empty: bool = False) -> dict:
    folder = Path(src) / FOLDER
    if not (folder / "meta.json").exists():
        if allow_empty:
            return {"imported": 0, "empty": True}
        raise StateError(
            f"no garden state in {src}; pass --allow-empty only for the very first run"
        )
    paths = sorted(p for p in folder.rglob("*") if p.is_file())
    for path in paths:
        validate(path)
    meta = json.loads((folder / "meta.json").read_text())
    if meta.get("workspace") != g.workspace_identity(cfg):
        raise StateError(
            f"state belongs to {meta.get('workspace')}, not {g.workspace_identity(cfg)}"
        )
    target = g.state_dir(cfg)
    count = 0
    for path in paths:
        if path.name == "meta.json" and path.parent == folder:
            continue
        destination = target / path.relative_to(folder)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
        count += 1
    return {"imported": count, "empty": False}


# Git --------------------------------------------------------------------------------------------


def git(repo, *argv, check=True):
    result = subprocess.run(["git", "-C", str(repo), *argv], capture_output=True, text=True)
    if check and result.returncode:
        raise RuntimeError(f"git {' '.join(argv)}: {result.stderr.strip()}")
    return result


def worktree(cfg) -> Path:
    return g.HOME / "ci-state"


def restore(cfg, repo: Path, branch: str, remote: str, allow_empty: bool) -> dict:
    """Check the state branch out beside the knowledge base and import it."""
    tree = worktree(cfg)
    if tree.exists():
        git(repo, "worktree", "remove", "--force", str(tree), check=False)
        shutil.rmtree(tree, ignore_errors=True)
    git(repo, "worktree", "prune")
    fetched = git(
        repo, "fetch", remote, f"+refs/heads/{branch}:refs/remotes/{remote}/{branch}", check=False
    )
    if fetched.returncode == 0:
        git(repo, "worktree", "add", "--detach", str(tree), f"{remote}/{branch}")
    else:
        if "couldn't find remote ref" not in fetched.stderr:
            raise StateError(f"could not fetch {branch}: {fetched.stderr.strip()}")
        git(repo, "worktree", "add", "--detach", str(tree), "HEAD")
        git(tree, "checkout", "-q", "--orphan", f"{branch}-local")
        git(tree, "rm", "-rq", "--cached", ".", check=False)
        for path in tree.iterdir():
            if path.name != ".git":
                shutil.rmtree(path) if path.is_dir() else path.unlink()
    return {
        "branch": branch,
        "remote_branch": fetched.returncode == 0,
        **import_state(cfg, tree, allow_empty),
    }


def changed(repo) -> list[str]:
    """Changed paths, verbatim: -z keeps non-ASCII and spaced names unquoted."""
    entries = git(repo, "status", "--porcelain", "-z", "--untracked-files=all").stdout.split("\0")
    paths, entries = [], iter(entries)
    for entry in entries:
        if entry:
            paths.append(entry[3:])
            if "R" in entry[:2] or "C" in entry[:2]:
                paths.append(next(entries))  # the rename's source follows its target
    return paths


def publish(cfg, repo: Path, branch: str, remote: str, target: str | None, attempts=3) -> dict:
    """Commit notes, reports and state, then push them atomically; never force."""
    store = g.cairn()
    scope = [
        cfg["collection"] + "/",
        reports.root(cfg).relative_to(g.workspace(cfg)).as_posix() + "/",
    ]
    ignored = {store.MARKER, ".cairn.lock", ".DS_Store"}
    paths = [p for p in changed(repo) if Path(p).name not in ignored]
    outside = [p for p in paths if not any(p.startswith(s) for s in scope)]
    if outside:
        return {
            "published": False,
            "reason": "changes outside the gardener's scope",
            "paths": outside,
        }
    run_id = g.load_state(cfg).get("last_run_daily") or "state"
    latest = latest_runs(cfg)
    if latest:
        run_id = max(latest.values(), key=lambda m: m.get("id", ""))["id"]
    target = target or git(repo, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    if paths:
        git(repo, "add", "-A", "--", *paths)
        git(repo, *BOT, "commit", "-q", "-m", f"garden: {run_id}")
    tree = worktree(cfg)
    if not tree.exists():
        raise StateError("no state worktree: run `cairn-garden ci restore` first")
    export_state(cfg, tree)
    git(tree, "add", "-A")
    if git(tree, "diff", "--cached", "--quiet", check=False).returncode:
        git(tree, *BOT, "commit", "-q", "-m", f"garden state: {run_id}")
    state_head = git(tree, "rev-parse", "HEAD", check=False).stdout.strip()
    ahead = git(repo, "rev-list", "--count", f"{remote}/{target}..HEAD", check=False)
    if not paths and ahead.returncode == 0 and ahead.stdout.strip() == "0":
        refs = []
    else:
        refs = [f"HEAD:refs/heads/{target}"]
    remote_state = git(repo, "rev-parse", f"{remote}/{branch}", check=False).stdout.strip()
    if state_head and state_head != remote_state:
        refs.append(f"{state_head}:refs/heads/{branch}")
    if not refs:
        return {"published": True, "pushed": [], "reason": "nothing to publish"}
    for attempt in range(attempts):
        push = git(repo, "push", "--atomic", "--porcelain", remote, *refs, check=False)
        if push.returncode == 0:
            return {"published": True, "pushed": refs, "attempts": attempt + 1}
        if f"refs/heads/{target}" not in refs[0] or "rejected" not in push.stdout + push.stderr:
            return {
                "published": False,
                "reason": "push failed",
                "error": push.stderr.strip()[-600:],
            }
        # The knowledge base moved on meanwhile (a commit from a laptop): replay on top of it.
        git(repo, "fetch", remote, f"+refs/heads/{target}:refs/remotes/{remote}/{target}")
        if git(repo, "rebase", f"{remote}/{target}", check=False).returncode:
            git(repo, "rebase", "--abort", check=False)
            side = f"garden/{run_id}"
            git(repo, "push", remote, f"HEAD:refs/heads/{side}", check=False)
            return {
                "published": False,
                "reason": "conflict with newer commits; state not advanced",
                "branch": side,
            }
    return {"published": False, "reason": "the remote kept moving; state not advanced"}


# Status -----------------------------------------------------------------------------------------


def latest_runs(cfg) -> dict:
    runs = {}
    for path in sorted((g.state_dir(cfg) / "runs").glob("*/manifest.json")):
        manifest = g.read_json(path, {})
        if manifest.get("mode"):
            runs[manifest["mode"]] = manifest
    return runs


def summary(cfg, mode: str | None, publication: dict | None) -> str:
    lines = ["## Cairn garden", ""]
    runs = latest_runs(cfg)
    modes = [mode] if mode in ("daily", "weekly") else ["daily", "weekly"]
    state = g.load_state(cfg)
    executed_ok = True
    for name in modes:
        manifest = runs.get(name)
        last = state.get("last_digest" if name == "daily" else "last_weekly")
        if manifest is None:
            lines.append(f"- **{name}**: no run yet (last completed: {last or 'never'})")
            continue
        status = manifest.get("status")
        executed_ok &= status in ("success", "success_with_warnings", "skipped")
        report = manifest.get("report_id")
        lines.append(
            f"- **{name}** `{manifest['id']}`: {status}"
            + (f", report `{reports.root(cfg).name}/{report}`" if report else "")
            + f" (last completed period: {last or 'never'})"
        )
        lines += [f"  - warning: {w}" for w in manifest.get("warnings", [])]
        if manifest.get("error"):
            lines.append(f"  - error: {manifest['error']}")
    weekly = reports.reports(cfg, "weekly")
    if weekly:
        latest = weekly[max(weekly)]
        pending = len(list(g.open_items(g.latest_run(latest.body))))
        lines.append(f"- pending approvals in `{max(weekly)}`: {pending}")
    if publication is not None:
        published = publication.get("published")
        lines.append(
            f"- publication: {'published' if published else 'NOT published'}"
            + (f" ({publication.get('reason')})" if publication.get("reason") else "")
        )
        complete = executed_ok and published
    else:
        complete = False
        lines.append("- publication: not attempted")
    lines += ["", f"**Overall: {'complete' if complete else 'incomplete'}**"]
    return "\n".join(lines) + "\n"


# Template ---------------------------------------------------------------------------------------

# 12:43/13:43 UTC is 07:43 in Chicago in summer/winter; 15:43/16:43 is 10:43 on Mondays. These
# are the earliest a period can run, not when it does: GitHub starts scheduled runs on a
# best-effort basis, often only two or three of these a day and hours late, so every hour until
# 20:43 is a catch-up. A trigger with nothing due takes seconds; `due()` decides what runs.
CRON = "43 12-20 * * *"

TEMPLATE = """\
# Cairn garden: daily digests and weekly reviews of this knowledge base.
# Generated by `cairn-garden ci template`; see cairn-workbench's gardener docs.
name: Cairn garden

on:
  schedule:
    # Best effort: GitHub starts only some scheduled runs, often hours late. Every trigger
    # catches up whatever is due, so a digest lands when the first one starts.
    - cron: "{cron}"
  workflow_dispatch:
    inputs:
      mode:
        description: auto runs whatever is due; catalog refreshes the journal catalog
        type: choice
        options: [auto, daily, weekly, catalog, enable-zotero-writes]
        default: auto
      scheduled:
        description: only run a period that is due
        type: boolean
        default: true
      allow-empty-state:
        description: first run only - start without garden state
        type: boolean
        default: false

# One run at a time for everything that changes the knowledge base or its state.
concurrency:
  group: cairn-garden
  cancel-in-progress: false

permissions:
  contents: write

jobs:
  garden:
    uses: iamsikun/cairn-workbench/.github/workflows/garden.yml@{version}
    with:
      version: {version}
      mode: ${{{{ inputs.mode || 'auto' }}}}
      scheduled: ${{{{ github.event_name == 'schedule' || inputs.scheduled }}}}
      allow-empty-state: ${{{{ inputs.allow-empty-state || false }}}}
      # aster: pinned      # also collect new papers with the Aster release this version pins
    secrets: inherit
"""


def template(version: str | None = None) -> str:
    return TEMPLATE.format(cron=CRON, version=version or f"v{__version__}")


# CLI --------------------------------------------------------------------------------------------


def output(name: str, value: str) -> None:
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as handle:
            handle.write(f"{name}={value}\n")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="cairn-garden ci",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("restore", "publish"):
        p = sub.add_parser(name)
        p.add_argument("--branch", default="garden-state")
        p.add_argument("--remote", default="origin")
        p.add_argument("--repo", type=Path)
        if name == "restore":
            p.add_argument("--allow-empty", action="store_true")
        else:
            p.add_argument("--target")
    p = sub.add_parser("due")
    p.add_argument("mode", choices=("daily", "weekly"))
    p = sub.add_parser("catalog-fresh")
    p.add_argument("--max-age", type=float, help="days; default catalog_max_age_days")
    p = sub.add_parser("summary")
    p.add_argument("--mode")
    p = sub.add_parser("state-export")
    p.add_argument("dir", type=Path)
    p = sub.add_parser("state-import")
    p.add_argument("dir", type=Path)
    p.add_argument("--allow-empty", action="store_true")
    p = sub.add_parser("template")
    p.add_argument("--version")
    args = parser.parse_args(argv)
    if args.cmd == "template":
        print(template(args.version), end="")
        return 0
    cfg = g.config()
    repo = getattr(args, "repo", None) or g.workspace(cfg)
    publication_file = g.HOME / "ci-publication.json"
    try:
        if args.cmd == "restore":
            result = restore(cfg, repo, args.branch, args.remote, args.allow_empty)
        elif args.cmd == "publish":
            result = publish(cfg, repo, args.branch, args.remote, args.target)
            g.atomic_json(publication_file, result)
        elif args.cmd == "due":
            from .workflow import due

            result = {"mode": args.mode, "due": due(cfg, args.mode)}
            output("due", str(result["due"]).lower())
        elif args.cmd == "catalog-fresh":
            if args.max_age is not None:
                cfg["catalog_max_age_days"] = args.max_age
            result = g.catalog_freshness(cfg)
            output("fresh", str(result["fresh"]).lower())
        elif args.cmd == "summary":
            text = summary(cfg, args.mode, g.read_json(publication_file, None))
            if os.environ.get("GITHUB_STEP_SUMMARY"):
                with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as handle:
                    handle.write(text)
            print(text, end="")
            # Surface paused writes on the run page; the summary alone was easy to miss.
            from .workflow import WRITES_PAUSED

            paused = {
                warning
                for manifest in latest_runs(cfg).values()
                for warning in manifest.get("warnings", [])
                if warning.startswith(WRITES_PAUSED)
            }
            for warning in sorted(paused):
                print(f"::warning title=Zotero writes paused::{warning}")
            return 0 if "**Overall: complete**" in text else 1
        elif args.cmd == "state-export":
            result = export_state(cfg, args.dir)
        else:
            result = import_state(cfg, args.dir, args.allow_empty)
    except Exception as error:
        g.out({"error": type(error).__name__, "message": str(error)})
        return 1
    g.out(result)
    if args.cmd == "publish":
        return 0 if result.get("published") else 1
    if args.cmd == "due":
        return 0 if result["due"] else 3
    if args.cmd == "catalog-fresh":
        return 0 if result["fresh"] else 3
    return 0
