from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, StrictBool, field_validator, model_validator

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


_PART = r"(0|[1-9][0-9]{0,8})"
ReleaseTag = Annotated[str, Field(pattern=rf"^v{_PART}\.{_PART}\.{_PART}$")]


def tag_version(tag: str) -> tuple[int, int, int]:
    major, minor, patch = tag.removeprefix("v").split(".")
    return int(major), int(minor), int(patch)


class UpdateAuthorization(Model):
    """Standing owner consent to adopt future releases from one channel branch."""

    schema_version: Literal[1] = 1
    id: ID
    workspace_id: ID
    at: datetime
    repository: str = Field(min_length=1, max_length=2048, pattern=r"^[^\r\n\x00]+$")
    ref: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,199}$")
    migrations: Literal["automatic_with_backup"] = "automatic_with_backup"
    owner_statement: str = Field(min_length=1, max_length=4000)

    @field_validator("owner_statement")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("owner statement is required")
        return value


class UpdateRevocation(Model):
    schema_version: Literal[1] = 1
    authorization_id: ID
    workspace_id: ID
    at: datetime
    owner_statement: str = Field(min_length=1, max_length=4000)


class RuntimeApproval(Model):
    schema_version: Literal[1] = 1
    id: ID
    workspace_id: ID
    at: datetime
    operation: Literal["init", "restore", "upgrade"]
    release_hash: Digest
    owner_statement: str = Field(min_length=1, max_length=4000)
    acknowledgements: set[ReviewAcknowledgement]
    worker: WorkerProfile
    archive_hash: Digest | None = None
    # An upgrade is authorized by a standing owner authorization for a release channel,
    # not by per-release acknowledgements; it always names the binding it replaces.
    previous_approval_id: ID | None = None
    update_authorization_id: ID | None = None
    release_tag: ReleaseTag | None = None
    backup_sha256: Digest | None = None

    @field_validator("owner_statement")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("owner review statement is required")
        return value

    @model_validator(mode="after")
    def upgrade_fields(self) -> RuntimeApproval:
        fields = (
            self.previous_approval_id,
            self.update_authorization_id,
            self.release_tag,
            self.backup_sha256,
        )
        if self.operation == "upgrade":
            if any(value is None for value in fields) or self.acknowledgements:
                raise ValueError("upgrade approval requires its authorization chain")
            if self.archive_hash is not None:
                raise ValueError("upgrade approval cannot bind a restore archive")
        elif any(value is not None for value in fields):
            raise ValueError("only an upgrade approval carries an update authorization")
        return self
