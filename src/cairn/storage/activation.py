from __future__ import annotations

import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal
from uuid import uuid4

from cairn.adapters.isolation import container_command, invoke_worker
from cairn.errors import Blocked, Conflict, Denied
from cairn.records.json import read_json
from cairn.records.models import canonical, digest, new_id, now
from cairn.records.release import ReleaseManifest
from cairn.records.runtime import (
    REQUIRED_REVIEWS,
    ProbeRequest,
    ProbeResult,
    ReviewAcknowledgement,
    RuntimeApproval,
    UpdateAuthorization,
    WorkerProfile,
)
from cairn.storage.release import load_release, verify_runtime

if TYPE_CHECKING:
    from cairn.storage.workspace import WorkspaceConfiguration


def check_worker(image: str) -> WorkerProfile:
    """Fresh probe through the actual launcher, with no private input or owner mounts."""
    nonce = uuid4().hex
    with tempfile.TemporaryDirectory(prefix="cairn-synthetic-probe-") as temporary:
        canary = Path(temporary) / "canary"
        original = b"Cairn synthetic isolation canary: " + nonce.encode()
        canary.write_bytes(original)
        request = ProbeRequest(nonce=nonce, canary_path=str(canary))
        result = ProbeResult.model_validate(read_json(invoke_worker(image, canonical(request))))
        if result.nonce != nonce or not all(result.checks.values()):
            raise Blocked("isolation_probe_failed_or_stale")
        if not canary.is_file() or canary.is_symlink() or canary.read_bytes() != original:
            raise Blocked("isolation_probe_modified_host_canary")
    return WorkerProfile(
        id=new_id("profile"),
        at=now(),
        image=image,
        profile_hash=digest(canonical(container_command(image))),
        result=result,
    )


@dataclass(frozen=True)
class PreparedActivation:
    raw_manifest: bytes
    manifest: ReleaseManifest
    owner_statement: str
    acknowledgements: set[ReviewAcknowledgement]
    worker: WorkerProfile

    def approval(
        self,
        workspace_id: str,
        operation: Literal["init", "restore"],
        archive_hash: str | None = None,
    ) -> RuntimeApproval:
        return RuntimeApproval(
            id=new_id("runtime"),
            workspace_id=workspace_id,
            at=now(),
            operation=operation,
            release_hash=digest(self.raw_manifest),
            owner_statement=self.owner_statement,
            acknowledgements=self.acknowledgements,
            worker=self.worker,
            archive_hash=archive_hash,
        )


def prepare_activation(
    file: Path | None,
    *,
    expected_sha256: str | None,
    statement: str | None,
    acknowledgements: set[ReviewAcknowledgement] | None,
) -> PreparedActivation:
    if (
        file is None
        or expected_sha256 is None
        or not statement
        or not statement.strip()
        or acknowledgements != REQUIRED_REVIEWS
    ):
        raise Denied(
            "private activation requires a reviewed release, statement, "
            "and all review acknowledgements"
        )
    manifest = load_release(file, expected_sha256=expected_sha256)
    verify_runtime(manifest)
    # Keep the exact reviewed bytes, including external formatting; check again before
    # using them to bind a new workspace rather than assuming the file stayed unchanged.
    from cairn.ingest.service import read_source_file

    raw = read_source_file(file)
    if digest(raw) != expected_sha256:
        raise Conflict("release manifest changed during verification")
    worker = check_worker(manifest.worker_image)
    return PreparedActivation(raw, manifest, statement, acknowledgements, worker)


LEGACY_RELEASE = "policy/runtime-release.json"
MAX_UPGRADE_CHAIN = 10000


def release_path(release_hash: str) -> str:
    """Upgrades keep every adopted manifest; the configuration selects one by digest."""
    return f"policy/runtime-releases/{release_hash}.json"


def _optional(read: Callable[[str], bytes], path: str) -> bytes | None:
    try:
        return read(path)
    except (FileNotFoundError, KeyError):
        return None


def read_release_manifest(release_hash: str, read: Callable[[str], bytes]) -> bytes:
    raw = _optional(read, release_path(release_hash))
    if raw is None:
        raw = read(LEGACY_RELEASE)
    if digest(raw) != release_hash:
        raise Conflict("workspace release manifest checksum mismatch")
    return raw


def read_approval(approval_id: str, read: Callable[[str], bytes]) -> RuntimeApproval:
    return RuntimeApproval.model_validate(read_json(read(f"receipts/runtime/{approval_id}.json")))


def check_upgrade_chain(
    workspace_id: str, approval: RuntimeApproval, read: Callable[[str], bytes]
) -> None:
    """An upgrade binding must lead back to an owner-acknowledged init or restore."""
    seen = {approval.id}
    current = approval
    while current.operation == "upgrade":
        assert current.update_authorization_id and current.previous_approval_id
        authorization = UpdateAuthorization.model_validate(
            read_json(read(f"receipts/updates/{current.update_authorization_id}.json"))
        )
        if authorization.workspace_id != workspace_id or authorization.id != (
            current.update_authorization_id
        ):
            raise Denied("upgrade approval does not bind this workspace's update authorization")
        if current.release_signer not in authorization.allowed_signers:
            raise Denied("upgrade signer is not in the owner's update authorization")
        previous = read_approval(current.previous_approval_id, read)
        if (
            previous.id != current.previous_approval_id
            or previous.workspace_id != workspace_id
            or previous.id in seen
            or len(seen) > MAX_UPGRADE_CHAIN
        ):
            raise Denied("upgrade approval chain is invalid")
        read_release_manifest(previous.release_hash, read)
        seen.add(previous.id)
        current = previous
    if current.acknowledgements != REQUIRED_REVIEWS:
        raise Denied("upgrade chain does not start from an owner-reviewed activation")


def check_runtime_metadata(
    config: WorkspaceConfiguration,
    read: Callable[[str], bytes],
) -> tuple[ReleaseManifest, RuntimeApproval]:
    if not config.runtime_release_hash or not config.runtime_approval_id:
        raise Denied("private workspace lacks reviewed runtime activation")
    raw = read_release_manifest(config.runtime_release_hash, read)
    manifest = ReleaseManifest.model_validate(read_json(raw))
    approval = read_approval(config.runtime_approval_id, read)
    if (
        approval.id != config.runtime_approval_id
        or approval.workspace_id != config.id
        or approval.release_hash != config.runtime_release_hash
        or approval.worker.image != manifest.worker_image
        or config.worker_image != manifest.worker_image
        or approval.worker.profile_hash
        != digest(canonical(container_command(manifest.worker_image)))
        or not all(approval.worker.result.checks.values())
        or (approval.operation == "restore" and not approval.archive_hash)
    ):
        raise Denied("workspace runtime approval does not bind its release and processing profile")
    if approval.operation == "upgrade":
        check_upgrade_chain(config.id, approval, read)
    elif approval.acknowledgements != REQUIRED_REVIEWS:
        raise Denied("workspace runtime approval does not bind its release and processing profile")
    return manifest, approval


def verify_workspace_runtime(config: WorkspaceConfiguration, read: Callable[[str], bytes]) -> None:
    manifest, _ = check_runtime_metadata(config, read)
    verify_runtime(manifest)
