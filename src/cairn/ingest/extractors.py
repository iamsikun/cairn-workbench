from __future__ import annotations

import io
import json

import pypdf

from cairn.errors import CairnError
from cairn.records.models import Extraction, Record, Segment, digest


def extract_bytes(source: Record, data: bytes) -> Extraction:
    if source.source is None or digest(data) != source.source.content_hash:
        raise CairnError("source checksum mismatch")
    kind = source.source.source_type
    segments: list[Segment] = []
    warnings: list[str] = []
    coverage = "full_text"
    method: str = kind
    version = "1"
    if kind in ("text", "markdown", "bibliography", "receipt"):
        segments = [
            Segment(locator=f"line {i}", text=line)
            for i, line in enumerate(data.decode("utf-8").splitlines(), 1)
            if line.strip()
        ]
    elif kind == "conversation":
        messages = json.loads(data)["messages"]
        if not isinstance(messages, list) or len(messages) > 10000:
            raise CairnError("invalid conversation messages")
        for i, message in enumerate(messages, 1):
            if not isinstance(message, dict) or not isinstance(message.get("content"), str):
                raise CairnError("conversation content must be text")
            segments.append(
                Segment(
                    locator=f"message {i}; role {message['role']}",
                    role=message["role"],
                    text=message["content"],
                )
            )
    elif kind == "pdf":
        reader = pypdf.PdfReader(io.BytesIO(data), strict=True)
        if reader.is_encrypted:
            raise CairnError("encrypted PDF requires owner extraction")
        if len(reader.pages) > 2000:
            raise CairnError("PDF exceeds page limit")
        for page_number, page in enumerate(reader.pages, 1):
            text = page.extract_text() or ""
            segments.extend(
                Segment(locator=f"page {page_number}, line {line_number}", text=line)
                for line_number, line in enumerate(text.splitlines(), 1)
                if line.strip()
            )
        coverage = "excerpt"
        method, version = "pypdf-text", pypdf.__version__
        warnings.append("Text extraction only; images and tables have not been inspected.")
    else:
        raise CairnError("unsupported extraction format")
    if not segments:
        coverage = "failed"
        warnings.append("No extractable text; local OCR or owner-provided transcription required.")
    return Extraction.model_validate(
        {
            "source_id": source.id,
            "source_hash": source.source.content_hash,
            "method": method,
            "method_version": version,
            "coverage": coverage,
            "segments": segments,
            "warnings": warnings,
        }
    )
