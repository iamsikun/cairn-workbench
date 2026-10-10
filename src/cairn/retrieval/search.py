from __future__ import annotations

import json
import re
import sqlite3
from typing import Any, Literal

from pydantic import Field

from cairn.errors import Blocked, CairnError
from cairn.ingest.service import load_extraction
from cairn.policies.models import Scope
from cairn.records.models import EvidenceRef, Model, Period, canonical, digest
from cairn.storage.workspace import Workspace


class Hit(Model):
    id: str
    kind: Literal["evidence", "synthesis", "note"]
    title: str
    text: str
    locator: str
    sources: list[EvidenceRef]
    source_date: str | None = None
    source_version: str | None = None
    coverage: str | None = None
    verification: list[str] = Field(default_factory=list)
    supersedes: list[str] = Field(default_factory=list)
    disputes: list[str] = Field(default_factory=list)
    period: Period | None = None
    status: str = "draft"
    review_date: str | None = None
    finance_category: str | None = None


ALIASES = {"evidence": "证据", "retrieval": "检索", "decision": "决策"}


def _terms(query: str) -> list[str]:
    terms = re.findall(r"[^\W_]+", query.casefold(), re.UNICODE)
    result = set(terms)
    for english, chinese in ALIASES.items():
        if english in result:
            result.add(chinese)
        if chinese in result:
            result.add(english)
    return sorted(result)


def _corpus(ws: Workspace, scope: Scope) -> tuple[list[tuple[Hit, list[str]]], str]:
    # Only this owner-side scan can see the complete vault. The database, statistics,
    # serialized results, and worker inputs contain the authorized subset only.
    records = ws.records(scope)
    allowed = {record.id for _, record, _ in records}
    allowed_assertions = {
        assertion.id for _, record, _ in records for assertion in record.assertions
    }
    hashes: dict[str, str] = {}
    corpus: list[tuple[Hit, list[str]]] = []
    for path, record, body in records:
        from cairn.proposals.service import all_refs

        if any(ref.id not in allowed for ref in all_refs(record)):
            # Withhold derived text as well as its citation if its evidence is denied.
            # Stripping only the reference can expose the restricted conclusion.
            continue
        hashes[path] = digest(ws.fs.read(path))
        if record.source and record.source.extraction:
            extraction, key = load_extraction(ws, record)
            hashes[f"evidence/{key}.json"] = key
            for segment in extraction.segments:
                if not segment.text.strip():
                    continue
                corpus.append(
                    (
                        Hit(
                            id=record.id,
                            kind="evidence",
                            title=record.title,
                            text=segment.text,
                            locator=segment.locator,
                            sources=[
                                EvidenceRef(
                                    id=record.id,
                                    source_hash=extraction.source_hash,
                                    evidence_hash=key,
                                    locator=segment.locator,
                                )
                            ],
                            source_date=str(record.source.source_date)
                            if record.source.source_date
                            else None,
                            source_version=record.source.version,
                            coverage=extraction.coverage,
                            supersedes=[
                                item for item in record.source.supersedes if item in allowed
                            ],
                            period=record.period,
                            status=record.status,
                        ),
                        record.aliases,
                    )
                )
        elif record.type != "source":
            refs = [ref for ref in record.sources if ref.id in allowed]
            refs += [ref for a in record.assertions for ref in a.sources if ref.id in allowed]
            corpus.append(
                (
                    Hit(
                        id=record.id,
                        kind="synthesis",
                        title=record.title,
                        text="\n".join(
                            [body, *record.sections.values(), *(a.text for a in record.assertions)]
                        ),
                        locator="record",
                        sources=refs,
                        source_date=str(record.period.as_of)
                        if record.period and record.period.as_of
                        else None,
                        verification=sorted({a.verification for a in record.assertions}),
                        supersedes=[
                            item
                            for a in record.assertions
                            for item in a.supersedes
                            if item in allowed | allowed_assertions
                        ],
                        disputes=[
                            item
                            for a in record.assertions
                            for item in a.disputes
                            if item in allowed | allowed_assertions
                        ],
                        period=record.period,
                        status=record.status,
                        review_date=str(record.review_date) if record.review_date else None,
                        finance_category=record.finance_category,
                    ),
                    record.aliases,
                )
            )
    from cairn.ingest.notes import read_notes

    for note in read_notes(ws):
        if not scope.allows_labels(note.labels) or scope.record_ids or scope.project_ids:
            continue
        hashes[note.path] = note.sha256
        # Owner notes are searchable as written; they are not source evidence.
        corpus.append(
            (
                Hit(
                    id=f"note:{note.path}",
                    kind="note",
                    title=note.title,
                    text=note.body,
                    locator=note.path,
                    sources=[],
                    status="owner_note",
                ),
                [],
            )
        )
    key = digest(
        canonical({"format": 3, "scope": scope, "policy": ws.policy_hash, "hashes": hashes})
    )
    return corpus, key


def _index(ws: Workspace, scope: Scope, *, rebuild: bool = False) -> sqlite3.Connection:
    corpus, key = _corpus(ws, scope)
    path = f"cache/indexes/{key}.sqlite"
    manifest = f"cache/indexes/{key}.json"
    connection = sqlite3.connect(":memory:")
    if not rebuild and ws.fs.exists(path) and ws.fs.exists(manifest):
        data = ws.fs.read(path)
        expected = json.loads(ws.fs.read(manifest))
        if expected.get("hash") == digest(data) and expected.get("key") == key:
            try:
                connection.deserialize(data)
                connection.execute("SELECT count(*) FROM docs").fetchone()
                return connection
            except sqlite3.DatabaseError:
                connection.close()
                connection = sqlite3.connect(":memory:")
    try:
        connection.execute("CREATE TABLE docs (id INTEGER PRIMARY KEY, payload TEXT)")
        connection.execute(
            "CREATE VIRTUAL TABLE search USING fts5(title, text, aliases, tokenize='unicode61')"
        )
        connection.execute("CREATE VIRTUAL TABLE substring USING fts5(text, tokenize='trigram')")
    except sqlite3.OperationalError as exc:
        connection.close()
        raise Blocked("SQLite FTS5 and trigram tokenizer are required") from exc
    for index, (hit, aliases) in enumerate(corpus, 1):
        connection.execute("INSERT INTO docs VALUES (?, ?)", (index, canonical(hit).decode()))
        connection.execute(
            "INSERT INTO search(rowid,title,text,aliases) VALUES (?,?,?,?)",
            (index, hit.title, hit.text, " ".join(aliases)),
        )
        connection.execute(
            "INSERT INTO substring(rowid,text) VALUES (?,?)",
            (index, " ".join([hit.title, hit.text, *aliases])),
        )
    connection.commit()
    data = connection.serialize()
    ws.fs.write(path, data)
    ws.fs.write(manifest, canonical({"key": key, "hash": digest(data)}))
    return connection


def rebuild_index(ws: Workspace, scope_name: str) -> int:
    with ws.lock(write=True):
        return rebuild_unlocked(ws, scope_name)


def rebuild_unlocked(ws: Workspace, scope_name: str) -> int:
    connection = _index(ws, ws.policy.scope(scope_name), rebuild=True)
    try:
        return int(connection.execute("SELECT count(*) FROM docs").fetchone()[0])
    finally:
        connection.close()


def search(
    ws: Workspace,
    query: str,
    *,
    scope_name: str,
    limit: int = 10,
    kind: Literal["evidence", "synthesis", "note"] | None = None,
    include_notes: bool = False,
) -> list[Hit]:
    """Owner notes appear only when requested, so views and packets never carry them."""
    if not 1 <= limit <= 100 or len(query) > 1000:
        raise CairnError("query or result limit exceeds budget")
    terms = _terms(query)
    if not terms:
        return []
    with ws.lock(write=True):
        from cairn.policies.audit import require_local_route_unlocked

        require_local_route_unlocked(
            ws,
            scope_name=scope_name,
            records=[],
            operation="query",
            provider="fts5",
            persist=False,
            payload_hash=digest(canonical({"question": query, "limit": limit, "kind": kind})),
        )
        connection = _index(ws, ws.policy.scope(scope_name))
        try:
            # FTS syntax is constructed from literal tokens, never accepted as SQL/FTS code.
            expression = " OR ".join('"' + term.replace('"', '""') + '"' for term in terms)
            scores: dict[int, float] = dict(
                connection.execute(
                    "SELECT rowid,bm25(search,4.0,1.0,3.0) FROM search WHERE search MATCH ?",
                    (expression,),
                ).fetchall()
            )
            for term in terms:
                if re.search(r"[\u3400-\u9fff]", term):
                    if len(term) >= 3:
                        rows = connection.execute(
                            "SELECT rowid FROM substring WHERE substring MATCH ?",
                            ('"' + term + '"',),
                        ).fetchall()
                    else:
                        rows = connection.execute(
                            "SELECT rowid FROM substring WHERE instr(text,?) > 0", (term,)
                        ).fetchall()
                    for (row_id,) in rows:
                        scores.setdefault(row_id, -0.000001)
            hits = []
            for row_id in sorted(scores, key=lambda item: (scores[item], item)):
                payload = connection.execute(
                    "SELECT payload FROM docs WHERE id=?", (row_id,)
                ).fetchone()
                hit = Hit.model_validate_json(payload[0])
                if hit.kind == "note" and not include_notes:
                    continue
                if kind is None or hit.kind == kind:
                    hits.append(hit)
                if len(hits) == limit:
                    break
            return hits
        finally:
            connection.close()


def query(ws: Workspace, question: str, *, scope_name: str, limit: int = 10) -> dict[str, Any]:
    hits = search(ws, question, scope_name=scope_name, limit=limit)
    evidence = [hit for hit in hits if hit.kind == "evidence"]
    return {
        "status": "evidence_found" if evidence else "insufficient_evidence",
        "mode": "extractive",
        "processing": {"route": "local", "provider": "fts5", "remote_requests": 0},
        "answer": "\n\n".join(f"{hit.text}\n[{hit.id}; {hit.locator}]" for hit in evidence),
        "hits": [json.loads(canonical(hit)) for hit in hits],
        "conflicts": [
            hit.id
            for hit in hits
            if hit.disputes or hit.supersedes or "disputed" in hit.verification
        ],
        "limitations": [
            "Retrieved text is evidence to review, not proof of an interpretation.",
            "No model synthesis or remote processing was performed.",
        ],
    }


def backlinks(ws: Workspace, object_id: str, *, scope_name: str) -> list[str]:
    with ws.lock():
        scope = ws.policy.scope(scope_name)
        ws.record(object_id, scope)
        from cairn.proposals.service import all_refs

        records = ws.records(scope)
        allowed = {record.id for _, record, _ in records}
        return [
            record.id
            for _, record, _ in records
            if all(ref.id in allowed for ref in all_refs(record))
            and (object_id in record.related or any(ref.id == object_id for ref in record.sources))
        ]
