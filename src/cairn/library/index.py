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
    analysis: str | None = None,
    review: str | None = None,
) -> list[dict[str, Any]]:
    with ws.lock():
        records = entities_unlocked(ws, scope)
        visible_ids = {record.id for _, record, _ in ws.records(ws.policy.scope(scope))}
        fingerprint = digest(
            canonical(
                {
                    "policy": ws.policy_hash,
                    "records": records,
                    "visible_ids": visible_ids,
                    "version": 2,
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
                    visible_journals = [key for key in value.journal_ids if key in allowed]
                    visible_metadata = value.model_dump(mode="json")
                    visible_metadata["journal_ids"] = visible_journals
                    for key in ("source_ids", "note_ids"):
                        visible_metadata[key] = [
                            item for item in visible_metadata[key] if item in visible_ids
                        ]
                    for file in visible_metadata["files"]:
                        if file["source_id"] not in visible_ids:
                            file["source_id"] = None
                    for evidence in visible_metadata["metadata_evidence"].values():
                        if evidence["source_id"] not in visible_ids:
                            evidence["source_id"] = None
                    payload = {
                        "id": record.id,
                        "title": record.title,
                        "metadata": visible_metadata,
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
                        [(record.id, j) for j in visible_journals],
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
            values = [json.loads(row[0]) for row in rows]
            states = status_unlocked(ws, {item["id"] for item in values})
            for value in values:
                value.update(
                    states.get(value["id"], {"analysis": "not_started", "review": "unreviewed"})
                )
            return [
                value
                for value in values
                if (analysis is None or value["analysis"] == analysis)
                and (review is None or value["review"] == review)
            ]
        finally:
            db.close()


def status_unlocked(ws: Workspace, allowed_ids: set[str]) -> dict[str, dict[str, str]]:
    from cairn.library.reader_models import ReadState
    from cairn.library.verification_models import VerificationState

    latest: dict[str, ReadState] = {}
    for path in ws.fs.files("receipts/library/reads"):
        value = ReadState.model_validate_json(ws.fs.read(path))
        if value.job.paper_id in allowed_ids and (
            value.job.paper_id not in latest or value.at > latest[value.job.paper_id].at
        ):
            latest[value.job.paper_id] = value
    checks: dict[str, list[VerificationState]] = {}
    for path in ws.fs.files("receipts/library/checks"):
        check = VerificationState.model_validate_json(ws.fs.read(path))
        checks.setdefault(check.read_id, []).append(check)
    statuses = {}
    for paper_id, state in latest.items():
        review = "unreviewed"
        values = checks.get(state.job.id, [])
        if any(v.result and v.result.verdict != "supported" for v in values):
            review = "concerns"
        elif any(v.status != "completed" for v in values):
            review = "verification_pending"
        elif state.proposal_id and ws.fs.exists(f"receipts/applied/{state.proposal_id}.json"):
            review = "owner_accepted"
        elif values:
            review = "model_checked_unreviewed"
        statuses[paper_id] = {"analysis": state.status, "review": review}
    return statuses


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
                    row.get("analysis", "not_started"),
                    row.get("review", "unreviewed"),
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
        "<th>Analysis</th><th>Review</th>"
        "<th>Availability</th><th>ID</th></tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table></html>"
    )
