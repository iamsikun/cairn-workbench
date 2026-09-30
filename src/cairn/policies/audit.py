from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Literal

from pydantic import Field

from cairn.errors import Blocked, CairnError, Conflict, Denied
from cairn.policies.models import Operation, Policy, RouteGrant, Scope
from cairn.records.json import read_json
from cairn.records.models import ID, Digest, Labels, Model, Record, canonical, digest, new_id, now
from cairn.storage.workspace import Workspace


class PolicyChange(Model):
    schema_version: Literal[1] = 1
    id: ID
    workspace_id: ID
    at: datetime
    operation: Literal["set_scope", "set_grant", "revoke_grant"]
    before_hash: Digest
    after_hash: Digest
    before_content: str
    before: Policy
    after: Policy
    owner_statement: str = Field(min_length=1, max_length=4000)


class RequestPart(Model):
    role: Literal["instructions", "derived_metadata", "output_handling", "traces"]
    content: str = Field(max_length=200000)
    labels: Labels | None = None


class RouteRequest(Model):
    schema_version: Literal[1] = 1
    scope: ID
    route: Literal["local", "cloud"]
    provider: str = Field(min_length=1, max_length=200)
    destination: str = "local"
    operation: Operation
    record_ids: list[ID] = Field(default_factory=list, max_length=100)
    question: str = Field(max_length=20000)
    question_labels: Labels | None = None
    parts: list[RequestPart] = Field(default_factory=list, max_length=20)


class RouteAudit(Model):
    schema_version: Literal[1] = 1
    id: ID
    workspace_id: ID
    at: datetime
    policy_hash: Digest
    scope: ID
    requested_route: Literal["local", "cloud"]
    provider: str
    destination: str
    operation: Operation
    request_hash: Digest
    input_hashes: dict[ID, Digest]
    decision: Literal["allowed", "denied", "blocked"]
    reason: str
    payload_hash: Digest | None = None
    execution_performed: Literal[False] = False


def _change_policy(
    ws: Workspace,
    *,
    base_hash: str,
    statement: str,
    operation: Literal["set_scope", "set_grant", "revoke_grant"],
    update: Callable[[Policy], None],
) -> PolicyChange:
    if not statement.strip():
        raise CairnError("policy changes require an explicit owner statement")
    with ws.lock(write=True):
        if base_hash != ws.policy_hash:
            raise Conflict("policy changed; inspect its current hash before editing")
        before = ws.policy
        policy_changes(ws.policy_hash, before, ws.fs.read, ws.config.id)
        before_content = ws.fs.read("policy/workspace.json").decode()
        after = before.model_copy(deep=True)
        update(after)
        after.revision += 1
        change_id = new_id("policychange")
        after.last_change = change_id
        after = Policy.model_validate(after.model_dump())
        change = PolicyChange(
            id=change_id,
            workspace_id=ws.config.id,
            at=now(),
            operation=operation,
            before_hash=base_hash,
            after_hash=digest(canonical(after)),
            before_content=before_content,
            before=before,
            after=after,
            owner_statement=statement,
        )
        # The policy points to a prewritten audit object. A crash before replacing
        # policy leaves an unapplied intent; a committed change always has its evidence.
        ws.fs.write(f"receipts/policy/{change.id}.json", canonical(change), exclusive=True)
        ws.fs.write("policy/workspace.json", canonical(after))
        return change


def set_scope(ws: Workspace, scope: Scope, *, base_hash: str, statement: str) -> PolicyChange:
    def update(policy: Policy) -> None:
        policy.scopes[scope.name] = scope
        # Consent to a named scope must not silently cover a changed membership.
        policy.cloud_grants = [grant for grant in policy.cloud_grants if grant.scope != scope.name]

    return _change_policy(
        ws, base_hash=base_hash, statement=statement, operation="set_scope", update=update
    )


def set_grant(ws: Workspace, grant: RouteGrant, *, base_hash: str, statement: str) -> PolicyChange:
    if grant.valid_until <= now():
        raise Denied("a new cloud grant must have a future expiry")
    if grant.owner_consent != statement:
        raise Denied("grant consent must match the explicit owner statement")

    def update(policy: Policy) -> None:
        policy.cloud_grants = [item for item in policy.cloud_grants if item.id != grant.id] + [
            grant
        ]

    return _change_policy(
        ws, base_hash=base_hash, statement=statement, operation="set_grant", update=update
    )


def revoke_grant(ws: Workspace, grant_id: str, *, base_hash: str, statement: str) -> PolicyChange:
    def update(policy: Policy) -> None:
        if not any(grant.id == grant_id for grant in policy.cloud_grants):
            raise Denied("grant unavailable")
        policy.cloud_grants = [grant for grant in policy.cloud_grants if grant.id != grant_id]

    return _change_policy(
        ws, base_hash=base_hash, statement=statement, operation="revoke_grant", update=update
    )


def policy_changes(
    checksum: str,
    policy: Policy,
    read: Callable[[str], bytes],
    workspace_id: str,
) -> set[str]:
    """Check an installed or staged policy chain without mutating it."""
    chain: set[str] = set()
    change_id = policy.last_change
    while change_id:
        if change_id in chain:
            raise Conflict("policy audit chain contains a cycle")
        change = PolicyChange.model_validate(read_json(read(f"receipts/policy/{change_id}.json")))
        if (
            change.id != change_id
            or change.workspace_id != workspace_id
            or change.after.last_change != change_id
            or change.after.revision != change.before.revision + 1
            or change.after_hash != checksum
            or digest(canonical(change.after)) != checksum
            or digest(change.before_content.encode()) != change.before_hash
            or Policy.model_validate(read_json(change.before_content.encode())) != change.before
        ):
            raise Conflict("policy audit chain checksum mismatch")
        chain.add(change_id)
        checksum = change.before_hash
        change_id = change.before.last_change
    return chain


def inspect_changes(ws: Workspace) -> list[dict[str, str]]:
    with ws.lock():
        chain = policy_changes(ws.policy_hash, ws.policy, ws.fs.read, ws.config.id)
        result = []
        for path in ws.fs.files("receipts/policy"):
            change = PolicyChange.model_validate(read_json(ws.fs.read(path)))
            if change.workspace_id != ws.config.id or path != f"receipts/policy/{change.id}.json":
                raise Conflict("policy audit workspace or identity mismatch")
            result.append(
                {
                    "id": change.id,
                    "operation": change.operation,
                    "state": "applied" if change.id in chain else "unapplied_intent",
                }
            )
        return result


def route_audit_unlocked(
    ws: Workspace,
    *,
    scope_name: str,
    records: Sequence[Record],
    operation: Operation,
    provider: str,
    route: Literal["local", "cloud"] = "local",
    destination: str = "local",
    question: str = "",
    question_labels: Labels | None = None,
    parts: Sequence[RequestPart] = (),
    persist: bool = True,
    payload_hash: str | None = None,
    unavailable_inputs: bool = False,
) -> RouteAudit:
    policy = ws.policy
    unknown = Labels(domain="shared", classification="restricted")
    decision: Literal["allowed", "denied", "blocked"] = "allowed"
    reason = "policy_allows_local_processing; operation has not executed"
    hashes = {record.id: digest(canonical(record)) for record in records}
    try:
        scope = policy.scope(scope_name)
        if unavailable_inputs:
            raise Denied("record unavailable in this scope")
        policy.authorize_route(
            scope,
            records,
            route=route,
            provider=provider,
            operation=operation,
            destination=destination,
            question=question_labels,
            extra_parts=[part.labels or unknown for part in parts],
        )
        if route == "cloud":
            decision, reason = "blocked", "cloud_adapter_unavailable; no transmission performed"
    except Denied as exc:
        decision, reason = "denied", str(exc)
    audit = RouteAudit(
        id=new_id("routeaudit"),
        workspace_id=ws.config.id,
        at=now(),
        policy_hash=ws.policy_hash,
        scope=scope_name,
        requested_route=route,
        provider=provider,
        destination=destination,
        operation=operation,
        request_hash=digest(
            canonical(
                {
                    "workspace": ws.config.id,
                    "inputs": hashes,
                    "policy": ws.policy_hash,
                    "scope": scope_name,
                    "operation": operation,
                    "route": route,
                    "provider": provider,
                    "destination": destination,
                    "question": question,
                    "question_labels": question_labels,
                    "parts": parts,
                    "payload_hash": payload_hash,
                }
            )
        ),
        payload_hash=payload_hash,
        input_hashes=hashes,
        decision=decision,
        reason=reason,
    )
    if persist:
        ws.fs.write(f"receipts/routes/{audit.id}.json", canonical(audit), exclusive=True)
    return audit


def require_local_route_unlocked(
    ws: Workspace,
    *,
    scope_name: str,
    records: Sequence[Record],
    operation: Operation,
    provider: str,
    persist: bool = True,
    payload_hash: str | None = None,
) -> RouteAudit:
    audit = route_audit_unlocked(
        ws,
        scope_name=scope_name,
        records=records,
        operation=operation,
        provider=provider,
        persist=persist,
        payload_hash=payload_hash,
    )
    if audit.decision == "denied":
        raise Denied(audit.reason)
    if audit.decision == "blocked":
        raise Blocked(audit.reason)
    return audit


def check_route(ws: Workspace, request: RouteRequest) -> RouteAudit:
    # This command audits a hypothetical complete request. It never runs an adapter.
    from cairn.proposals.service import all_refs

    with ws.lock(write=True):
        records = []
        unavailable = False
        try:
            scope = ws.policy.scope(request.scope)
            records = [ws.record(record_id, scope)[1] for record_id in request.record_ids]
            cited = {ref.id for record in records for ref in all_refs(record)}
            records += [
                ws.record(record_id, scope)[1]
                for record_id in sorted(cited)
                if record_id not in request.record_ids
            ]
        except Denied:
            records, unavailable = [], True
        return route_audit_unlocked(
            ws,
            scope_name=request.scope,
            records=records,
            operation=request.operation,
            provider=request.provider,
            route=request.route,
            destination=request.destination,
            question=request.question,
            question_labels=request.question_labels,
            parts=request.parts,
            payload_hash=digest(canonical(request)),
            unavailable_inputs=unavailable,
        )
