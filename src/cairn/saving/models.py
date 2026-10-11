from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from cairn.records.models import ID, Digest, Domain, Model, RecordType, now


def default_collections() -> list[Domain]:
    return ["research", "finance", "life", "shared"]


class WorkspaceConfigV4(Model):
    schema_version: Literal[4] = 4
    record_schema_version: Literal[2] = 2
    id: ID
    synthetic: bool = False
    collections: list[Domain] = Field(default_factory=default_collections)


class Citation(Model):
    id: ID
    locator: str | None = Field(default=None, max_length=500)
    quote: str | None = Field(default=None, max_length=10000)


class Relationship(Model):
    target: ID
    kind: Literal[
        "broader_topic",
        "studies",
        "uses",
        "extends",
        "compares_with",
        "supports",
        "challenges",
        "analogy",
        "related",
        "investigates",
    ] = "related"
    explanation: str = Field(min_length=1, max_length=4000)
    basis: Literal["source_stated", "inferred"] = "inferred"
    sources: list[Citation] = Field(default_factory=list, max_length=20)
    state: Literal["active", "rejected"] = "active"


class Observation(Model):
    id: ID
    text: str = Field(min_length=1, max_length=20000)
    author: Literal["user", "assistant"] = "user"


class SourceInput(Model):
    identity: str = Field(min_length=1, max_length=1000)
    title: str = Field(min_length=1, max_length=500)
    origin: str | None = Field(default=None, max_length=2000)
    version: str | None = Field(default=None, max_length=200)
    text: str | None = Field(default=None, max_length=1000000)
    coverage: Literal["unknown", "excerpt", "abstract_only", "full_text", "failed"] = "unknown"
    authors: list[str] = Field(default_factory=list, max_length=100)


class SourceInfo(SourceInput):
    content_hash: Digest | None = None
    blob: str | None = None
    extraction_status: Literal["unavailable", "supplied", "extracted", "failed"] = "unavailable"
    warnings: list[str] = Field(default_factory=list)
    original_hash: Digest | None = None
    original_blob: str | None = None
    pages: dict[int, str] = Field(default_factory=dict)


class Resource(Model):
    key: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    kind: Literal["diagram", "table", "figure", "scenario"]
    title: str = Field(min_length=1, max_length=500)
    # Declarative renderer inputs only; never source-supplied executable code.
    content: str = Field(max_length=1000000)
    description: str = Field(min_length=1, max_length=10000)


class KnowledgeRecord(Model):
    schema_version: Literal[2] = 2
    id: ID
    type: RecordType = "concept"
    title: str = Field(min_length=1, max_length=500)
    collection: Domain = "research"
    kind: Literal["note", "paper", "topic", "question", "source"] = "note"
    created_at: datetime = Field(default_factory=now)
    updated_at: datetime = Field(default_factory=now)
    aliases: list[str] = Field(default_factory=list)
    relationships: list[Relationship] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    observations: list[Observation] = Field(default_factory=list)
    resources: list[Resource] = Field(default_factory=list)
    primary_source_id: ID | None = None
    paper_identity: str | None = None
    source: SourceInfo | None = None
    enrichment: Literal["complete", "pending"] = "pending"
    unresolved: list[str] = Field(default_factory=list)
    coverage: str = "unknown"
    verification: Literal["unreviewed"] = "unreviewed"
    archived: bool = False

    @model_validator(mode="after")
    def consistent(self) -> "KnowledgeRecord":
        if not self.id.startswith(self.type + "_"):
            raise ValueError("record ID must match its type")
        if (self.type == "source") != (self.source is not None):
            raise ValueError("source records require source metadata")
        if len({x.id for x in self.observations}) != len(self.observations):
            raise ValueError("duplicate observation IDs")
        if len({x.key for x in self.resources}) != len(self.resources):
            raise ValueError("duplicate resource keys")
        return self


class NoteChange(Model):
    id: ID | None = None
    expected_revision: Digest | None = None
    type: RecordType = "concept"
    kind: Literal["note", "paper", "topic", "question"] | None = None
    title: str = Field(min_length=1, max_length=500)
    markdown: str = Field(min_length=1, max_length=1000000)
    aliases: list[str] | None = None
    relationships: list[Relationship] = Field(default_factory=list, max_length=100)
    citations: list[Citation] = Field(default_factory=list, max_length=100)
    observations: list[Observation] = Field(default_factory=list, max_length=1000)
    resources: list[Resource] | None = None
    enrichment: Literal["complete", "pending"] = "pending"
    unresolved: list[str] | None = None
    coverage: str | None = None


class SaveNote(Model):
    operation_key: str = Field(min_length=1, max_length=200)
    note: NoteChange
    client: str | None = Field(default=None, max_length=200)
    model: str | None = Field(default=None, max_length=200)


class SaveReading(SaveNote):
    paper: SourceInput
    topics: list[NoteChange] = Field(default_factory=list, max_length=19)


class Capture(Model):
    operation_key: str = Field(min_length=1, max_length=200)
    source: SourceInput
    pdf_base64: str | None = Field(default=None, max_length=22000000)


class SavedNote(Model):
    id: ID
    path: str
    revision: Digest
    enrichment: Literal["complete", "pending"]


class SaveReceipt(Model):
    schema_version: Literal[1] = 1
    id: ID
    operation_hash: Digest
    payload_hash: Digest
    collection: Domain
    at: datetime = Field(default_factory=now)
    notes: list[SavedNote]
    status: Literal["saved", "unchanged"] = "saved"
    client: str | None = None
    model: str | None = None
    undo_of: ID | None = None


class Entry(Model):
    path: str
    before: str | None
    after: str


class SaveTransaction(Model):
    schema_version: Literal[1] = 1
    kind: Literal["save"] = "save"
    id: ID
    collection: Domain
    status: Literal["prepared", "committed"] = "prepared"
    entries: list[Entry]
    receipt: SaveReceipt
