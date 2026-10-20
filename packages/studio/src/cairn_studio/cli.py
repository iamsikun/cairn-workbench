"""cairn-studio: browse a Cairn knowledge base in a local app.

serve [-w PATH] [--collection NAME] [--port N] [--open] [--verbose]

The knowledge base is -w, else $CAIRN_WORKSPACE, else `workspace` in
~/.config/cairn-workbench/config.toml ($CAIRN_WORKBENCH_CONFIG). The collection is
--collection, else $CAIRN_COLLECTION, else `collection` there, else research.
If cairn-catalog is installed and its pages are built, the catalog is served under /catalog.
"""

from __future__ import annotations

import argparse
import os
import sys
import tomllib
import webbrowser
from pathlib import Path

from cairn.store import COLLECTIONS, CairnError

from . import catalog
from .server import StudioServer


def _settings() -> dict:
    home = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    default = home / "cairn-workbench" / "config.toml"
    path = Path(os.environ.get("CAIRN_WORKBENCH_CONFIG") or default).expanduser()
    return tomllib.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cairn-studio", description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve", help="start the app on localhost")
    serve.add_argument("-w", "--workspace", help="knowledge base folder")
    serve.add_argument("--collection", choices=COLLECTIONS)
    serve.add_argument("--port", type=int, default=8767)
    serve.add_argument("--open", action="store_true", help="open it in the browser")
    serve.add_argument("--verbose", action="store_true", help="log every request")
    args = parser.parse_args(argv)

    settings = _settings()
    workspace = args.workspace or os.environ.get("CAIRN_WORKSPACE") or settings.get("workspace")
    if not workspace:
        print("cairn-studio: pass -w PATH or set CAIRN_WORKSPACE", file=sys.stderr)
        return 2
    collection = (
        args.collection
        or os.environ.get("CAIRN_COLLECTION")
        or settings.get("collection")
        or "research"
    )
    journals = catalog.load()
    try:
        server = StudioServer(
            Path(workspace).expanduser(), collection, args.port, args.verbose, journals
        )
    except (CairnError, OSError) as exc:
        print(f"cairn-studio: {exc}", file=sys.stderr)
        return 1
    print(f"Studio: {server.url}", flush=True)
    if journals:
        print(f"Catalog: {server.url}catalog/", flush=True)
        catalog.warm(journals)
    if args.open:
        webbrowser.open(server.url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0
