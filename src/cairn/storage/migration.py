"""Explicit, backed-up owner migrations; ordinary reads never change formats."""

from __future__ import annotations

from pathlib import Path

from cairn.errors import CairnError, Conflict, RecoveryRequired
from cairn.policies.audit import PolicyChange, policy_changes
from cairn.policies.models import Policy
from cairn.records.json import read_json
from cairn.records.migration import (
    MigrationAuthorization,
    MigrationPlan,
    MigrationReceipt,
    MigrationTransaction,
)
from cairn.records.models import canonical, digest, now
from cairn.storage.workspace import Workspace, WorkspaceConfigV2, parse_config
from cairn.transactions.apply import _crash


def _plan(config_raw: bytes, policy_raw: bytes, inputs: dict[str, str]) -> MigrationPlan:
    config = parse_config(config_raw)
    if config.schema_version != 1:
        raise Conflict("workspace is already current; there is no migration to apply")
    if inputs.get("workspace.json") != digest(config_raw) or inputs.get(
        "policy/workspace.json"
    ) != digest(policy_raw):
        raise Conflict("migration preview does not bind its original configuration")
    migration_id = "migration_" + digest(canonical(inputs))
    updated = WorkspaceConfigV2.model_validate(
        {**config.model_dump(), "schema_version": 2, "record_schema_version": 1}
    )
    policy = Policy.model_validate(read_json(policy_raw))
    policy.revision += 1
    policy.last_change = migration_id
    return MigrationPlan(
        id=migration_id,
        workspace_id=config.id,
        input_hashes=inputs,
        before_config=config_raw.decode(),
        after_config=canonical(updated).decode(),
        before_policy=policy_raw.decode(),
        after_policy=canonical(policy).decode(),
    )


def _targets(plan: MigrationPlan) -> dict[str, tuple[bytes, bytes]]:
    return {
        "workspace.json": (plan.before_config.encode(), plan.after_config.encode()),
        "policy/workspace.json": (plan.before_policy.encode(), plan.after_policy.encode()),
    }


def _policy_change(auth: MigrationAuthorization) -> PolicyChange:
    plan = auth.plan
    return PolicyChange(
        id=plan.id,
        workspace_id=plan.workspace_id,
        at=auth.at,
        operation="schema_migration",
        before_hash=digest(plan.before_policy.encode()),
        after_hash=digest(plan.after_policy.encode()),
        before_content=plan.before_policy,
        before=Policy.model_validate(read_json(plan.before_policy.encode())),
        after=Policy.model_validate(read_json(plan.after_policy.encode())),
        owner_statement=auth.owner_statement,
    )


def _receipt(auth: MigrationAuthorization) -> MigrationReceipt:
    return MigrationReceipt(
        id=auth.plan.id,
        workspace_id=auth.plan.workspace_id,
        authorization_hash=digest(canonical(auth)),
        plan_sha256=digest(canonical(auth.plan)),
        backup_sha256=auth.backup_sha256,
        at=auth.at,
        files={path: digest(after) for path, (_, after) in _targets(auth.plan).items()},
    )


def validate_migrations(
    payloads: dict[str, bytes], workspace_id: str, *, allow_pending: bool = False
) -> dict[str, tuple[MigrationAuthorization, MigrationTransaction]]:
    """Validate historical or staged journals without trusting journal-supplied edits."""
    from cairn.storage.backup import _paths

    groups: dict[str, dict[str, bytes]] = {}
    for path, raw in payloads.items():
        if not path.startswith("migrations/"):
            continue
        parts = path.split("/")
        if len(parts) != 3 or parts[2] not in (
            "authorization.json",
            "transaction.json",
            "receipt.json",
        ):
            raise Conflict("unknown migration artifact")
        groups.setdefault(parts[1], {})[parts[2]] = raw
    transactions = {}
    for migration_id, files in groups.items():
        if "authorization.json" not in files:
            raise Conflict("migration omits owner authorization")
        auth = MigrationAuthorization.model_validate(read_json(files["authorization.json"]))
        plan = auth.plan
        _paths(list(plan.input_hashes))
        if (
            plan.id != migration_id
            or plan.workspace_id != workspace_id
            or plan
            != _plan(plan.before_config.encode(), plan.before_policy.encode(), plan.input_hashes)
            or canonical(auth) != files["authorization.json"]
        ):
            raise Conflict("migration differs from the supported, approved transformation")
        if "transaction.json" not in files:
            # A crash during preparation can leave an unused, immutable authorization.
            if "receipt.json" in files:
                raise Conflict("migration receipt has no transaction")
            continue
        tx = MigrationTransaction.model_validate(read_json(files["transaction.json"]))
        policy_path = f"receipts/policy/{migration_id}.json"
        if (
            tx.id != plan.id
            or tx.workspace_id != workspace_id
            or tx.authorization_hash != digest(canonical(auth))
            or payloads.get(policy_path) != canonical(_policy_change(auth))
            or tx.policy_change_hash != digest(canonical(_policy_change(auth)))
        ):
            raise Conflict("migration authorization or policy audit changed")
        if "receipt.json" in files and files["receipt.json"] != canonical(_receipt(auth)):
            raise Conflict("migration receipt differs from authorization")
        if tx.status == "committed" and "receipt.json" not in files:
            raise Conflict("committed migration omits its receipt")
        if tx.status == "prepared" and not allow_pending:
            raise RecoveryRequired("recover the schema migration before creating a new backup")
        transactions[migration_id] = (auth, tx)
    return transactions


def inspect(ws: Workspace) -> dict[str, object]:
    from cairn.storage.backup import durable_contents, validate_payloads

    with ws.lock():
        contents = durable_contents(ws)
        config = validate_payloads(contents)
        return {
            "workspace_id": config.id,
            "workspace_schema": config.schema_version,
            "record_schema": 1,
            "supported_workspace_schemas": [1, 2],
            "current_workspace_schema": 2,
            "records_validated": len(ws.records()),
            "migration_available": config.schema_version == 1,
            "writes_performed": False,
        }


def _preview_unlocked(ws: Workspace) -> MigrationPlan:
    from cairn.storage.backup import durable_contents, validate_payloads

    contents = durable_contents(ws)
    validate_payloads(contents)
    return _plan(
        contents["workspace.json"],
        contents["policy/workspace.json"],
        {path: digest(raw) for path, raw in contents.items()},
    )


def preview(ws: Workspace) -> MigrationPlan:
    with ws.lock():
        return _preview_unlocked(ws)


def _complete(
    ws: Workspace, auth: MigrationAuthorization, tx: MigrationTransaction
) -> MigrationReceipt:
    from cairn.storage.backup import durable_contents

    plan = auth.plan
    directory = f"migrations/{plan.id}"
    current = durable_contents(ws)
    validated = validate_migrations(current, ws.config.id, allow_pending=True)
    if validated.get(plan.id) != (auth, tx):
        raise Conflict("migration journal changed")
    policy_changes(ws.policy_hash, ws.policy, ws.fs.read, ws.config.id)
    targets = _targets(plan)
    # Inspect ALL inputs and targets before the first replacement. The two target
    # paths and their exact transformation are derived by the owner runtime.
    observed = {path: digest(raw) for path, raw in current.items()}
    for suffix in ("authorization.json", "transaction.json", "receipt.json"):
        observed.pop(f"{directory}/{suffix}", None)
    observed.pop(f"receipts/policy/{plan.id}.json", None)
    for path, (before, after) in targets.items():
        if current.get(path) not in (before, after):
            raise Conflict("migration recovery conflicts with an owner edit; bytes preserved")
        observed[path] = digest(before)
    if observed != plan.input_hashes:
        raise Conflict("migration input changed; owner bytes preserved")
    for index, (path, (before, after)) in enumerate(targets.items()):
        actual = ws.fs.read(path)
        if actual == before:
            ws.fs.write(path, after)
        elif actual != after:
            raise Conflict("owner content changed during migration")
        _crash(ws, f"migration:write:{index}")
    receipt = _receipt(auth)
    for path, expected in receipt.files.items():
        if digest(ws.fs.read(path)) != expected:
            raise Conflict("migration final checksum mismatch")
    receipt_path = f"{directory}/receipt.json"
    if not ws.fs.exists(receipt_path):
        ws.fs.write(receipt_path, canonical(receipt), exclusive=True)
    elif ws.fs.read(receipt_path) != canonical(receipt):
        raise Conflict("migration receipt changed")
    _crash(ws, "migration:receipt")
    tx.status = "committed"
    ws.fs.write(f"{directory}/transaction.json", canonical(tx))
    ws.config = parse_config(ws.fs.read("workspace.json"))
    _crash(ws, "migration:committed")
    return receipt


def _maintenance(ws: Workspace, receipt: MigrationReceipt) -> None:
    from cairn.storage.history import snapshot

    path = f"receipts/maintenance/{receipt.id}.json"
    if ws.fs.exists(path):
        state = read_json(ws.fs.read(path))
        if not isinstance(state, dict) or not isinstance(state.get("history"), str):
            raise Conflict("invalid migration maintenance state")
        if state["history"] != "pending":
            return
    # Retryable after the commit marker; history failure cannot undo a migration.
    ws.fs.write(path, canonical({"history": "pending"}))
    try:
        commit = snapshot(ws, f"Schema migration {receipt.id}")
    except CairnError:
        return
    ws.fs.write(path, canonical({"history": commit}))
    _crash(ws, "migration:history")


def apply(
    ws: Workspace, *, plan_sha256: str, backup_path: Path, statement: str
) -> MigrationReceipt:
    from cairn.storage.backup import backup_unlocked

    if not statement.strip() or len(statement) > 4000:
        raise CairnError(
            "migration requires an explicit owner statement of at most 4000 characters"
        )
    with ws.lock(write=True):
        plan = _preview_unlocked(ws)
        if digest(canonical(plan)) != plan_sha256:
            raise Conflict("migration preview is stale or changed; inspect a fresh preview")
        # A failed/existing backup destination prevents all workspace mutations.
        backed_up = backup_unlocked(ws, backup_path)
        _crash(ws, "migration:backup")
        auth = MigrationAuthorization(
            plan=plan,
            backup_sha256=str(backed_up["sha256"]),
            at=now(),
            owner_statement=statement,
        )
        change = _policy_change(auth)
        directory = f"migrations/{plan.id}"
        ws.fs.write(f"{directory}/authorization.json", canonical(auth), exclusive=True)
        _crash(ws, "migration:authorization")
        ws.fs.write(f"receipts/policy/{plan.id}.json", canonical(change), exclusive=True)
        _crash(ws, "migration:policy_intent")
        tx = MigrationTransaction(
            id=plan.id,
            workspace_id=plan.workspace_id,
            authorization_hash=digest(canonical(auth)),
            policy_change_hash=digest(canonical(change)),
        )
        ws.fs.write(f"{directory}/transaction.json", canonical(tx), exclusive=True)
        _crash(ws, "migration:prepared")
        receipt = _complete(ws, auth, tx)
        _maintenance(ws, receipt)
        return receipt


def recover(ws: Workspace) -> list[MigrationReceipt]:
    from cairn.storage.backup import durable_contents

    with ws.lock(write=True, recovery=True):
        # A schema migration is never allowed to overlap a synthesis transaction.
        from cairn.transactions.apply import Transaction

        for path in ws.fs.files("journal"):
            tx = Transaction.model_validate(read_json(ws.fs.read(path)))
            if tx.status == "prepared":
                raise RecoveryRequired("recover the synthesis transaction before schema migration")
        journals = validate_migrations(durable_contents(ws), ws.config.id, allow_pending=True)
        pending = [(auth, tx) for auth, tx in journals.values() if tx.status == "prepared"]
        if len(pending) > 1:
            raise Conflict("multiple pending schema migrations; no files were changed")
        recovered = [_complete(ws, auth, tx) for auth, tx in pending]
        for auth, _ in journals.values():
            _maintenance(ws, _receipt(auth))
        return recovered
