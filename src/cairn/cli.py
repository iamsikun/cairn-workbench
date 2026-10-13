"""cairn init | connect | mcp | search | show | topics | html"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from cairn.store import COLLECTIONS, FOLDERS, KB, STATUSES, CairnError, init


def connect_command(client: str, root: Path, collection: str, remove: bool) -> list[str]:
    """The client's own `mcp add/remove` command; Cairn never edits client settings itself."""
    name = "cairn" if collection == "research" else f"cairn-{collection}"
    scope = ["--scope", "user"] if client == "claude" else []
    if remove:
        return [client, "mcp", "remove", *scope, name]
    server = [sys.executable, "-m", "cairn", "mcp", "--workspace", str(root)]
    server += ["--collection", collection]
    return [client, "mcp", "add", *scope, name, "--", *server]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cairn", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    def command(name: str, help: str, workspace: bool = True) -> argparse.ArgumentParser:
        p = sub.add_parser(name, help=help)
        if workspace:
            p.add_argument(
                "-w",
                "--workspace",
                default=os.environ.get("CAIRN_WORKSPACE"),
                help="knowledge base folder (default: $CAIRN_WORKSPACE)",
            )
            p.add_argument("-c", "--collection", default="research", choices=COLLECTIONS)
        return p

    p = command("init", "create a knowledge base", workspace=False)
    p.add_argument("path", type=Path)
    p = command("connect", "register the MCP server with Claude Code or Codex")
    p.add_argument("client", choices=["claude", "codex"])
    p.add_argument("--remove", action="store_true", help="unregister instead")
    p.add_argument("--dry-run", action="store_true", help="print the command only")
    command("mcp", "run the MCP server on stdio (started by the client)")
    p = command("search", "search notes")
    p.add_argument("query", nargs="?", default="", help="keywords; omit to list all")
    p.add_argument("--kind", choices=list(FOLDERS))
    p.add_argument("--status", choices=STATUSES, help="idea status")
    p = command("show", "print a note with its links and backlinks")
    p.add_argument("name")
    command("topics", "list topics and their hierarchy")
    command("html", "write offline HTML pages and print the index path")

    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            print(f"Initialized {init(args.path)}")
            return 0
        if not args.workspace:
            raise CairnError("pass --workspace or set CAIRN_WORKSPACE")
        kb = KB(args.workspace, args.collection)
        if args.command == "connect":
            cmd = connect_command(args.client, kb.root, kb.collection, args.remove)
            print(" ".join(cmd))
            return 0 if args.dry_run else subprocess.call(cmd)
        if args.command == "mcp":
            from cairn.mcp import serve

            serve(kb)
            return 0
        result: Any
        if args.command == "search":
            result = kb.search(args.query, 50, args.kind, args.status)
        elif args.command == "show":
            result = kb.get(args.name)
        elif args.command == "topics":
            result = kb.list_topics()
        else:
            from cairn.html import render

            result = str(render(kb) / "index.html")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except CairnError as exc:
        print(f"cairn: {exc}", file=sys.stderr)
        return 1
