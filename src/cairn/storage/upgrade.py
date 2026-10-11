"""Legacy authorization readers and revocation; runtime upgrades are retired."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from cairn.adapters.legacy import retired
from cairn.errors import Conflict
from cairn.records.json import read_json
from cairn.records.models import canonical, now
from cairn.records.runtime import (
    UpdateAuthorization,
    UpdateRevocation,
)
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


def enable(ws: Workspace, *, repository: str, ref: str, statement: str) -> UpdateAuthorization:
    retired("Legacy automatic-update authorization")


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
    retired("Legacy runtime rebinding")
