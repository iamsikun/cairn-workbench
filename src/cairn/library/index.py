from __future__ import annotations

import html
import json
import sqlite3
from typing import Any

from cairn.library.models import Paper, metadata
from cairn.library.store import entities_unlocked
from cairn.records.models import canonical, digest
from cairn.storage.workspace import Workspace


def papers(
    ws: Workspace,
    *,
    scope: str,
    query: str = "",
    journal: str | None = None,
    year: int | None = None,
    reading: str | None = None,
    available: bool | None = None,
) -> list[dict[str, Any]]:
    with ws.lock():
        records = entities_unlocked(ws, scope)
        fingerprint = digest(
            canonical(
                {
                    "policy": ws.policy_hash,
                    "records": records,
                    "version": 1,
                }
            )
        )
        cache = f"cache/library/{scope}/{fingerprint}.sqlite"
        db = sqlite3.connect(":memory:")
        try:
            if ws.fs.exists(cache):
                db.deserialize(ws.fs.read(cache))
            else:
                db.execute(
                    "CREATE TABLE papers(id TEXT PRIMARY KEY, year INTEGER, reading TEXT, "
                    "available INTEGER, data TEXT)"
                )
                db.execute("CREATE TABLE journals(paper TEXT, journal TEXT)")
                db.execute("CREATE VIRTUAL TABLE search USING fts5(id UNINDEXED, text)")
                allowed = {r.id for r in records}
                for record in records:
                    value = metadata(record)
                    if not isinstance(value, Paper):
                        continue
                    # Journal links themselves must not reveal a denied record.
                    value.journal_ids = [key for key in value.journal_ids if key in allowed]
                    payload = {
                        "id": record.id,
                        "title": record.title,
                        "metadata": value.model_dump(mode="json"),
                    }
                    has_file = any(f.availability == "available" for f in value.files)
                    db.execute(
                        "INSERT INTO papers VALUES(?,?,?,?,?)",
                        (
                            record.id,
                            value.year,
                            value.reading,
                            has_file,
                            json.dumps(payload),
                        ),
                    )
                    db.executemany(
                        "INSERT INTO journals VALUES(?,?)",
                        [(record.id, j) for j in value.journal_ids],
                    )
                    db.execute(
                        "INSERT INTO search VALUES(?,?)",
                        (
                            record.id,
                            " ".join(
                                [
                                    record.title,
                                    *value.authors,
                                    value.doi or "",
                                    value.abstract or "",
                                    *value.topics,
                                ]
                            ),
                        ),
                    )
                db.commit()
                ws.fs.write(cache, db.serialize())
            predicates: list[str] = []
            params: list[Any] = []
            if query:
                # Literal terms: user text cannot inject FTS syntax.
                terms = " AND ".join('"' + word.replace('"', '""') + '"' for word in query.split())
                predicates.append("id IN (SELECT id FROM search WHERE search MATCH ?)")
                params.append(terms)
            if journal is not None:
                predicates.append("id IN (SELECT paper FROM journals WHERE journal=?)")
                params.append(journal)
            for field, val in (("year", year), ("reading", reading), ("available", available)):
                if val is not None:
                    predicates.append(f"{field}=?")
                    params.append(val)
            where = " WHERE " + " AND ".join(predicates) if predicates else ""
            rows = db.execute("SELECT data FROM papers" + where + " ORDER BY year DESC,id", params)
            return [json.loads(row[0]) for row in rows]
        finally:
            db.close()


def render_catalog(rows: list[dict[str, Any]]) -> str:
    body = []
    for row in rows:
        meta = row["metadata"]
        body.append(
            "<tr>"
            + "".join(
                f"<td>{html.escape(str(value))}</td>"
                for value in (
                    row["title"],
                    "; ".join(meta["authors"]),
                    meta["year"] or "Unknown",
                    meta["reading"],
                    "PDF available"
                    if any(f["availability"] == "available" for f in meta["files"])
                    else "Metadata only",
                    row["id"],
                )
            )
            + "</tr>"
        )
    return (
        "<!doctype html><html lang=en><meta charset=utf-8>"
        "<meta http-equiv=Content-Security-Policy content=\"default-src 'none'; "
        "style-src 'unsafe-inline'\"><title>Cairn library</title>"
        "<style>body{font:16px system-ui;margin:3em;max-width:1200px}"
        "td,th{text-align:left;padding:.7em;border-bottom:1px solid #ddd}</style>"
        f"<h1>Cairn library</h1><p>{len(rows)} papers in this scope.</p><table>"
        "<thead><tr><th>Paper</th><th>Authors</th><th>Year</th><th>Reading</th>"
        "<th>Availability</th><th>ID</th></tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table></html>"
    )
