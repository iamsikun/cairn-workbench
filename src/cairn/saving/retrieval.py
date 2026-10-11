import json
import sqlite3
from typing import Any

from cairn.records.models import Domain, canonical, digest
from cairn.saving.workspace import Book


def rebuild(book: Book, collection: Domain) -> None:
    rows = book.records(collection)
    db = sqlite3.connect(":memory:")
    try:
        db.execute("CREATE VIRTUAL TABLE notes USING fts5(id UNINDEXED, title, body)")
        for identity, (_, record, body) in rows.items():
            if record.archived:
                continue
            text = "\n".join(
                [
                    body,
                    *record.aliases,
                    *record.unresolved,
                    *(o.text for o in record.observations),
                    *(r.explanation for r in record.relationships if r.state == "active"),
                ]
            )
            db.execute("INSERT INTO notes VALUES (?, ?, ?)", (identity, record.title, text))
        db.commit()
        book.fs.write(f"cache/search/{collection}.sqlite", db.serialize())
        hashes = {p: book.revision(p) for p, _, _ in rows.values()}
        book.fs.write(f"cache/search/{collection}.json", canonical(hashes))
    finally:
        db.close()


def search(book: Book, collection: Domain, query: str, limit: int = 20) -> list[dict[str, Any]]:
    book.collection(collection)
    with book.lock():
        # Rebuild from canonical records: external Markdown edits cannot yield stale results.
        ranks: dict[str, float] = {}
        terms = query.casefold().split()
        try:
            rebuild(book, collection)
            if terms:
                db = sqlite3.connect(":memory:")
                try:
                    db.deserialize(book.fs.read(f"cache/search/{collection}.sqlite"))
                    expression = " OR ".join('"' + term.replace('"', '""') + '"' for term in terms)
                    ranks = dict(
                        db.execute(
                            "SELECT id, -bm25(notes) FROM notes WHERE notes MATCH ?", (expression,)
                        )
                    )
                finally:
                    db.close()
        except (OSError, sqlite3.Error):
            pass  # Canonical fallback below remains scoped and current.
        matches: list[dict[str, Any]] = []
        for identity, (path, record, body) in book.records(collection).items():
            if record.archived:
                continue
            text = "\n".join(
                [
                    record.title,
                    body,
                    *record.aliases,
                    *record.unresolved,
                    *(o.text for o in record.observations),
                    *(r.explanation for r in record.relationships if r.state == "active"),
                ]
            )
            expanded = text.casefold()
            score = sum(expanded.count(term) for term in terms)
            if score or not terms:
                matches.append(
                    {
                        "id": identity,
                        "title": record.title,
                        "kind": record.kind,
                        "revision": book.revision(path),
                        "excerpt": body[:500],
                        "score": ranks.get(identity, 0.0) + score * 0.000000001,
                        "enrichment": record.enrichment,
                    }
                )
        return sorted(matches, key=lambda r: (-r["score"], r["id"]))[: max(1, min(limit, 100))]


def get_note(book: Book, collection: Domain, identity: str) -> dict[str, Any]:
    with book.lock():
        path, record, body = book.record(identity, collection)
        rows = book.records(collection)
        visible = {k: r for k, (_, r, _) in rows.items() if not r.archived}
        value = record.model_dump(mode="json")
        index_state = "pending"
        index_path = f"cache/search/{collection}.json"
        if book.fs.exists(index_path):
            try:
                if json.loads(book.fs.read(index_path)) == {
                    p: book.revision(p) for p, _, _ in rows.values()
                }:
                    index_state = "current"
            except (ValueError, OSError):
                pass
        html_state = "not_requested"
        manifest_path = f"views/{collection}/{identity}.json"
        if book.fs.exists(manifest_path):
            html_state = "stale"
            try:
                manifest = json.loads(book.fs.read(manifest_path))
                if all(
                    k in rows and book.revision(rows[k][0]) == rev
                    for k, rev in manifest["inputs"].items()
                ):
                    html_state = "current"
            except (ValueError, OSError, KeyError):
                pass
        value["states"] = {
            "content": "saved",
            "enrichment": record.enrichment,
            "search": index_state,
            "html": html_state,
        }
        value["relationships"] = [
            {
                **r.model_dump(mode="json"),
                "sources": [c.model_dump(mode="json") for c in r.sources if c.id in visible],
            }
            for r in record.relationships
            if r.target in visible
        ]
        value["citations"] = [
            c.model_dump(mode="json") for c in record.citations if c.id in visible
        ]
        if record.primary_source_id not in visible:
            value["primary_source_id"] = None
        value["source_versions"] = [
            identity for identity in record.source_versions if identity in visible
        ]
        from cairn.saving.models import SaveReceipt

        receipts = [
            SaveReceipt.model_validate_json(book.fs.read(p))
            for p in book.fs.files(f"revisions/{collection}")
        ]
        value["checkpoints"] = [
            {
                "revision_id": r.id,
                "at": r.at.isoformat(),
                "revision": n.revision,
                "client": r.client,
                "model": r.model,
            }
            for r in sorted(receipts, key=lambda r: r.at, reverse=True)
            for n in r.notes
            if n.id == identity
        ][:100]
        value.update(
            markdown=body,
            path=str(book.root / path),
            revision=book.revision(path),
            backlinks=[
                {
                    "id": r.id,
                    "title": r.title,
                    "relationship": link.kind,
                    "explanation": link.explanation,
                }
                for r in visible.values()
                for link in r.relationships
                if link.target == identity and link.state == "active"
            ],
        )
        return value


def list_topics(book: Book, collection: Domain) -> list[dict[str, str]]:
    with book.lock():
        return [
            {
                "id": r.id,
                "title": r.title,
                "revision": digest(book.fs.read(p)),
                "enrichment": r.enrichment,
            }
            for p, r, _ in book.records(collection).values()
            if r.kind in ("topic", "question") and not r.archived
        ]
