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


def check_runtime_metadata(
    config: WorkspaceConfiguration,
    read: Callable[[str], bytes],
) -> tuple[ReleaseManifest, RuntimeApproval]:
    if not config.runtime_release_hash or not config.runtime_approval_id:
        raise Denied("private workspace lacks reviewed runtime activation")
    raw = read("policy/runtime-release.json")
    if digest(raw) != config.runtime_release_hash:
        raise Conflict("workspace release manifest checksum mismatch")
    manifest = ReleaseManifest.model_validate(read_json(raw))
    approval = RuntimeApproval.model_validate(
        read_json(read(f"receipts/runtime/{config.runtime_approval_id}.json"))
    )
    if (
        approval.id != config.runtime_approval_id
        or approval.workspace_id != config.id
        or approval.release_hash != config.runtime_release_hash
        or approval.acknowledgements != REQUIRED_REVIEWS
        or approval.worker.image != manifest.worker_image
        or config.worker_image != manifest.worker_image
        or approval.worker.profile_hash
        != digest(canonical(container_command(manifest.worker_image)))
        or not all(approval.worker.result.checks.values())
        or (approval.operation == "restore" and not approval.archive_hash)
    ):
        raise Denied("workspace runtime approval does not bind its release and processing profile")
    return manifest, approval


def verify_workspace_runtime(config: WorkspaceConfiguration, read: Callable[[str], bytes]) -> None:
    manifest, _ = check_runtime_metadata(config, read)
    verify_runtime(manifest)
