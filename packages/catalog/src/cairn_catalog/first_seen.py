#!/usr/bin/env python3
"""When each paper first entered the catalog, independent of its publication date.

"New since your last visit" compares this date with the reader's saved snapshot.
The ledger persists across refreshes; an id keeps the date of its first appearance.
"""

import json
import sqlite3
from contextlib import closing
from pathlib import Path

from . import paths

ROOT = paths.data_dir()
LEDGER = "first-seen.jsonl"


def seed_date(record, snapshot):
    """Without a ledger, the earliest source retrieval is the best evidence."""
    dates = [s["retrieved_at"][:10] for s in record.get("sources") or [] if s.get("retrieved_at")]
    return min([*dates, snapshot])


def update(root=ROOT, source_root=ROOT, snapshot=None):
    root, source_root = Path(root), Path(source_root)
    snapshot = snapshot or json.loads((root / "coverage.json").read_text())["as_of"]
    previous = {}
    for path in dict.fromkeys([root / LEDGER, source_root / LEDGER]):
        if path.exists():
            with path.open(encoding="utf-8") as handle:
                for line in handle:
                    entry = json.loads(line)
                    previous.setdefault(entry["id"], entry["first_seen"])
    seeding = not previous
    ledger = {}
    with (root / "papers.jsonl").open(encoding="utf-8") as handle:
        for line in handle:
            record = json.loads(line)
            ledger[record["id"]] = previous.get(record["id"]) or (
                seed_date(record, snapshot) if seeding else snapshot
            )
    temp = root / (LEDGER + ".tmp")
    with temp.open("w", encoding="utf-8") as handle:
        for paper_id in sorted(ledger):
            handle.write(json.dumps({"id": paper_id, "first_seen": ledger[paper_id]}) + "\n")
    temp.replace(root / LEDGER)
    with closing(sqlite3.connect(root / "catalog.sqlite")) as con:
        con.executescript(
            "DROP TABLE IF EXISTS paper_first_seen; CREATE TABLE paper_first_seen(paper_id TEXT PRIMARY KEY, first_seen TEXT NOT NULL);"
        )
        con.executemany("INSERT INTO paper_first_seen VALUES(?,?)", ledger.items())
        con.commit()
    return {
        "papers": len(ledger),
        "new": sum(paper_id not in previous for paper_id in ledger),
        "seeded": seeding,
    }
