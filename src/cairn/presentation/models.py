from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field, model_validator

from cairn.library.feed import FeedDigest
from cairn.presentation.document import (
    EvidenceItem as EvidenceItem,
)
from cairn.presentation.document import (
    ViewAsset as ViewAsset,
)
from cairn.presentation.document import (
    ViewBlock as ViewBlock,
)
from cairn.presentation.document import (
    ViewDocument as ViewDocument,
)
from cairn.presentation.document import (
    ViewSection as ViewSection,
)
from cairn.records.continuity import ContextPack
from cairn.records.models import ID, Assertion, Digest, EvidenceRef, Labels, Model, Period, Record
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


class PageEntry(Model):
    record: Record
    markdown: str = Field(max_length=200000)


class PagePayload(Model):
    kind: Literal["page"] = "page"
    pages: list[PageEntry]
    topics: dict[ID, str]


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
    | FeedPayload
    | PagePayload,
    Field(discriminator="kind"),
]


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


class RenderJob(Model):
    operation: Literal["render_view"] = "render_view"
    document: ViewDocument
