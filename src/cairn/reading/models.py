from typing import Literal

from pydantic import Field, model_validator

from cairn.adapters.protocol import Page
from cairn.records.continuity import ReceiptMessage
from cairn.records.models import ID, Digest, EvidenceRef, Extraction, Labels, Model, Record


class FinchPacket(Model):
    schema_version: Literal[1] = 1
    id: ID
    source: Record
    extraction: Extraction
    evidence_hash: Digest
    related: list[Page] = Field(default_factory=list, max_length=20)
    scope: ID
    policy_hash: Digest
    input_hashes: dict[str, Digest]
    guard_hash: Digest
    request: str = Field(min_length=1, max_length=20000)
    request_labels: Labels
    provider: str = Field(min_length=1, max_length=200)
    destination: str = Field(min_length=1, max_length=2000)
    route: Literal["cloud"] = "cloud"
    guidance_hash: Digest
    skill_version: Literal["0.2.0"] = "0.2.0"


class FinchGuard(Model):
    """Owner-only immutability checks; never export unrelated workspace paths."""

    schema_version: Literal[1] = 1
    protected_hashes: dict[str, Digest]


class FinchClaim(Model):
    text: str = Field(min_length=1, max_length=10000)
    kind: Literal["reported_result", "inference", "hypothesis"]
    sources: list[EvidenceRef] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def cited(self) -> "FinchClaim":
        if self.kind == "reported_result" and not self.sources:
            raise ValueError("reported results require supplied paper evidence")
        return self


class FinchResponse(Model):
    schema_version: Literal[1] = 1
    session_id: ID
    input_hash: Digest
    summary: str = Field(min_length=1, max_length=20000)
    claims: list[FinchClaim] = Field(default_factory=list, max_length=100)
    messages: list[ReceiptMessage] = Field(min_length=1, max_length=1000)
    unresolved: list[str] = Field(default_factory=list, max_length=100)
    limitations: list[str] = Field(default_factory=list, max_length=40)


class FinchReceipt(Model):
    schema_version: Literal[1] = 1
    session_id: ID
    response_hash: Digest
    source_id: ID
    proposal_id: ID
    workflow_stage: Literal["validated"] = "validated"
    processing_verified: Literal[False] = False
