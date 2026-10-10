"""Read-only triage: inbox notes, unaccepted proposals and unanswered writing packets."""

from __future__ import annotations

from cairn.ingest.notes import read_notes
from cairn.proposals.accept import EXPLICIT_ONLY, pending
from cairn.records.models import Model
from cairn.storage.workspace import Workspace


class InboxNote(Model):
    path: str
    title: str
    domain: str
    classification: str
    captured_as: str | None


class InboxProposal(Model):
    proposal_id: str
    origin: str
    paths: list[str]
    review_flags: list[str]
    next: str


class InboxPacket(Model):
    kind: str
    packet_id: str
    next: str


class Inbox(Model):
    notes: list[InboxNote]
    proposals: list[InboxProposal]
    packets: list[InboxPacket]


def _origin(provider: str, job_id: str) -> str:
    if job_id.startswith("job_draft_"):
        return "draft"
    if provider.startswith("finch-"):
        return "finch"
    if provider.startswith("quill-"):
        return "quill"
    return "ingest"


def _unanswered(ws: Workspace, prefix: str, answered: str) -> list[str]:
    names = [path.rsplit("/", 1)[-1].removesuffix(".json") for path in ws.fs.files(prefix)]
    return sorted(name for name in names if not ws.fs.exists(f"{answered}/{name}.json"))


def inbox(ws: Workspace) -> Inbox:
    proposals = pending(ws)
    with ws.lock():
        captured = {
            record.source.content_hash: record.id
            for _, record, _ in ws.records()
            if record.source is not None
        }
        notes = [
            InboxNote(
                path=note.path,
                title=note.title,
                domain=note.labels.domain,
                classification=note.labels.classification,
                captured_as=captured.get(note.sha256),
            )
            for note in read_notes(ws)
            if note.path.startswith("vault/inbox/")
        ]
        packets = [
            InboxPacket(kind="finch", packet_id=key, next="cairn finch finish RESPONSE_FILE")
            for key in _unanswered(ws, "receipts/finch/exports", "receipts/finch/imports")
        ] + [
            InboxPacket(kind="quill", packet_id=key, next="cairn write finish RESPONSE_FILE")
            for key in _unanswered(ws, "receipts/quill/exports", "receipts/quill/finished")
        ] + [
            InboxPacket(kind="draft", packet_id=key, next="cairn draft finish RESPONSE_FILE")
            for key in _unanswered(ws, "receipts/drafts/exports", "receipts/drafts/finished")
        ]
    return Inbox(
        notes=notes,
        proposals=[
            InboxProposal(
                proposal_id=p.id,
                origin=_origin(p.provider, p.job_id),
                paths=[change.path for change in p.changes],
                review_flags=sorted(p.review_flags),
                next=f"cairn accept {p.id}"
                if p.review_flags & EXPLICIT_ONLY
                else "cairn accept --all",
            )
            for p in proposals
        ],
        packets=packets,
    )
