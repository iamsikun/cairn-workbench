"""Owner-authorized runtime upgrade of a private workspace.

A workspace stays bound to one exact release. Rebinding it to a newer release is an
owner maintenance operation authorized once, in advance, by an `UpdateAuthorization`
stored in the workspace. Each rebind is run by the new installed runtime, which must
verify itself, re-verify the signed release tag against the workspace's own signer
list, recompute the source hash from the signed tree, pass a fresh worker probe, and
take a backup before the configuration (the single commit point) names the new release.
Schema migrations then run automatically with their own mandatory backup.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from cairn.errors import CairnError, Conflict, Denied
from cairn.ingest.service import read_source_file
from cairn.records.json import read_json
from cairn.records.models import canonical, digest, new_id, now
from cairn.records.release import ReleaseManifest
from cairn.records.runtime import (
    RuntimeApproval,
    UpdateAuthorization,
    UpdateRevocation,
    tag_version,
)
from cairn.storage.activation import check_runtime_metadata, check_worker, release_path
from cairn.storage.release import verify_runtime
from cairn.storage.workspace import Workspace

UPDATES = "receipts/updates"


def backup_name(backup_dir: Path, ws: Workspace, label: str) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return backup_dir / ws.config.id / f"{stamp}-{label}-{uuid4().hex[:8]}.zip"


def revocation_path(authorization_id: str) -> str:
    return f"{UPDATES}/revocations/{authorization_id}.json"


def authorizations(ws: Workspace) -> list[UpdateAuthorization]:
    found = []
    for path in ws.fs.files(UPDATES):
        if path.count("/") != 2:
            continue
        item = UpdateAuthorization.model_validate(read_json(ws.fs.read(path)))
        if path != f"{UPDATES}/{item.id}.json" or item.workspace_id != ws.config.id:
            raise Conflict("update authorization identity mismatch")
        found.append(item)
    return found


def active_authorization(ws: Workspace) -> UpdateAuthorization | None:
    active = [item for item in authorizations(ws) if not ws.fs.exists(revocation_path(item.id))]
    if len(active) > 1:
        raise Conflict("more than one active update authorization")
    return active[0] if active else None


def enable(
    ws: Workspace, *, repository: str, ref: str, allowed_signers: list[str], statement: str
) -> UpdateAuthorization:
    """Record the owner's standing consent to adopt releases signed by these keys."""
    if ws.config.synthetic:
        raise Denied("automatic updates apply to private workspaces")
    with ws.lock(write=True):
        if active_authorization(ws) is not None:
            raise Conflict("automatic updates are already enabled; disable them first")
        authorization = UpdateAuthorization(
            id=new_id("update"),
            workspace_id=ws.config.id,
            at=now(),
            repository=repository,
            ref=ref,
            allowed_signers=allowed_signers,
            owner_statement=statement,
        )
        ws.fs.write(f"{UPDATES}/{authorization.id}.json", canonical(authorization), exclusive=True)
        return authorization


def disable(ws: Workspace, *, statement: str) -> UpdateRevocation | None:
    """Stop future upgrades; the current binding and its history remain valid."""
    with ws.lock(write=True):
        authorization = active_authorization(ws)
        if authorization is None:
            return None
        revocation = UpdateRevocation(
            authorization_id=authorization.id,
            workspace_id=ws.config.id,
            at=now(),
            owner_statement=statement,
        )
        ws.fs.write(revocation_path(authorization.id), canonical(revocation), exclusive=True)
        return revocation


def rebind(
    root: Path,
    *,
    release: Path,
    release_sha256: str,
    mirror: Path,
    tag: str,
    backup_dir: Path,
) -> dict[str, object]:
    from cairn.storage.streaming_backup import backup_unlocked
    from cairn.updater.source import verify_release

    raw = read_source_file(release)
    if digest(raw) != release_sha256:
        raise Conflict("release manifest differs from the verified build")
    manifest = ReleaseManifest.model_validate(read_json(raw))
    verify_runtime(manifest)  # This process must be the new, verified installation.
    ws = Workspace(root, _upgrading=True)
    if ws.config.synthetic:
        raise Denied("automatic updates apply to private workspaces")
    if ws.config.runtime_release_hash == release_sha256:
        return {"workspace_id": ws.config.id, "status": "current", "release_tag": tag}
    with ws.lock(write=True):
        _, previous = check_runtime_metadata(ws.config, ws.fs.read)
        authorization = active_authorization(ws)
        if authorization is None:
            raise Denied("automatic updates are not enabled for this workspace")
        verified = verify_release(mirror, tag, authorization.ref, authorization.allowed_signers)
        if verified.commit != manifest.code_revision or verified.source_hash != (
            manifest.source_hash
        ):
            raise Conflict("release manifest does not match the signed source")
        if previous.release_tag and tag_version(tag) <= tag_version(previous.release_tag):
            raise Denied("automatic updates never move to an older or equal release")
        worker = check_worker(manifest.worker_image)
        backed_up = backup_unlocked(ws, backup_name(backup_dir, ws, f"before-{tag}"))
        approval = RuntimeApproval(
            id=new_id("runtime"),
            workspace_id=ws.config.id,
            at=now(),
            operation="upgrade",
            release_hash=release_sha256,
            owner_statement=(
                f"Automatic update to {tag} under owner authorization {authorization.id}."
            ),
            acknowledgements=set(),
            worker=worker,
            previous_approval_id=previous.id,
            update_authorization_id=authorization.id,
            release_tag=tag,
            release_signer=verified.signer,
            backup_sha256=str(backed_up["sha256"]),
        )
        path = release_path(release_sha256)
        if ws.fs.exists(path):
            if ws.fs.read(path) != raw:
                raise Conflict("stored release manifest differs")
        else:
            ws.fs.write(path, raw, exclusive=True)
        ws.fs.write(f"receipts/runtime/{approval.id}.json", canonical(approval), exclusive=True)
        config = ws.config.model_copy(
            update={
                "runtime_release_hash": release_sha256,
                "runtime_approval_id": approval.id,
                "worker_image": manifest.worker_image,
            }
        )
        # Replacing the configuration is the commit point: an interruption before it
        # leaves unreferenced receipts and the previous, still valid binding.
        ws.fs.write("workspace.json", canonical(config))
    upgraded = Workspace(root)
    result: dict[str, object] = {
        "workspace_id": upgraded.config.id,
        "status": "upgraded",
        "release_tag": tag,
        "runtime_approval_id": approval.id,
        "backup_sha256": backed_up["sha256"],
        "history": _history(upgraded, f"Runtime upgrade to {tag} ({approval.id})"),
        "migrations": migrate(upgraded, backup_dir, authorization, tag),
    }
    return result


def _history(ws: Workspace, message: str) -> str:
    from cairn.storage.history import snapshot

    try:
        return snapshot(ws, message)
    except CairnError:
        return "pending"


def migrate(
    ws: Workspace, backup_dir: Path, authorization: UpdateAuthorization, tag: str
) -> list[str]:
    """Apply supported format migrations, each with its own mandatory backup."""
    from cairn.storage import migration

    applied = []
    while migration.inspect(ws)["migration_available"]:
        plan = migration.preview(ws)
        receipt = migration.apply(
            ws,
            plan_sha256=digest(canonical(plan)),
            backup_path=backup_name(backup_dir, ws, f"before-{plan.id}"),
            statement=(
                f"Automatic migration during update to {tag} under owner authorization "
                f"{authorization.id}; pending proposals are invalidated and regenerated."
            ),
        )
        applied.append(receipt.id)
        ws = Workspace(ws.root)
    return applied
