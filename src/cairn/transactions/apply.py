from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Literal

from cairn.errors import CairnError, Conflict, Denied
from cairn.proposals.models import Approval
from cairn.proposals.service import load_job, load_proposal, validate_unlocked
from cairn.records.models import ID, Digest, Event, Model, canonical, digest, new_id, now
from cairn.storage.history import snapshot
from cairn.storage.workspace import Workspace


class Entry(Model):
    path: str
    before: str | None
    before_hash: Digest | None
    after: str
    after_hash: Digest


class Transaction(Model):
    schema_version: Literal[1] = 1
    id: ID
    proposal_id: ID
    proposal_hash: Digest
    approval_hash: Digest
    policy_hash: Digest
    source_id: ID
    at: datetime
    status: Literal["prepared", "committed", "rolled_back"] = "prepared"
    entries: list[Entry]


class ApplyReceipt(Model):
    schema_version: Literal[1] = 1
    id: ID
    proposal_id: ID
    proposal_hash: Digest
    approval_hash: Digest
    at: datetime
    files: dict[str, Digest]


def _crash(ws: Workspace, label: str) -> None:
    # Process-termination fault injection cannot be enabled in a private workspace.
    if ws.config.synthetic and os.environ.get("CAIRN_TEST_CRASH_AT") == label:
        os._exit(77)


def _save(ws: Workspace, tx: Transaction) -> None:
    ws.fs.write(f"journal/{tx.id}/transaction.json", canonical(tx))


def _complete(ws: Workspace, tx: Transaction) -> ApplyReceipt:
    if ws.policy_hash != tx.policy_hash:
        raise Conflict("policy changed during incomplete transaction")
    # Inspect every entry before writing any. Unexpected owner bytes are preserved.
    for entry in tx.entries:
        if digest(entry.after.encode()) != entry.after_hash or (
            entry.before is not None and digest(entry.before.encode()) != entry.before_hash
        ):
            raise Conflict("transaction journal checksum mismatch")
        current = digest(ws.fs.read(entry.path)) if ws.fs.exists(entry.path) else None
        if current not in (entry.before_hash, entry.after_hash):
            raise Conflict("recovery conflicts with an owner edit; bytes preserved")
    for index, entry in enumerate(tx.entries):
        current = digest(ws.fs.read(entry.path)) if ws.fs.exists(entry.path) else None
        if current == entry.before_hash:
            ws.fs.write(entry.path, entry.after.encode())
        elif current != entry.after_hash:
            raise Conflict("owner content changed during apply")
        _crash(ws, f"write:{index}")
    for entry in tx.entries:
        if digest(ws.fs.read(entry.path)) != entry.after_hash:
            raise Conflict("final transaction hash mismatch")
    receipt = ApplyReceipt(
        id=tx.id,
        proposal_id=tx.proposal_id,
        proposal_hash=tx.proposal_hash,
        approval_hash=tx.approval_hash,
        at=tx.at,
        files={entry.path: entry.after_hash for entry in tx.entries},
    )
    receipt_path = f"receipts/applied/{tx.proposal_id}.json"
    if ws.fs.exists(receipt_path):
        if ws.fs.read(receipt_path) != canonical(receipt):
            raise Conflict("existing receipt differs from transaction")
    else:
        ws.fs.write(receipt_path, canonical(receipt), exclusive=True)
    _crash(ws, "receipt")
    tx.status = "committed"
    _save(ws, tx)
    _crash(ws, "committed")
    event_path = f"receipts/events/event_{tx.id}.json"
    if not ws.fs.exists(event_path):
        ws.event(
            Event(
                id=f"event_{tx.id}",
                object_id=tx.source_id,
                attempt_id=tx.proposal_id,
                stage="applied",
                at=tx.at,
                hashes={"proposal": tx.proposal_hash},
            )
        )
    return receipt


def _maintenance(ws: Workspace, receipt: ApplyReceipt) -> None:
    state_path = f"receipts/maintenance/{receipt.proposal_id}.json"
    state = {"history": "pending", "index": "pending"}
    if ws.fs.exists(state_path):
        state = json.loads(ws.fs.read(state_path))
    if state["index"] == "pending":
        try:
            from cairn.retrieval.search import rebuild_unlocked

            job = load_job(ws, load_proposal(ws, receipt.proposal_id).job_id).job
            rebuild_unlocked(ws, job.scope_name)
            event_id = f"event_index_{receipt.id}"
            if not ws.fs.exists(f"receipts/events/{event_id}.json"):
                ws.event(
                    Event(
                        id=event_id,
                        object_id=job.source.id,
                        attempt_id=receipt.proposal_id,
                        stage="indexed",
                        at=now(),
                        hashes={"proposal": receipt.proposal_hash},
                    )
                )
            state["index"] = "complete"
        except (CairnError, OSError):
            state["index"] = "pending"
    if state["history"] == "pending":
        try:
            state["history"] = snapshot(ws, f"Apply {receipt.proposal_id}")
        except CairnError:
            state["history"] = "pending"
    ws.fs.write(state_path, canonical(state))
    _crash(ws, "history")


def apply(ws: Workspace, proposal_id: str) -> ApplyReceipt:
    with ws.lock(write=True):
        proposal = load_proposal(ws, proposal_id)
        receipt_path = f"receipts/applied/{proposal_id}.json"
        if ws.fs.exists(receipt_path):
            receipt = ApplyReceipt.model_validate_json(ws.fs.read(receipt_path))
            if receipt.proposal_hash != digest(canonical(proposal)):
                raise Conflict("applied proposal was altered")
            _maintenance(ws, receipt)
            return receipt
        envelope = validate_unlocked(ws, proposal)
        approval_path = f"approvals/{proposal.id}.json"
        if not ws.fs.exists(approval_path):
            raise Denied("owner approval required")
        approval = Approval.model_validate_json(ws.fs.read(approval_path))
        if (
            approval.proposal_hash != digest(canonical(proposal))
            or approval.workspace_id != ws.config.id
            or approval.proposal_id != proposal.id
            or approval.policy_hash != ws.policy_hash
            or not proposal.review_flags <= approval.acknowledgements
        ):
            raise Denied("approval does not bind this exact proposal and policy")
        tx = Transaction(
            id=new_id("transaction"),
            proposal_id=proposal.id,
            proposal_hash=approval.proposal_hash,
            approval_hash=digest(canonical(approval)),
            policy_hash=ws.policy_hash,
            source_id=envelope.job.source.id,
            at=now(),
            entries=[
                Entry(
                    path=change.path,
                    before=ws.fs.read(change.path).decode()
                    if change.base_hash is not None
                    else None,
                    before_hash=change.base_hash,
                    after=change.content,
                    after_hash=change.content_hash,
                )
                for change in proposal.changes
            ],
        )
        _save(ws, tx)
        _crash(ws, "prepared")
        receipt = _complete(ws, tx)
        _maintenance(ws, receipt)
        return receipt


def recover(ws: Workspace) -> list[ApplyReceipt]:
    recovered = []
    with ws.lock(write=True, recovery=True):
        for path in ws.fs.files("journal"):
            if not path.endswith("/transaction.json"):
                continue
            tx = Transaction.model_validate_json(ws.fs.read(path))
            if tx.status == "rolled_back":
                continue
            if tx.status == "committed":
                receipt = ApplyReceipt.model_validate_json(
                    ws.fs.read(f"receipts/applied/{tx.proposal_id}.json")
                )
                event_path = f"receipts/events/event_{tx.id}.json"
                if not ws.fs.exists(event_path):
                    ws.event(
                        Event(
                            id=f"event_{tx.id}",
                            object_id=tx.source_id,
                            attempt_id=tx.proposal_id,
                            stage="applied",
                            at=tx.at,
                            hashes={"proposal": tx.proposal_hash},
                        )
                    )
                _maintenance(ws, receipt)
                continue
            proposal = load_proposal(ws, tx.proposal_id)
            approval_raw = ws.fs.read(f"approvals/{tx.proposal_id}.json")
            if (
                digest(canonical(proposal)) != tx.proposal_hash
                or digest(approval_raw) != tx.approval_hash
                or len(tx.entries) != len(proposal.changes)
            ):
                raise Conflict("recovery authorization changed")
            for entry, change in zip(tx.entries, proposal.changes, strict=True):
                if (
                    entry.path != change.path
                    or entry.before_hash != change.base_hash
                    or entry.after_hash != change.content_hash
                    or entry.after != change.content
                ):
                    raise Conflict("journal differs from approved proposal")
            receipt = _complete(ws, tx)
            _maintenance(ws, receipt)
            recovered.append(receipt)
    return recovered
