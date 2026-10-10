from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field, model_validator

from cairn.library.feed import FeedDigest
from cairn.records.continuity import ContextPack
from cairn.records.models import ID, Assertion, Digest, EvidenceRef, Labels, Model, Period
from cairn.retrieval.search import Hit


class PaperClaim(Model):
    text: str = Field(min_length=1, max_length=5000)
    page: int = Field(ge=1)
    quote: str | None = Field(default=None, max_length=2000)
    kind: Literal["reported_result", "inference", "hypothesis"] = "reported_result"


class PaperSummary(Model):
    """Kept so views saved by the retired library reader still load."""

    summary: str = Field(min_length=1, max_length=8000)
    research_question: list[PaperClaim] = Field(default_factory=list, max_length=20)
    methods: list[PaperClaim] = Field(default_factory=list, max_length=20)
    findings: list[PaperClaim] = Field(default_factory=list, max_length=40)
    assumptions: list[PaperClaim] = Field(default_factory=list, max_length=20)
    limitations: list[PaperClaim] = Field(default_factory=list, max_length=20)
    warnings: list[str] = Field(default_factory=list, max_length=40)


class EvidenceItem(Model):
    key: ID
    reference: EvidenceRef
    title: str
    text: str
    source_date: str | None = None
    version: str | None = None
    coverage: str
    tables_inspected: bool
    images_inspected: bool
    support: str = "Hash and locator checked; quote presence does not establish entailment."


class ReviewChange(Model):
    id: ID
    title: str
    target: str
    base_hash: Digest | None
    current_hash: Digest | None
    proposed_hash: Digest
    rationale: str
    period: Period | None
    conflicts: list[str]
    diff: str
    assertions: list[Assertion] = Field(default_factory=list)


class ReviewReport(Model):
    id: ID
    proposal_hash: Digest
    provider: str
    route: str
    scope: ID
    validation: str
    stage: str = "proposed"
    review_flags: list[str]
    changes: list[ReviewChange]
    references: list[EvidenceRef]


class CatalogItem(Model):
    id: ID
    title: str
    authors: list[str]
    year: int | None
    doi: str | None
    reading: str
    analysis: str = "not_started"
    review: str = "unreviewed"
    availability: str


class ProjectPayload(Model):
    kind: Literal["project"] = "project"
    context: ContextPack
    assertion_kinds: dict[ID, str] = Field(default_factory=dict)


class QueryPayload(Model):
    kind: Literal["query"] = "query"
    mode: Literal["extractive"] = "extractive"
    status: str
    hits: list[Hit]
    limitations: list[str]
    assertions: dict[ID, list[Assertion]] = Field(default_factory=dict)


class EvidencePayload(Model):
    kind: Literal["evidence"] = "evidence"
    source_id: ID


class PaperPayload(Model):
    kind: Literal["paper"] = "paper"
    paper: CatalogItem
    summary: PaperSummary | None = None
    inspected_pages: list[int] = Field(default_factory=list)
    visual_pages: list[int] = Field(default_factory=list)
    page_count: int | None = None
    coverage: str = "Not read"


class ProposalPayload(Model):
    kind: Literal["proposal"] = "proposal"
    report: ReviewReport


class CatalogPayload(Model):
    kind: Literal["catalog"] = "catalog"
    papers: list[CatalogItem]


class FeedPayload(Model):
    kind: Literal["feed"] = "feed"
    digest: FeedDigest


Payload = Annotated[
    ProjectPayload
    | QueryPayload
    | EvidencePayload
    | PaperPayload
    | ProposalPayload
    | CatalogPayload
    | FeedPayload,
    Field(discriminator="kind"),
]


class ViewAsset(Model):
    id: ID
    mime: Literal["image/png", "image/jpeg", "image/webp"]
    data: str = Field(max_length=7_000_000)
    sha256: Digest

    @model_validator(mode="after")
    def checked(self) -> "ViewAsset":
        import base64

        from cairn.records.models import digest

        raw = base64.b64decode(self.data, validate=True)
        if len(raw) > 5_000_000 or digest(raw) != self.sha256:
            raise ValueError("asset checksum or size mismatch")
        signatures = {
            "image/png": raw.startswith(b"\x89PNG\r\n\x1a\n"),
            "image/jpeg": raw.startswith(b"\xff\xd8\xff"),
            "image/webp": raw.startswith(b"RIFF") and raw[8:12] == b"WEBP",
        }
        if not signatures[self.mime]:
            raise ValueError("asset media signature mismatch")
        return self


class ViewBundle(Labels):
    schema_version: Literal[1] = 1
    id: ID
    workspace_id: ID
    scope: ID
    policy_hash: Digest
    created_at: datetime
    question: str = Field(max_length=20000)
    title: str = Field(max_length=1000)
    input_hashes: dict[str, Digest]
    library_state_hash: Digest | None = None
    review_state_hash: Digest | None = None
    record_ids: list[ID]
    evidence: list[EvidenceItem]
    payload: Payload
    warnings: list[str] = Field(default_factory=list)
    assets: list[ViewAsset] = Field(default_factory=list, max_length=8)
    renderer: str
    template_version: Literal["cairn-view-v1"] = "cairn-view-v1"

    @model_validator(mode="after")
    def unique_evidence(self) -> "ViewBundle":
        if len({item.key for item in self.evidence}) != len(self.evidence):
            raise ValueError("duplicate evidence keys")
        return self


class ViewBlock(Model):
    title: str = ""
    text: str = ""
    kind: Literal["text", "quote", "code", "diagram"] = "text"
    labels: list[str] = Field(default_factory=list)
    citations: list[ID] = Field(default_factory=list)
    nodes: list[str] = Field(default_factory=list)
    url: str | None = None
    asset_id: ID | None = None


class ViewSection(Model):
    title: str
    blocks: list[ViewBlock]


class ViewDocument(Model):
    version: Literal[1] = 1
    title: str
    bundle_id: ID
    bundle_hash: Digest
    subtitle: str
    sections: list[ViewSection]
    evidence: list[EvidenceItem]
    targets: list[ID]
    feedback: bool = False
    assets: list[ViewAsset] = Field(default_factory=list, max_length=8)


class RenderJob(Model):
    operation: Literal["render_view"] = "render_view"
    document: ViewDocument
