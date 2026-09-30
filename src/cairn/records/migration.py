"""Owner maintenance artifacts. These are never accepted as worker results."""

from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator

from cairn.records.models import ID, Digest, Model


class MigrationPlan(Model):
    schema_version: Literal[1] = 1
    operation: Literal["workspace_v1_to_v2"] = "workspace_v1_to_v2"
    id: ID
    workspace_id: ID
    input_hashes: dict[str, Digest] = Field(max_length=10000)
    before_config: str
    after_config: str
    before_policy: str
    after_policy: str


class MigrationAuthorization(Model):
    schema_version: Literal[1] = 1
    plan: MigrationPlan
    backup_sha256: Digest
    at: datetime
    owner_statement: str = Field(min_length=1, max_length=4000)

    @field_validator("owner_statement")
    @classmethod
    def statement_is_explicit(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("migration requires an explicit owner statement")
        return value


class MigrationTransaction(Model):
    schema_version: Literal[1] = 1
    id: ID
    workspace_id: ID
    authorization_hash: Digest
    policy_change_hash: Digest
    status: Literal["prepared", "committed"] = "prepared"


class MigrationReceipt(Model):
    schema_version: Literal[1] = 1
    id: ID
    workspace_id: ID
    authorization_hash: Digest
    plan_sha256: Digest
    backup_sha256: Digest
    at: datetime
    files: dict[str, Digest]
