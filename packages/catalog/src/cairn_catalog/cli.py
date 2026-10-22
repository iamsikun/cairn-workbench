"""cairn-catalog: the public journal catalog that feeds a Cairn knowledge base.

update [--rebuild-only]        refresh metadata, verify a staged edition, then publish it
serve [--port N] [--open]      the catalog app on localhost (preferences, SQLite browser)
search | import-paper | harvest | harvest-repec | harvest-publisher | build | validate
                               catalog commands (see `cairn-catalog search -h`)
entities search|publications|import|build
                               authors and institutions
browser | personalize | first-seen | author-directory | verify
                               rebuild one derived part of the current edition
jmlr [--refresh]               the JMLR publisher archive
paths                          print the folders and files in use
"""

from __future__ import annotations

import argparse
import json
import sys

CATALOG = {
    "search",
    "import-paper",
    "harvest",
    "harvest-repec",
    "harvest-publisher",
    "build",
    "validate",
}


# Commands without a parser of their own: parsed here, so `-h` prints help instead of running.
SIMPLE = {
    "update": ("refresh metadata, verify a staged edition, then publish it", ["--rebuild-only"]),
    "browser": ("rebuild the offline browser pages of the current edition", []),
    "personalize": ("rewrite catalog-personal.js from the preferences and topic notes", []),
    "first-seen": ("record when each paper first entered the catalog", []),
    "author-directory": ("rebuild the surname index for author browsing", []),
    "verify": ("compare the offline pages' queries with SQLite", []),
    "jmlr": ("harvest the JMLR publisher archive", ["--refresh"]),
    "paths": ("print the folders and files in use", []),
}


def _print(value) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=1, default=str))


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0 if argv else 2
    command, rest = argv[0], argv[1:]
    if command in SIMPLE:
        text, flags = SIMPLE[command]
        parser = argparse.ArgumentParser(prog=f"cairn-catalog {command}", description=text)
        for flag in flags:
            parser.add_argument(flag, action="store_true")
        options = parser.parse_args(rest)
    if command in CATALOG:
        from . import catalog

        catalog.main([command, *rest])
    elif command == "entities":
        from . import entities

        entities.main(rest)
    elif command == "serve":
        from . import catalog_server

        catalog_server.main(rest)
    elif command == "update":
        from . import paths, update_catalog

        update_catalog.refresh(paths.data_dir(), rebuild_only=options.rebuild_only)
    elif command == "browser":
        from . import build_browser

        build_browser.build()
    elif command == "personalize":
        from . import personalize

        _print(personalize.run())
    elif command == "first-seen":
        from . import first_seen

        _print(first_seen.update())
    elif command == "author-directory":
        import sqlite3
        from contextlib import closing

        from . import author_directory

        with closing(sqlite3.connect(author_directory.ROOT / "catalog.sqlite")) as con:
            con.execute("PRAGMA foreign_keys=ON")
            with con:
                con.execute("BEGIN IMMEDIATE")
                _print(author_directory.build(con))
    elif command == "verify":
        from . import verify_offline

        _print({"parity_queries": verify_offline.verify()})
    elif command == "jmlr":
        from . import paths
        from .publisher_archives import harvest_jmlr

        harvest_jmlr(paths.data_dir(), options.refresh)
    elif command == "paths":
        from . import paths

        _print(
            {
                "config": paths.config_file(),
                "data": paths.data_dir(),
                "preferences": paths.preferences_file(),
                "workspace": paths.workspace(),
                "collection": paths.collection(),
            }
        )
    else:
        print(f"cairn-catalog: unknown command {command!r}\n{__doc__}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
