"""Saved, scoped feed snapshots. Rendering never interprets imported markup."""

from __future__ import annotations

import html
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Literal
from urllib.parse import quote

from pydantic import Field

from cairn.errors import Denied
from cairn.library.catalog import get_paper
from cairn.library.store import commit_unlocked
from cairn.records.models import ID, Digest, Model, canonical, digest, now
from cairn.storage.workspace import Workspace


class FeedEvent(Model):
    id: ID
    paper_id: ID
    kind: Literal["new_publication", "newly_discovered", "box_addition", "box_revision"]
    at: datetime
    reading_requested: bool = False


class FeedEntry(Model):
    event: FeedEvent
    title: str
    citation: str
    journal_ids: list[ID]
    journals: list[str]
    doi: str | None = None
    availability: str
    summary: str | None = None
    coverage: str = "Not read"
    reading_status: str = "unknown"
    analysis_status: str = "not_started"
    review_state: str = "unreviewed"
    verification: list[str] = Field(default_factory=list)
    proposal_id: ID | None = None
    source_hash: Digest | None = None


class FeedDigest(Model):
    schema_version: Literal[1] = 1
    id: ID
    scope: ID
    at: datetime
    entries: list[FeedEntry]
    issues: list[str] = Field(default_factory=list)
    notification: Literal["pending", "acknowledged"] = "pending"


def entries(ws: Workspace, events: list[FeedEvent], scope: str) -> list[FeedEntry]:
    result = []
    with ws.lock():
        for event in events:
            record, paper = get_paper(ws, event.paper_id, scope)
            visible = [
                (key, ws.record(key, ws.policy.scope(scope))[1].title)
                for key in paper.journal_ids
                if ws.policy.scope(scope).allows(ws.record(key)[1])
            ]
            entry = FeedEntry(
                event=event,
                title=record.title,
                citation=f"{'; '.join(paper.authors) or 'Authors unknown'} "
                f"({paper.year or 'year unknown'}). {record.title}.",
                journal_ids=[key for key, _ in visible],
                journals=[title for _, title in visible],
                doi=paper.doi,
                reading_status=paper.reading,
                availability="PDF available"
                if any(f.availability == "available" for f in paper.files)
                else (
                    "Archived PDF; Box unavailable"
                    if any(f.source_id for f in paper.files)
                    else "Metadata only"
                ),
            )
            result.append(entry)
    return result


def save(
    ws: Workspace, events: list[FeedEvent], issues: list[str], scope: str
) -> FeedDigest | None:
    rows = entries(ws, events, scope)
    fingerprint = digest(canonical({"scope": scope, "entries": rows, "issues": sorted(issues)}))
    with ws.lock(write=True):
        pointer = f"receipts/library/feed_latest/{scope}.json"
        previous_id = None
        if ws.fs.exists(pointer):
            from cairn.records.json import read_json

            previous = read_json(ws.fs.read(pointer))
            previous_id = previous["id"]
            if previous["fingerprint"] == fingerprint:
                return None
        value = FeedDigest(
            id="digest_" + digest(canonical([fingerprint, previous_id]))[:32],
            scope=scope,
            at=now(),
            entries=rows,
            issues=sorted(issues),
        )
        path = f"receipts/library/feeds/{value.id}.json"
        if ws.fs.exists(path):
            value = FeedDigest.model_validate_json(ws.fs.read(path))
        commit_unlocked(
            ws,
            {
                path: canonical(value),
                pointer: canonical({"id": value.id, "fingerprint": fingerprint}),
            },
            "save_feed",
        )
        # Rebuildable presentation artifacts; the durable JSON is the authoritative
        # saved digest and is included in backup/history.
        for format in ("md", "html", "atom"):
            ws.fs.write(
                f"cache/library/feed/{scope}/{value.id}.{format}", render(value, format).encode()
            )
            ws.fs.write(
                f"cache/library/feed/{scope}/latest.{format}", render(value, format).encode()
            )
        return value


def history(ws: Workspace, scope: str, limit: int = 20) -> list[FeedDigest]:
    if not 1 <= limit <= 100:
        raise Denied("feed history limit must be 1..100")
    with ws.lock():
        output = []
        for path in ws.fs.files("receipts/library/feeds"):
            value = FeedDigest.model_validate_json(ws.fs.read(path))
            if value.scope != scope:
                continue
            # Recheck every record on access; saved counts must not leak revoked scopes.
            for entry in value.entries:
                get_paper(ws, entry.event.paper_id, scope)
                for journal_id in entry.journal_ids:
                    ws.record(journal_id, ws.policy.scope(scope))
            output.append(value)
        return sorted(output, key=lambda v: (v.at, v.id), reverse=True)[:limit]


def acknowledge(ws: Workspace, digest_id: str, scope: str) -> None:
    with ws.lock(write=True):
        path = f"receipts/library/feeds/{digest_id}.json"
        value = FeedDigest.model_validate_json(ws.fs.read(path))
        if value.scope != scope:
            raise Denied("digest unavailable")
        for entry in value.entries:
            get_paper(ws, entry.event.paper_id, scope)
        value.notification = "acknowledged"
        commit_unlocked(ws, {path: canonical(value)}, "acknowledge_feed_delivery")


def render(value: FeedDigest, format: str) -> str:
    if format == "json":
        return canonical(value).decode()
    if format == "atom":
        ET.register_namespace("", "http://www.w3.org/2005/Atom")
        ns = "{http://www.w3.org/2005/Atom}"
        root = ET.Element(ns + "feed")
        ET.SubElement(root, ns + "id").text = f"urn:cairn:feed:{value.scope}"
        ET.SubElement(root, ns + "title").text = "Cairn journal updates"
        ET.SubElement(root, ns + "updated").text = value.at.isoformat()
        author = ET.SubElement(root, ns + "author")
        ET.SubElement(author, ns + "name").text = "Cairn"
        for entry in value.entries:
            item = ET.SubElement(root, ns + "entry")
            ET.SubElement(item, ns + "id").text = "urn:cairn:" + entry.event.id
            ET.SubElement(item, ns + "title").text = entry.title
            ET.SubElement(item, ns + "updated").text = value.at.isoformat()
            if entry.doi:
                ET.SubElement(
                    item, ns + "link", href="https://doi.org/" + quote(entry.doi, safe="/")
                )
            ET.SubElement(item, ns + "summary", type="text").text = entry_text(entry)
        return ET.tostring(root, encoding="unicode", xml_declaration=True)
    groups: dict[str, list[FeedEntry]] = {}
    for entry in value.entries:
        for journal in entry.journals or ["Unresolved journal"]:
            groups.setdefault(journal, []).append(entry)
    if format == "html":
        content = "<h1>Cairn journal updates</h1>"
        content += f"<p>{html.escape(value.at.isoformat())}</p>"
        content += "".join(
            f"<p><strong>Attention:</strong> {html.escape(x)}</p>" for x in value.issues
        )
        for journal, rows in sorted(groups.items()):
            content += f"<h2>{html.escape(journal)}</h2>"
            for entry in rows:
                content += (
                    f"<article><h3>{html.escape(entry.title)}</h3>"
                    f"<pre>{html.escape(entry_text(entry))}</pre>"
                )
                if entry.doi:
                    content += (
                        f'<a href="https://doi.org/{quote(entry.doi, safe="/")}">Publication</a>'
                    )
                content += "</article>"
        return (
            "<!doctype html><html lang=en><meta charset=utf-8>"
            "<meta http-equiv=Content-Security-Policy content=\"default-src 'none'; "
            "style-src 'unsafe-inline'\">"
            "<title>Cairn feed</title><style>body{font:16px system-ui;max-width:850px;"
            "margin:3em auto}pre{white-space:pre-wrap;font:inherit}"
            "article{border-top:1px solid #ccc;padding:1em 0}</style>" + content + "</html>"
        )
    if format != "md":
        raise Denied("feed format must be md, html, atom, or json")

    # Escape Markdown control syntax as well as HTML in all imported strings.
    def escape(text: str) -> str:
        text = html.escape(text)
        for token in ("\\", "`", "*", "_", "[", "]", "#", "!"):
            text = text.replace(token, "\\" + token)
        return text

    body = f"# Cairn journal updates\n\n{value.at.isoformat()}\n\n"
    body += "\n".join(f"Attention: {escape(issue)}" for issue in value.issues) + "\n\n"
    for journal, rows in sorted(groups.items()):
        body += f"## {escape(journal)}\n\n"
        for entry in rows:
            body += f"### {escape(entry.title)}\n\n{escape(entry_text(entry))}\n\n"
            if entry.doi:
                body += f"[Publication](https://doi.org/{quote(entry.doi, safe='/')})\n\n"
    return body


def entry_text(entry: FeedEntry) -> str:
    return (
        f"{entry.citation}\n{entry.event.kind.replace('_', ' ')}; {entry.availability}\n"
        f"{entry.summary or 'Summary pending or unavailable.'}\n"
        f"Evidence: {entry.coverage}\nReview: {entry.review_state}\n"
        f"Verification: {'; '.join(entry.verification) or 'Pending'}\n"
        f"Personal reading: {entry.reading_status}; analysis: {entry.analysis_status}\n"
        f"Paper: {entry.event.paper_id}; proposal: {entry.proposal_id or 'none'}"
    )
