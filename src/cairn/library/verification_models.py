from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from cairn.library.reader_models import PaperSummary
from cairn.records.models import ID, Digest, Model, Segment

ProviderName = Literal["codex", "claude"]


class VerificationConfig(Model):
    schema_version: Literal[1] = 1
    scope: ID = "research"
    journal_ids: list[ID] = Field(min_length=1)
    valid_until: datetime
    owner_statement: str = Field(min_length=1, max_length=4000)
    codex_model: str = "gpt-6.1-sol"
    claude_model: str = "sonnet"


class VerificationPacket(Model):
    schema_version: Literal[1] = 1
    read_id: ID
    paper_id: ID
    source_id: ID
    source_hash: Digest
    result_hash: Digest
    summary: PaperSummary
    passages: list[Segment] = Field(max_length=12)
    images: dict[str, str] = Field(default_factory=dict, max_length=4)
    coverage: str
    omitted_pages: list[int] = Field(default_factory=list)


class VerificationFinding(Model):
    severity: Literal["minor", "serious"]
    kind: Literal["numerical", "citation", "interpretation", "missing_evidence", "injection"]
    explanation: str = Field(min_length=1, max_length=4000)
    page: int | None = Field(default=None, ge=1)


class VerificationResult(Model):
    schema_version: Literal[1] = 1
    packet_hash: Digest
    verdict: Literal["supported", "concerns", "insufficient_evidence"]
    findings: list[VerificationFinding] = Field(default_factory=list, max_length=40)
    limitations: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def supported_without_concerns(self) -> "VerificationResult":
        if self.verdict == "supported" and self.findings:
            raise ValueError("supported verdict cannot contain concerns")
        return self


class VerificationState(Model):
    schema_version: Literal[1] = 1
    id: ID
    read_id: ID
    packet_hash: Digest
    result_hash: Digest
    source_hash: Digest
    provider: ProviderName
    reason: str
    status: Literal["queued", "completed", "blocked", "stale"] = "queued"
    issue: str | None = None
    result: VerificationResult | None = None
    at: datetime
