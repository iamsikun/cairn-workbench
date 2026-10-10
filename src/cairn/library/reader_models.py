from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from cairn.records.models import ID, Digest, Extraction, Model
from cairn.records.runtime import ImageID, ProbeResult

# Shared by the device reader and the owner-side text check.
VISUAL_ONLY = "[Visual evidence; no extracted text]"
PAGE_TEXT_BUDGET = 12000


class DeviceProbe(Model):
    nonce: str
    image: ImageID
    model_hash: Digest
    projection_hash: Digest
    result: ProbeResult
    host_canary_preserved: Literal[True]
    gpu: str
    at: datetime


class QualityReview(Model):
    trial_hash: Digest
    model_hash: Digest
    projection_hash: Digest
    image: ImageID
    peak_vram_mib: int = Field(ge=1, le=24000)
    owner_statement: str = Field(min_length=1, max_length=4000)
    at: datetime


class DeviceConfig(Model):
    schema_version: Literal[1] = 1
    id: ID
    ssh_alias: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,100}$")
    known_hosts: str
    known_hosts_hash: Digest
    command: Literal["posix", "windows_wsl"] = "posix"
    scope: ID = "research"
    image: ImageID
    model_hash: Digest
    projection_hash: Digest
    model_revision: str = Field(pattern=r"^[a-f0-9]{40}$")
    runtime_revision: str = Field(pattern=r"^[a-f0-9]{40}$")
    probe: DeviceProbe | None = None
    quality_review: QualityReview | None = None


class PaperClaim(Model):
    text: str = Field(min_length=1, max_length=5000)
    page: int = Field(ge=1)
    quote: str | None = Field(default=None, max_length=2000)
    kind: Literal["reported_result", "inference", "hypothesis"] = "reported_result"


class PaperSummary(Model):
    summary: str = Field(min_length=1, max_length=8000)
    research_question: list[PaperClaim] = Field(default_factory=list, max_length=20)
    methods: list[PaperClaim] = Field(default_factory=list, max_length=20)
    findings: list[PaperClaim] = Field(default_factory=list, max_length=40)
    assumptions: list[PaperClaim] = Field(default_factory=list, max_length=20)
    limitations: list[PaperClaim] = Field(default_factory=list, max_length=20)
    warnings: list[str] = Field(default_factory=list, max_length=40)

    def claims(self) -> list[PaperClaim]:
        return [
            *self.research_question,
            *self.methods,
            *self.findings,
            *self.assumptions,
            *self.limitations,
        ]


class ReaderJob(Model):
    schema_version: Literal[1] = 1
    id: ID
    paper_id: ID
    source_id: ID
    source_hash: Digest
    policy_hash: Digest
    device_hash: Digest
    device_id: ID
    scope: ID = "research"
    source_type: Literal["pdf", "bibliography"]
    title: str
    model_hash: Digest
    projection_hash: Digest
    prompt_version: Literal["paper-reader-v1", "finch-paper-reader-v1"] = "finch-paper-reader-v1"
    guidance_hash: Digest | None = None
    reading_revision: int = Field(default=1, ge=1, le=10000)
    page_limit: int = Field(default=500, ge=1, le=2000)
    chunk_pages: int = Field(default=4, ge=1, le=4)


class ReaderResult(Model):
    schema_version: Literal[1] = 1
    job_id: ID
    input_hash: Digest
    model_hash: Digest
    extraction: Extraction
    summary: PaperSummary
    inspected_pages: list[int]
    visual_pages: list[int] = Field(default_factory=list)
    page_count: int = Field(ge=1)

    @model_validator(mode="after")
    def coverage(self) -> "ReaderResult":
        if self.extraction.images_inspected != bool(self.visual_pages):
            raise ValueError("image coverage metadata mismatch")
        if (
            not self.inspected_pages
            or len(self.inspected_pages) != len(set(self.inspected_pages))
            or any(p < 1 or p > self.page_count for p in self.inspected_pages)
        ):
            raise ValueError("invalid inspected pages")
        if not set(self.visual_pages) <= set(self.inspected_pages):
            raise ValueError("visual inspection exceeds inspected pages")
        if self.extraction.coverage == "full_text" and len(self.inspected_pages) != self.page_count:
            raise ValueError("full-text coverage cannot omit pages")
        for claim in self.summary.claims():
            if claim.page not in self.inspected_pages:
                raise ValueError("claim references an uninspected page")
            segments = [s for s in self.extraction.segments if s.locator == f"page {claim.page}"]
            if not segments or (
                claim.quote is not None and not any(claim.quote in s.text for s in segments)
            ):
                raise ValueError("claim quote or page does not match extraction")
        return self


class ReadState(Model):
    schema_version: Literal[1] = 1
    job: ReaderJob
    status: Literal["queued", "running", "completed", "blocked", "failed", "stale", "cancelled"] = (
        "queued"
    )
    attempts: int = 0
    reason: str | None = None
    proposal_id: ID | None = None
    result_hash: Digest | None = None
    at: datetime
