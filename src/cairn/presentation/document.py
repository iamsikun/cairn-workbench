"""Data-only document contract shared by native and legacy rendering."""

from typing import Literal

from pydantic import Field, model_validator

from cairn.records.models import ID, Digest, EvidenceRef, Model


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


class ViewBlock(Model):
    title: str = ""
    text: str = ""
    kind: Literal["text", "quote", "code", "diagram", "markdown"] = "text"
    anchor: ID | None = Field(default=None, exclude_if=lambda value: value is None)
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
