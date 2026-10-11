"""Historical upgrade chains remain validated; new upgrades cannot run."""


import pytest
from pydantic import ValidationError
from test_activation import reviewed_fixture as reviewed_fixture

from cairn.errors import Blocked, Denied
from cairn.records.models import canonical, now
from cairn.records.runtime import (
    PROBE_CHECKS,
    REQUIRED_REVIEWS,
    ProbeResult,
    RuntimeApproval,
    UpdateAuthorization,
    WorkerProfile,
)
from cairn.storage import activation, upgrade
from cairn.storage.backup import validate_payloads
from cairn.storage.streaming_backup import durable_contents
from cairn.storage.workspace import Workspace


def test_historical_upgrade_chain_and_revocation(reviewed_fixture, tmp_path):
    ws = Workspace.init(tmp_path / "legacy", code_roots=[tmp_path / "code"], **reviewed_fixture)
    previous = activation.read_approval(ws.config.runtime_approval_id, ws.fs.read)
    auth = UpdateAuthorization(
        id="update_synthetic", workspace_id=ws.config.id, at=now(),
        repository="https://example.invalid/synthetic", ref="stable",
        owner_statement="Synthetic historical consent.",
    )
    ws.fs.write(f"receipts/updates/{auth.id}.json", canonical(auth))
    approved = RuntimeApproval(
        id="runtime_upgrade", workspace_id=ws.config.id, at=now(), operation="upgrade",
        release_hash=previous.release_hash, owner_statement="Synthetic historical upgrade.",
        acknowledgements=set(), worker=previous.worker, previous_approval_id=previous.id,
        update_authorization_id=auth.id, release_tag="v0.3.0", backup_sha256="5" * 64,
    )
    ws.fs.write(f"receipts/runtime/{approved.id}.json", canonical(approved))
    ws.config.runtime_approval_id = approved.id
    ws.fs.write("workspace.json", canonical(ws.config))
    reopened = Workspace(ws.root)
    validate_payloads(durable_contents(reopened))
    assert upgrade.active_authorization(reopened) == auth
    assert upgrade.disable(reopened, statement="Synthetic stop").authorization_id == auth.id
    assert upgrade.active_authorization(reopened) is None
    # A later revocation preserves the validity of an earlier historical adoption.
    Workspace(ws.root)
    forged = approved.model_copy(update={"update_authorization_id": "update_forged"})
    ws.fs.write(f"receipts/runtime/{approved.id}.json", canonical(forged))
    with pytest.raises((Denied, FileNotFoundError)):
        Workspace(ws.root)


def test_rebind_and_enable_retired_before_access(tmp_path):
    with pytest.raises(Blocked, match="retired"):
        upgrade.enable(None, repository="unused", ref="stable", statement="unused")
    with pytest.raises(Blocked, match="retired"):
        upgrade.rebind(
            tmp_path / "absent", release=tmp_path / "missing", release_sha256="0" * 64,
            mirror=tmp_path / "mirror", tag="v0.5.0", backup_dir=tmp_path / "backup",
        )
    assert list(tmp_path.iterdir()) == []


def test_upgrade_approval_shape_is_enforced() -> None:
    worker = WorkerProfile(
        id="profile_synthetic",
        at=now(),
        image="sha256:" + "2" * 64,
        profile_hash="3" * 64,
        result=ProbeResult(nonce="0" * 32, checks=dict.fromkeys(PROBE_CHECKS, True)),
    )
    base = {
        "id": "runtime_synthetic",
        "workspace_id": "workspace_synthetic",
        "at": now(),
        "release_hash": "4" * 64,
        "owner_statement": "Synthetic.",
        "worker": worker,
    }
    with pytest.raises(ValidationError):
        RuntimeApproval(operation="upgrade", acknowledgements=set(), **base)
    with pytest.raises(ValidationError):
        RuntimeApproval(
            operation="init",
            acknowledgements=REQUIRED_REVIEWS,
            release_tag="v1.0.0",
            **base,
        )
    with pytest.raises(ValidationError):
        RuntimeApproval(
            operation="upgrade",
            acknowledgements=REQUIRED_REVIEWS,
            previous_approval_id="runtime_previous",
            update_authorization_id="update_synthetic",
            release_tag="v1.0.0",
            backup_sha256="5" * 64,
            **base,
        )
