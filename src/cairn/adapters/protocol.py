from typing import Literal, Protocol

from pydantic import Field

from cairn.records.models import ID, Digest, Extraction, Model, Record


class Page(Model):
    record: Record
    body: str = Field(max_length=200000)


class Job(Model):
    schema_version: Literal[1] = 1
    id: ID
    operation: Literal["ingest"] = "ingest"
    policy_hash: Digest
    scope_name: ID
    route: Literal["local", "cloud"] = "local"
    provider: str
    source: Record
    extraction: Extraction
    evidence_hash: Digest
    related: list[Page] = Field(default_factory=list, max_length=20)
    max_changes: int = Field(default=4, ge=1, le=20)


class Candidate(Page):
    rationale: str = Field(min_length=1, max_length=10000)


class Result(Model):
    schema_version: Literal[1] = 1
    job_id: ID
    input_hash: Digest
    provider: str
    candidates: list[Candidate] = Field(max_length=20)
    warnings: list[str] = Field(default_factory=list)


class Provider(Protocol):
    def generate(self, job: Job) -> Result: ...
