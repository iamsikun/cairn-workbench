from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from cairn.adapters.protocol import Job, Page
from cairn.presentation.models import ViewBundle
from cairn.records.models import ID, Digest, Domain, EvidenceRef, Labels, Model, Record, digest


class WritingJob(Model):
    schema_version: Literal[1] = 1
    id: ID
    purpose: Literal["explanation", "revision"]
    bundle: ViewBundle
    request: str = Field(max_length=20000)
    request_labels: Labels
    guidance: str = Field(max_length=100000)
    guidance_hash: Digest
    # The old revision marks packets that carried a vendored Quill snapshot.
    quill_revision: Literal["d6bc7de15d1779c58286cbdec1a54eec52bdef22", "cairn-1"] = "cairn-1"
    route: Literal["local", "cloud"]
    provider: str = Field(min_length=1, max_length=200)
    destination: str = Field(min_length=1, max_length=2000)
    revision: Job | None = None
    target_ids: list[ID] = Field(default_factory=list, max_length=20)
    feedback_id: ID | None = None

    @model_validator(mode="after")
    def consistent(self) -> "WritingJob":
        if (self.purpose == "revision") != (self.revision is not None):
            raise ValueError("revision packet requires a sealed revision job")
        if self.guidance_hash != digest(self.guidance.encode()):
            raise ValueError("writing guidance checksum mismatch")
        return self


class Quotation(Model):
    evidence_key: ID
    text: str = Field(min_length=1, max_length=10000)


class ExplanationBlock(Model):
    title: str = Field(default="", max_length=500)
    text: str = Field(min_length=1, max_length=20000)
    kind: Literal["reported_result", "inference", "hypothesis", "question"]
    evidence_keys: list[ID] = Field(default_factory=list, max_length=40)
    quotations: list[Quotation] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def cited(self) -> "ExplanationBlock":
        if self.kind == "reported_result" and not self.evidence_keys:
            raise ValueError("reported results require supplied evidence")
        if any(q.evidence_key not in self.evidence_keys for q in self.quotations):
            raise ValueError("quote must reference a cited evidence key")
        return self


class ExplanationAnswer(Model):
    """What the owner's agent returns to explain a saved view."""

    blocks: list[ExplanationBlock] = Field(min_length=1, max_length=100)
    limitations: list[str] = Field(default_factory=list, max_length=40)


class ExplanationResponse(Model):
    schema_version: Literal[1] = 1
    job_id: ID
    input_hash: Digest
    blocks: list[ExplanationBlock] = Field(min_length=1, max_length=100)
    limitations: list[str] = Field(default_factory=list, max_length=40)


class ExportReceipt(Model):
    schema_version: Literal[1] = 1
    job_id: ID
    input_hash: Digest
    policy_hash: Digest
    route: Literal["cloud"] = "cloud"
    provider: str
    destination: str
    at: datetime
    processing_verified: Literal[False] = False


class FeedbackEntry(Model):
    target_id: ID
    comment: str = Field(min_length=1, max_length=10000)
    suggested_text: str | None = Field(default=None, max_length=20000)


class Feedback(Model):
    schema_version: Literal[1] = 1
    bundle_id: ID
    bundle_hash: Digest
    entries: list[FeedbackEntry] = Field(min_length=1, max_length=20)


class FeedbackReceipt(Model):
    schema_version: Literal[1] = 1
    id: ID
    feedback: Feedback
    source_id: ID
    attribution: Literal["Imported feedback; authorship and approval are not established"] = (
        "Imported feedback; authorship and approval are not established"
    )


class NewTarget(Model):
    type: Literal["concept", "project", "entity", "playbook", "decision"]
    domain: Domain
    title: str = Field(min_length=1, max_length=500)


class QuillEvidence(Model):
    key: ID
    reference: EvidenceRef
    text: str = Field(max_length=200000)


class QuillPacket(Model):
    """What to write, where it goes, and the only material Quill may use."""

    schema_version: Literal[1] = 1
    id: ID
    instructions: str = Field(min_length=1, max_length=20000)
    request_labels: Labels
    target: Page | None = None
    new: NewTarget | None = None
    evidence: list[QuillEvidence] = Field(default_factory=list, max_length=400)
    context: list[Page] = Field(default_factory=list, max_length=20)
    sources: list[Record] = Field(default_factory=list, max_length=20)
    feedback_id: ID | None = None
    scope: ID
    policy_hash: Digest
    input_hashes: dict[str, Digest]
    route: Literal["cloud"] = "cloud"
    provider: str = Field(min_length=1, max_length=200)
    destination: str = Field(min_length=1, max_length=2000)
    guidance_hash: Digest
    # The old revision marks packets that carried a vendored Quill snapshot.
    quill_revision: Literal["d6bc7de15d1779c58286cbdec1a54eec52bdef22", "cairn-1"] = "cairn-1"
    # Digest of the agent's answer, so a different answer seals a new packet. Omitted when
    # unset, which keeps the identity of packets sealed before it existed.
    attempt: Digest | None = Field(default=None, exclude_if=lambda value: value is None)
    related_ids: list[ID] | None = Field(default=None, exclude_if=lambda value: value is None)
    project_ids: list[ID] | None = Field(default=None, exclude_if=lambda value: value is None)
    aliases: list[str] | None = Field(default=None, exclude_if=lambda value: value is None)

    @model_validator(mode="after")
    def one_target(self) -> "QuillPacket":
        if (self.target is None) == (self.new is None):
            raise ValueError("a writing packet needs exactly one target or new record")
        if self.target is not None and self.target.record.type == "source":
            raise ValueError("sources are immutable")
        return self


class QuillClaim(Model):
    text: str = Field(min_length=1, max_length=10000)
    kind: Literal["reported_result", "inference", "hypothesis"]
    evidence_keys: list[ID] = Field(default_factory=list, max_length=40)
    quotations: list[Quotation] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def cited(self) -> "QuillClaim":
        if self.kind == "reported_result" and not self.evidence_keys:
            raise ValueError("reported results require supplied evidence")
        if any(q.evidence_key not in self.evidence_keys for q in self.quotations):
            raise ValueError("quote must reference a cited evidence key")
        return self


class QuillResponse(Model):
    """Quill returns prose and claims; Cairn formats the record itself."""

    schema_version: Literal[1] = 1
    packet_id: ID
    input_hash: Digest
    title: str | None = Field(default=None, min_length=1, max_length=500)
    body_markdown: str = Field(min_length=1, max_length=200000)
    claims: list[QuillClaim] = Field(default_factory=list, max_length=100)
    limitations: list[str] = Field(default_factory=list, max_length=40)


class SourceCitation(Model):
    source_id: ID
    locator: str = Field(min_length=1, max_length=200)
    quote: str | None = Field(default=None, min_length=1, max_length=10000)


class PageClaim(Model):
    text: str = Field(min_length=1, max_length=10000)
    kind: Literal["reported_result", "inference", "hypothesis"]
    sources: list[SourceCitation] = Field(default_factory=list, max_length=40)

    @model_validator(mode="after")
    def cited(self) -> "PageClaim":
        if self.kind == "reported_result" and not self.sources:
            raise ValueError("reported results require supplied evidence")
        return self


class PageAnswer(Model):
    """What the owner's agent returns for a page; Cairn binds and formats it."""

    title: str | None = Field(default=None, min_length=1, max_length=500)
    body_markdown: str = Field(min_length=1, max_length=200000)
    claims: list[PageClaim] = Field(default_factory=list, max_length=100)
    limitations: list[str] = Field(default_factory=list, max_length=40)
    related: list[str] | None = Field(
        default=None, max_length=20, exclude_if=lambda value: value is None
    )
    project_ids: list[str] | None = Field(
        default=None, max_length=20, exclude_if=lambda value: value is None
    )
    aliases: list[str] | None = Field(
        default=None, max_length=40, exclude_if=lambda value: value is None
    )


class PageDraft(PageAnswer):
    """A companion page; @key links refer to another page in this same proposal."""

    key: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,39}$")
    target: ID | None = None
    base_hash: Digest | None = None
    new_type: Literal["concept", "project", "entity", "playbook", "decision"] = "concept"
    domain: Domain = "research"

    @model_validator(mode="after")
    def target_hash(self) -> "PageDraft":
        if (self.target is None) != (self.base_hash is None):
            raise ValueError("an existing target requires its base_hash")
        if self.target is None and not self.title:
            raise ValueError("new pages require a title")
        return self


class QuillReceipt(Model):
    schema_version: Literal[1] = 1
    packet_id: ID
    response_hash: Digest
    source_id: ID
    proposal_id: ID
    workflow_stage: Literal["validated"] = "validated"
    processing_verified: Literal[False] = False
