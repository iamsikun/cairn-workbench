"""One owner step from a validated proposal to applied content; batchable.

This composes validate, approve and apply without weakening any of them. Each proposal
still gets its own sealed approval and journaled transaction. Only the owner CLI calls
this; a proposal, packet or model response never carries acceptance authority.
"""

from __future__ import annotations

from cairn.errors import CairnError, Denied
from cairn.proposals.models import Proposal
from cairn.proposals.service import approve, load_proposal, validate, validate_unlocked
from cairn.records.models import Model
from cairn.storage.markdown import decode
from cairn.storage.workspace import Workspace
from cairn.transactions.apply import apply

DEFAULT_STATEMENT = "Owner accepted via cairn accept"
# Batch selection never includes these; the owner must name such proposals explicitly.
EXPLICIT_ONLY = frozenset({"sensitive_record", "decision_review", "owner_adoption"})


class AcceptItem(Model):
    proposal_id: str
    titles: list[str]
    paths: list[str]
    review_flags: list[str]
    status: str
    reason: str | None = None
    receipt_id: str | None = None


def _applied(ws: Workspace, proposal_id: str) -> bool:
    return ws.fs.exists(f"receipts/applied/{proposal_id}.json")


def _item(proposal: Proposal, status: str, reason: str | None = None) -> AcceptItem:
    records = [decode(change.content.encode())[0] for change in proposal.changes]
    return AcceptItem(
        proposal_id=proposal.id,
        titles=[f"{r.type}: {r.title}" for r in records],
        paths=[change.path for change in proposal.changes],
        review_flags=sorted(proposal.review_flags),
        status=status,
        reason=reason,
    )


def pending(ws: Workspace) -> list[Proposal]:
    """Unapplied proposals in creation order."""
    with ws.lock():
        proposals = [
            load_proposal(ws, path.removeprefix("proposals/").removesuffix(".json"))
            for path in ws.fs.files("proposals")
            if path.count("/") == 1 and path.endswith(".json")
        ]
    return sorted(
        (p for p in proposals if not _applied(ws, p.id)), key=lambda p: (p.created_at, p.id)
    )


def plan(ws: Workspace, proposal_ids: list[str] | None) -> list[AcceptItem]:
    """Read-only preview. Explicit IDs must be acceptable; batch selection skips others."""
    explicit = proposal_ids is not None
    proposals = (
        [load_proposal(ws, key) for key in dict.fromkeys(proposal_ids or [])]
        if explicit
        else pending(ws)
    )
    items = []
    for proposal in proposals:
        if _applied(ws, proposal.id):
            items.append(_item(proposal, "applied"))
            continue
        if not explicit and proposal.review_flags & EXPLICIT_ONLY:
            items.append(_item(proposal, "skipped", "requires explicit owner selection"))
            continue
        try:
            with ws.lock():
                validate_unlocked(ws, proposal)
        except CairnError as exc:
            if explicit:
                raise
            items.append(_item(proposal, "skipped", f"{exc.code}: {exc}"))
            continue
        items.append(_item(proposal, "ready"))
    return items


def accept(
    ws: Workspace, items: list[AcceptItem], *, statement: str = DEFAULT_STATEMENT
) -> list[AcceptItem]:
    """Validate, approve and apply each ready item in order; stop at the first failure."""
    if not statement.strip():
        raise Denied("owner review statement is required")
    results = []
    failed = False
    for item in items:
        if item.status != "ready":
            results.append(item)
            continue
        if failed:
            results.append(item.model_copy(update={"status": "not_attempted"}))
            continue
        try:
            proposal = validate(ws, item.proposal_id)
            if sorted(proposal.review_flags) != item.review_flags:
                raise Denied("review flags changed after the owner preview")
            approve(
                ws, proposal.id, acknowledgements=set(proposal.review_flags), statement=statement
            )
            receipt = apply(ws, proposal.id)
        except CairnError as exc:
            # Earlier items stay applied: each one is its own recoverable transaction.
            failed = True
            results.append(
                item.model_copy(update={"status": "failed", "reason": f"{exc.code}: {exc}"})
            )
            continue
        results.append(item.model_copy(update={"status": "applied", "receipt_id": receipt.id}))
    return results
