from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator

from cairn.adapters.protocol import Job
from cairn.policies.models import Scope
from cairn.records.models import ID, Digest, Model


class JobEnvelope(Model):
    job: Job
    scope: Scope
    input_hashes: dict[str, Digest]
    protected_hashes: dict[str, Digest]


class Change(Model):
    id: ID
    path: str
    base_hash: Digest | None
    content: str = Field(max_length=1000000)
    content_hash: Digest
    diff: str
    rationale: str


class Proposal(Model):
    schema_version: Literal[1] = 1
    id: ID
    workspace_id: ID
    job_id: ID
    input_hash: Digest
    policy_hash: Digest
    provider: str
    route: Literal["local", "cloud", "owner_device"]
    created_at: datetime
    changes: list[Change] = Field(min_length=1, max_length=20)
    review_flags: set[str] = Field(default_factory=set)


class Approval(Model):
    schema_version: Literal[1] = 1
    proposal_id: ID
    workspace_id: ID
    proposal_hash: Digest
    policy_hash: Digest
    acknowledgements: set[str]
    owner_statement: str = Field(min_length=1, max_length=4000)
    at: datetime

    @field_validator("owner_statement")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("owner review statement is required")
        return value


class DraftReceipt(Model):
    """Owner-side record that an agent's draft for one packet was staged and validated."""

    schema_version: Literal[1] = 1
    job_id: ID
    response_hash: Digest
    proposal_id: ID | None
    workflow_stage: Literal["validated", "unchanged"]
    processing_verified: Literal[False] = False
