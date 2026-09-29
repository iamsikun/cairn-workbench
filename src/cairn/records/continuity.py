from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from cairn.records.models import ID, Digest, EvidenceRef, Labels, Model, RepositoryBinding


class ReceiptMessage(Model):
    role: Literal["system", "developer", "user", "assistant", "tool"]
    content: str = Field(min_length=1, max_length=20000)


class ReceiptEntry(Model):
    text: str = Field(min_length=1, max_length=10000)
    sources: list[EvidenceRef] = Field(default_factory=list, max_length=20)


class SessionReceipt(Model):
    schema_version: Literal[1] = 1
    session_id: ID
    project_id: ID
    messages: list[ReceiptMessage] = Field(default_factory=list, max_length=1000)
    tried: list[ReceiptEntry] = Field(default_factory=list, max_length=100)
    produced_evidence: list[EvidenceRef] = Field(default_factory=list, max_length=100)
    proposed_decisions: list[ReceiptEntry] = Field(default_factory=list, max_length=3)
    failures: list[ReceiptEntry] = Field(default_factory=list, max_length=100)
    unresolved: list[ReceiptEntry] = Field(default_factory=list, max_length=100)
    next_action: ReceiptEntry | None = None
    repository: RepositoryBinding | None = None


class ContextItem(Model):
    id: str
    text: str
    sources: list[EvidenceRef] = Field(default_factory=list)
    verification: str = "unreviewed"
    coverage: str | None = None
    version: str | None = None
    source_date: str | None = None


class RepositoryState(Model):
    status: Literal["unbound", "unverified", "current", "stale"]
    recorded: RepositoryBinding | None = None
    observed: RepositoryBinding | None = None
    explanation: str


class ContextPack(Labels):
    schema_version: Literal[1] = 1
    id: ID
    project_id: ID
    question: str = Field(min_length=1, max_length=20000)
    created_at: datetime
    policy_hash: Digest
    budget: int = Field(ge=1000, le=200000)
    estimated_tokens: int = 0
    budget_method: str = "UTF-8 byte count; conservative estimate, not model tokenization"
    sections: dict[str, list[ContextItem]]
    source_ids: list[ID]
    input_hashes: dict[ID, Digest]
    omitted_sections: dict[str, int] = Field(default_factory=dict)
    repository: RepositoryState
    warnings: list[str] = Field(default_factory=list)
