"""cairn-garden: keep a Cairn knowledge base organized and growing.

daily | weekly [--scheduled] [--agent claude|codex] [--model M] [--zotero-limit N]
                               a complete verified pass; --scheduled runs only when due
health | readiness | enable-zotero-writes
                               runtime checks and the scheduled Zotero write gate
apply [NOTE] [--dry-run]       run approved proposals
lint | fix-links | new-papers | zotero-sync | zotero-gaps | snapshot | verify | storage |
html-audit | metrics | archive-digests | commit | config
                               engine commands; each prints JSON (`cairn-garden lint -h`)
schedule [--catalog] [--remove]
                               install or remove the launchd jobs (after readiness passes)
skill [--remove]               link the kb-gardener skill into Claude Code and other agents
zotero-bridge --output FILE.xpi [--credentials]
                               build the local Zotero extension and provision its credential
migrate [--dry-run] [--workspace PATH] [--resources-to PATH] | migrate --rollback JOURNAL
                               move a kb-gardener install and in-workspace catalog out of the
                               knowledge base, into this layout
"""

from __future__ import annotations

import json
import os
import sys
from datetime import date
from pathlib import Path

WORKFLOW = {"daily", "weekly", "health", "readiness", "enable-zotero-writes"}
# Claude Code reads ~/.claude/skills; Codex, Gemini CLI and Cursor read ~/.agents/skills.
SKILL_HOMES = {".claude": (".claude",), ".agents": (".agents", ".codex", ".gemini", ".cursor")}


def _print(value) -> None:
    print(json.dumps(value, indent=2, ensure_ascii=False, default=str))


def scheduled_environment(mode: str) -> None:
    """launchd starts with a minimal PATH and no terminal; find agent CLIs and keep a log."""
    from . import engine

    home = Path.home()
    extra = [str(home / ".local/bin"), "/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin"]
    os.environ["PATH"] = os.pathsep.join([*extra, os.environ.get("PATH", "")])
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
        if remove:
            if link.is_symlink():
                link.unlink()
                done.append({"unlinked": str(link)})
            continue
        if link.exists() and not link.is_symlink():
            done.append({"skipped": str(link), "reason": "a non-link folder already exists"})
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
        if command in ("daily", "weekly") and "--scheduled" in rest:
            scheduled_environment(command)
        from . import workflow

        return workflow.main(argv)
    if command == "schedule":
        from . import schedule

        _print(
            schedule.remove()
            if "--remove" in rest
            else schedule.install(catalog="--catalog" in rest)
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
