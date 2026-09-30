from __future__ import annotations

import re
from datetime import datetime
from typing import Literal
from urllib.parse import unquote, urlsplit

from pydantic import Field, field_validator, model_validator

from cairn.records.models import ID, Digest, Model, Record, canonical
from cairn.storage.files import components

LIBRARY_SECTION = "cairn_library_v1"
ReadingState = Literal["unknown", "unread", "queued", "reading", "skimmed", "read"]


def normalize_doi(value: str | None) -> str | None:
    if not value:
        return None
    value = unquote(value.strip()).lower()
    value = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", value)
    if not re.fullmatch(r"10\.\d{4,9}/[^\s<>]+", value) or len(value) > 1000:
        raise ValueError("invalid DOI")
    return value


class DiscoverySource(Model):
    kind: Literal["crossref", "atom", "rss", "pmlr"]
    url: str | None = None
    issn: str | None = Field(default=None, pattern=r"^\d{4}-\d{3}[\dX]$")

    @model_validator(mode="after")
    def valid(self) -> DiscoverySource:
        if self.kind == "crossref":
            if not self.issn or self.url:
                raise ValueError("Crossref requires an ISSN and no custom URL")
        else:
            parts = urlsplit(self.url or "")
            if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
                raise ValueError("discovery sources require owner-selected HTTPS URLs")
        return self


class Journal(Model):
    schema_version: Literal[1] = 1
    kind: Literal["journal"] = "journal"
    folder: str
    resolved: bool = False
    issns: list[str] = Field(default_factory=list)
    discovery: list[DiscoverySource] = Field(default_factory=list)
    coverage: str = "Local collection only; publication coverage unknown"
    checked_at: datetime | None = None
    watermark: datetime | None = None

    @field_validator("folder")
    @classmethod
    def folder_name(cls, value: str) -> str:
        if len(components(value)) != 1 or value.startswith("."):
            raise ValueError("journal folder must be one visible directory")
        return value


class FileLocation(Model):
    path: str
    content_hash: Digest
    size: int = Field(ge=0)
    mtime_ns: int
    availability: Literal["available", "unavailable", "missing"] = "available"
    source_id: ID | None = None

    @field_validator("path")
    @classmethod
    def relative_file(cls, value: str) -> str:
        if len(components(value)) < 2:
            raise ValueError("file must be inside a journal folder")
        return value


class MetadataEvidence(Model):
    origin: str
    source_id: ID | None = None
    observed_at: datetime


class Paper(Model):
    schema_version: Literal[1] = 1
    kind: Literal["paper"] = "paper"
    journal_ids: list[ID] = Field(min_length=1)
    doi: str | None = None
    authors: list[str] = Field(default_factory=list)
    year: int | None = Field(default=None, ge=1000, le=9999)
    published: str | None = None
    volume: str | None = None
    issue: str | None = None
    pages: str | None = None
    abstract: str | None = None
    external_ids: list[str] = Field(default_factory=list)
    files: list[FileLocation] = Field(default_factory=list)
    source_ids: list[ID] = Field(default_factory=list)
    metadata_evidence: dict[str, MetadataEvidence] = Field(default_factory=dict)
    owner_fields: set[str] = Field(default_factory=set)
    reading: ReadingState = "unknown"
    priority: int = Field(default=0, ge=0, le=3)
    topics: list[str] = Field(default_factory=list)
    note_ids: list[ID] = Field(default_factory=list)
    analysis_ids: list[ID] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    first_seen: datetime

    @field_validator("doi", mode="before")
    @classmethod
    def doi_value(cls, value: str | None) -> str | None:
        return normalize_doi(value)


class LibraryConfig(Model):
    schema_version: Literal[1] = 1
    id: Literal["cairn-library"] = "cairn-library"
    root: str
    scope: ID = "research"
    read_only: Literal[True] = True
    layout: Literal["journal_subfolders"] = "journal_subfolders"


class ScanReport(Model):
    schema_version: Literal[1] = 1
    id: ID
    at: datetime
    complete: bool = True
    baseline: bool = False
    added: list[ID] = Field(default_factory=list)
    changed: list[ID] = Field(default_factory=list)
    moved: list[ID] = Field(default_factory=list)
    missing: list[ID] = Field(default_factory=list)
    unchanged: int = 0
    issues: dict[str, str] = Field(default_factory=dict)


def metadata(record: Record) -> Journal | Paper | None:
    raw = record.sections.get(LIBRARY_SECTION)
    if raw is None:
        return None
    if record.type != "entity" or record.domain != "research":
        raise ValueError("library metadata requires a research entity")
    import json

    data = json.loads(raw)
    if data.get("kind") == "journal":
        return Journal.model_validate(data)
    return Paper.model_validate(data)


def set_metadata(record: Record, value: Journal | Paper) -> None:
    record.sections[LIBRARY_SECTION] = canonical(value).decode().strip()
