from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, StrictBool, field_validator

from cairn.records.models import ID, Digest, Model

ImageID = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]


class ReviewAcknowledgement(StrEnum):
    RELEASE = "release_review"
    CONTINUITY = "manual_continuity"
    RECOVERY = "backup_restore"


REQUIRED_REVIEWS: set[ReviewAcknowledgement] = {
    ReviewAcknowledgement.RELEASE,
    ReviewAcknowledgement.CONTINUITY,
    ReviewAcknowledgement.RECOVERY,
}
PROBE_CHECKS = frozenset(
    {
        "non_root",
        "canonical_write_denied",
        "policy_write_denied",
        "approval_write_denied",
        "read_only_root",
        "no_docker_socket",
        "no_host_home",
        "no_credentials",
        "private_canary_unreadable",
        "no_egress_1.1.1.1",
        "no_egress_198.51.100.1",
        "no_dns",
        "hostile_subprocess_contained",
    }
)


class ProbeRequest(Model):
    operation: Literal["probe"] = "probe"
    nonce: Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]
    canary_path: str = Field(min_length=1, max_length=4096)


class ProbeResult(Model):
    schema_version: Literal[1] = 1
    nonce: Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]
    checks: dict[str, StrictBool]

    @field_validator("checks")
    @classmethod
    def complete_checks(cls, value: dict[str, bool]) -> dict[str, bool]:
        if set(value) != PROBE_CHECKS:
            raise ValueError("worker probe omits or adds checks")
        return value


class WorkerProfile(Model):
    schema_version: Literal[1] = 1
    id: ID
    at: datetime
    image: ImageID
    profile_hash: Digest
    result: ProbeResult
    host_canary_preserved: Literal[True] = True


class RuntimeApproval(Model):
    schema_version: Literal[1] = 1
    id: ID
    workspace_id: ID
    at: datetime
    operation: Literal["init", "restore"]
    release_hash: Digest
    owner_statement: str = Field(min_length=1, max_length=4000)
    acknowledgements: set[ReviewAcknowledgement]
    worker: WorkerProfile
    archive_hash: Digest | None = None

    @field_validator("owner_statement")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("owner review statement is required")
        return value
