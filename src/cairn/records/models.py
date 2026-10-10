from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

ID = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{2,95}$")]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Domain = Literal["research", "finance", "life", "shared"]
Classification = Literal["public", "private", "restricted"]
Processing = Literal["local_only", "cloud_eligible"]
RecordType = Literal["source", "concept", "project", "decision", "entity", "playbook"]
Stage = Literal["captured", "extracted", "proposed", "validated", "approved", "applied", "indexed"]


def now() -> datetime:
    return datetime.now(UTC)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(value: Any) -> bytes:
    def normalize(item: Any) -> Any:
        if isinstance(item, BaseModel):
            return normalize(item.model_dump(mode="python"))
        if isinstance(item, dict):
            return {key: normalize(val) for key, val in item.items()}
        if isinstance(item, (set, frozenset)):
            return sorted(normalize(val) for val in item)
        if isinstance(item, (list, tuple)):
            return [normalize(val) for val in item]
        if isinstance(item, (datetime, date)):
            return item.isoformat()
        if isinstance(item, Decimal):
            return str(item)
        return item

    return (
        json.dumps(normalize(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode()


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class Labels(Model):
    domain: Domain
    classification: Classification = "private"
    processing: Processing = "local_only"
    compartments: set[ID] = Field(default_factory=set)


class Period(Model):
    as_of: date | None = None
    valid_from: date | None = None
    valid_until: date | None = None
    tax_year: int | None = Field(default=None, ge=1900, le=9999)
    jurisdiction: str | None = None
    statement_period: str | None = None
    owner_alias: ID | None = None
    account_alias: ID | None = None

    @model_validator(mode="after")
    def ordered(self) -> Period:
        if self.valid_from and self.valid_until and self.valid_until < self.valid_from:
            raise ValueError("invalid validity interval")
        return self


class EvidenceRef(Model):
    id: ID
    source_hash: Digest
    evidence_hash: Digest
    locator: str = Field(min_length=1, max_length=500)
    quote: str | None = Field(default=None, max_length=10000)


class Money(Model):
    value: Decimal = Field(allow_inf_nan=False)
    unit: str = Field(min_length=1, max_length=40)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    as_of: date
    owner_alias: ID | None = None
    account_alias: ID | None = None
    sources: list[EvidenceRef] = Field(min_length=1)

    @field_validator("value", mode="before")
    @classmethod
    def decimal_input(cls, value: Any) -> Any:
        if isinstance(value, (float, bool)):
            raise ValueError("decimal values must be decimal strings, never floats")
        return value


class Assertion(Model):
    id: ID
    text: str = Field(min_length=1, max_length=20000)
    kind: Literal["reported_result", "inference", "hypothesis", "owner_decision"]
    verification: Literal["unreviewed", "reviewed", "disputed", "superseded"] = "unreviewed"
    sources: list[EvidenceRef] = Field(default_factory=list)
    period: Period | None = None
    amounts: list[Money] = Field(default_factory=list)
    supersedes: list[ID] = Field(default_factory=list)
    disputes: list[ID] = Field(default_factory=list)
    rationale: str | None = None
    context_role: (
        Literal["tried", "relevant_literature", "failed_approaches", "open_issues", "next_action"]
        | None
    ) = None

    @model_validator(mode="after")
    def evidence_required(self) -> Assertion:
        if self.kind == "reported_result" and not self.sources:
            raise ValueError("reported results require evidence")
        if (self.supersedes or self.disputes) and not self.rationale:
            raise ValueError("supersession and disputes require rationale")
        return self


class ExtractionMetadata(Model):
    evidence_hash: Digest
    method: str
    method_version: str
    coverage: Literal["full_text", "excerpt", "abstract_only", "failed"]
    tables_inspected: bool = False
    images_inspected: bool = False


class SourceMetadata(Model):
    identity: str = Field(min_length=1, max_length=1000)
    origin: str = Field(min_length=1, max_length=2000)
    source_type: Literal[
        "text",
        "markdown",
        "pdf",
        "conversation",
        "bibliography",
        "receipt",
        "finance_snapshot",
        "life_dossier",
    ]
    captured_at: datetime
    content_hash: Digest
    blob: str
    version: str | None = None
    source_date: date | None = None
    supersedes: list[ID] = Field(default_factory=list)
    external_id: str | None = None
    citation_key: str | None = None
    authors: list[str] = Field(default_factory=list)
    bibliography: dict[str, JsonValue] | None = None
    library_alias: ID | None = None
    extraction: ExtractionMetadata | None = None


class RepositoryBinding(Model):
    alias: ID
    commit: str = Field(pattern=r"^[0-9a-f]{40,64}$")
    worktree_hash: Digest
    run_ids: list[str] = Field(default_factory=list)


class Record(Labels):
    schema_version: Literal[1] = 1
    id: ID
    type: RecordType
    title: str = Field(min_length=1, max_length=500)
    status: Literal["draft", "active", "disputed", "superseded"] = "draft"
    created_at: datetime
    updated_at: datetime
    aliases: list[str] = Field(default_factory=list)
    sources: list[EvidenceRef] = Field(default_factory=list)
    assertions: list[Assertion] = Field(default_factory=list)
    related: list[ID] = Field(default_factory=list)
    project_ids: list[ID] = Field(default_factory=list)
    primary_source_id: ID | None = Field(default=None, exclude_if=lambda value: value is None)
    period: Period | None = None
    source: SourceMetadata | None = None
    sections: dict[str, str] = Field(default_factory=dict)
    repository: RepositoryBinding | None = None
    review_date: date | None = None
    finance_category: (
        Literal["educational", "official_rule", "account_snapshot", "owner_decision"] | None
    ) = None

    @field_validator("created_at", "updated_at")
    @classmethod
    def aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("timestamps must have a timezone")
        return value

    @model_validator(mode="after")
    def consistent(self) -> Record:
        if self.primary_source_id is not None and self.type != "concept":
            raise ValueError("only concept notes can bind a primary paper source")
        if "cairn_library_v1" in self.sections:
            from cairn.library.models import metadata

            metadata(self)
        if not self.id.startswith(f"{self.type}_"):
            raise ValueError("record ID prefix must match type")
        if (self.type == "source") != (self.source is not None):
            raise ValueError("only source records have source metadata")
        if self.updated_at < self.created_at:
            raise ValueError("updated timestamp predates creation")
        if self.finance_category and self.domain != "finance":
            raise ValueError("financial category requires finance domain")
        if self.finance_category == "official_rule" and not (
            self.period and (self.period.as_of or self.period.valid_from or self.period.tax_year)
        ):
            raise ValueError("official rules require dated applicability metadata")
        if self.finance_category == "account_snapshot" and not (
            self.period
            and self.period.as_of
            and self.period.owner_alias
            and self.period.account_alias
        ):
            raise ValueError("account snapshots require dated owner and account metadata")
        ids = [item.id for item in self.assertions]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate assertion IDs")
        return self


class Segment(Model):
    locator: str
    text: str
    role: Literal["system", "developer", "user", "assistant", "tool"] | None = None


class Extraction(Model):
    schema_version: Literal[1] = 1
    source_id: ID
    source_hash: Digest
    method: str
    method_version: str
    coverage: Literal["full_text", "excerpt", "abstract_only", "failed"]
    tables_inspected: bool = False
    images_inspected: bool = False
    normalization: Literal["none"] = "none"
    segments: list[Segment]
    warnings: list[str] = Field(default_factory=list)


class Event(Model):
    schema_version: Literal[1] = 1
    id: ID
    object_id: ID
    attempt_id: ID
    stage: Stage
    outcome: Literal["succeeded", "failed", "blocked"] = "succeeded"
    reason: str | None = None
    at: datetime
    hashes: dict[str, Digest] = Field(default_factory=dict)
