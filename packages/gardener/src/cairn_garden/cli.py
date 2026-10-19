"""cairn-garden: keep a Cairn knowledge base organized and growing.

daily | weekly [--scheduled] [--agent claude|codex] [--model M] [--zotero-limit N]
                               a complete verified pass; --scheduled runs only when due
health | readiness | enable-zotero-writes
                               runtime checks and the scheduled Zotero write gate
apply [NOTE] [--dry-run]       run approved proposals
lint | fix-links | new-papers | zotero-sync | zotero-gaps | snapshot | verify | storage |
html-audit | metrics | archive-digests | commit | config
                               engine commands; each prints JSON (`cairn-garden lint -h`)
schedule [--catalog] [--aster] [--remove]
                               install or remove the launchd jobs (after readiness passes)
skill [--remove]               link the kb-gardener skill into Claude Code and other agents
zotero-bridge --output FILE.xpi [--credentials]
                               build the local Zotero extension and provision its credential
migrate [--dry-run] [--workspace PATH] [--resources-to PATH] | migrate --rollback JOURNAL
                               move a kb-gardener install and in-workspace catalog out of the
                               knowledge base, into this layout
migrate-reports [--dry-run] [--maintenance SLUG ...] | migrate-reports --rollback JOURNAL
                               move garden reports out of the research notes into gardening/
ci restore | publish | due | catalog-fresh | summary | state-export | state-import | template
                               unattended runs on GitHub Actions (`cairn-garden ci -h`)
sync setup | run | status | remove
                               local Git sync and a daily macOS calendar schedule
"""

from __future__ import annotations

import json
import os
import sys
from datetime import date
from pathlib import Path

WORKFLOW = {"daily", "weekly", "health", "readiness", "enable-zotero-writes"}
# Each skills folder and the folders that show its agent is installed, as Finch, Quill and
# Aster's installers detect them: Codex, Gemini CLI and Cursor share ~/.agents/skills.
SKILL_HOMES = {
    ".claude": (".claude",),
    ".agents": (".agents", ".codex", ".gemini", ".cursor"),
    ".copilot": (".copilot",),
    ".config/opencode": (".config/opencode",),
}


def _print(value) -> None:
    print(json.dumps(value, indent=2, ensure_ascii=False, default=str))


def agent_path() -> None:
    """launchd and other minimal environments lack the folders where agent CLIs are installed."""
    extra = [
        str(Path.home() / ".local/bin"),
        "/opt/homebrew/bin",
        "/usr/local/bin",
        "/usr/bin",
        "/bin",
    ]
    os.environ["PATH"] = os.pathsep.join([*extra, os.environ.get("PATH", "")])


def scheduled_log(mode: str) -> None:
    """A scheduled run has no terminal; append its output to a dated log."""
    from . import engine

    logs = engine.HOME / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    log = open(logs / f"{date.today().isoformat()}-{mode}.log", "a")  # kept open for the process
    os.dup2(log.fileno(), 1)
    os.dup2(log.fileno(), 2)


def skill(remove: bool) -> dict:
    from .workflow import SKILL

    home, done = Path.home(), []
    for folder, markers in SKILL_HOMES.items():
        if not any((home / marker).is_dir() for marker in markers):
            continue
        link = home / folder / "skills" / "kb-gardener"
        # A link is this package's when it points at a cairn_garden skill folder or nowhere.
        ours = link.is_symlink() and (
            not link.exists() or Path(os.readlink(link)).parts[-2:] == ("cairn_garden", "skill")
        )
        if remove:
            if ours:
                link.unlink()
                done.append({"unlinked": str(link)})
            continue
        if link.exists() and not link.is_symlink():
            done.append({"skipped": str(link), "reason": "a non-link folder already exists"})
            continue
        if link.is_symlink() and not ours:
            done.append({"kept": str(link), "reason": f"owned elsewhere: {os.readlink(link)}"})
            continue
        link.parent.mkdir(parents=True, exist_ok=True)
        if link.is_symlink():
            link.unlink()
        link.symlink_to(SKILL, target_is_directory=True)
        done.append({"linked": str(link), "to": str(SKILL)})
    return {"skill": done}


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0 if argv else 2
    command, rest = argv[0], argv[1:]
    if command in WORKFLOW:
        agent_path()
        if command in ("daily", "weekly") and "--scheduled" in rest:
            scheduled_log(command)
        from . import workflow

        return workflow.main(argv)
    if command == "schedule":
        from . import schedule

        _print(
            schedule.remove()
            if "--remove" in rest
            else schedule.install(catalog="--catalog" in rest, aster="--aster" in rest)
        )
        return 0
    if command == "skill":
        _print(skill("--remove" in rest))
        return 0
    if command == "migrate":
        import argparse

        from . import migrate

        parser = argparse.ArgumentParser(prog="cairn-garden migrate", description=migrate.__doc__)
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--workspace", type=Path)
        parser.add_argument("--resources-to", type=Path, help="where research/resources moves")
        parser.add_argument("--rollback", type=Path, metavar="JOURNAL")
        args = parser.parse_args(rest)
        if args.rollback:
            result = migrate.rollback(args.rollback)
        elif args.dry_run:
            result = migrate.plan(args.workspace, args.resources_to)
        else:
            result = migrate.run(args.workspace, args.resources_to)
        _print(result)
        return 0 if not result.get("problems") else 1
    if command == "ci":
        from . import ci

        return ci.main(rest)
    if command == "sync":
        agent_path()
        from . import sync

        return sync.main(rest)
    if command == "migrate-reports":
        import argparse

        from . import engine, migrate_reports

        parser = argparse.ArgumentParser(
            prog="cairn-garden migrate-reports", description=migrate_reports.__doc__
        )
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--maintenance", action="append", default=[], metavar="SLUG")
        parser.add_argument("--rollback", type=Path, metavar="JOURNAL")
        args = parser.parse_args(rest)
        cfg = engine.config()
        try:
            if args.rollback:
                result = migrate_reports.rollback(cfg, args.rollback)
            elif args.dry_run:
                result = migrate_reports.preview(cfg, args.maintenance)
            else:
                result = migrate_reports.run(cfg, args.maintenance)
        except Exception as error:
            result = {"error": type(error).__name__, "problems": [str(error)]}
        _print(result)
        return 0 if not result.get("problems") else 1
    if command == "zotero-bridge":
        import argparse

        from .zotero_local import prepare

        parser = argparse.ArgumentParser(prog="cairn-garden zotero-bridge")
        parser.add_argument("--output", type=Path, required=True)
        parser.add_argument("--credentials", action="store_true")
        args = parser.parse_args(rest)
        _print(prepare(args.output, args.credentials))
        return 0
    from . import engine

    engine.main(argv)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
