"""Deterministic PDF metadata inspection, executed in the isolated extraction worker."""

import io
import re
from typing import Any

import pypdf

from cairn.errors import CairnError
from cairn.library.models import normalize_doi


def inspect_metadata(data: bytes) -> dict[str, Any]:
    reader = pypdf.PdfReader(io.BytesIO(data), strict=True)
    if reader.is_encrypted:
        raise CairnError("encrypted PDF")
    meta: Any = reader.metadata or {}
    result: dict[str, Any] = {}
    title = meta.get("/Title")
    if isinstance(title, str) and title.strip():
        result["title"] = title.strip()[:500]
    author = meta.get("/Author")
    if isinstance(author, str) and author.strip():
        result["authors"] = [author.strip()[:1000]]
    text = "\n".join((page.extract_text() or "")[:100000] for page in reader.pages[:2])
    matches = set(re.findall(r"10\.\d{4,9}/[^\s<>\"\[\]]+", text, re.I))
    # Multiple DOIs often mean references; do not guess which identifies this paper.
    if len(matches) == 1:
        result["doi"] = normalize_doi(next(iter(matches)).rstrip(".,;)"))
    return result
