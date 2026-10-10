"""Read-only triage: inbox notes and unaccepted proposals."""

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


class Inbox(Model):
    notes: list[InboxNote]
    proposals: list[InboxProposal]


def _origin(provider: str, job_id: str) -> str:
    if job_id.startswith("job_draft_"):
        return "draft"
    if provider.startswith("finch-"):
        return "finch"
    if provider.startswith("quill-"):
        return "quill"
    return "ingest"


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
    )
