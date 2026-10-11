"""Optional bounded local PDF extraction, without fetching external references."""

import base64
import re
import resource
import sys
from pathlib import Path
from typing import Any

from cairn.adapters.isolation import bounded_process
from cairn.errors import CairnError, Denied
from cairn.records.models import canonical, digest
from cairn.saving.models import KnowledgeRecord, SourceInfo
from cairn.saving.workspace import Book


def located_text(source: SourceInfo, locator: str) -> str | None:
    if locator in source.locators:
        return source.locators[locator]
    page = re.fullmatch(r"page (\d+)", locator)
    if page:
        return source.pages.get(int(page[1]))
    lines = re.fullmatch(r"lines? (\d+)(?:-(\d+))?", locator)
    if lines and source.text:
        start, end = int(lines[1]), int(lines[2] or lines[1])
        rows = source.text.splitlines()
        if 1 <= start <= end <= len(rows):
            return "\n".join(rows[start - 1 : end])
    return None


def attach_pdf(book: Book, record: KnowledgeRecord, encoded: str) -> tuple[KnowledgeRecord, str]:
    try:
        raw = base64.b64decode(encoded, validate=True)
    except ValueError as exc:
        raise Denied("invalid PDF encoding") from exc
    if len(raw) > 16 * 1024 * 1024 or not raw.startswith(b"%PDF-"):
        raise Denied("expected a PDF of at most 16 MiB")
    assert record.source is not None
    info = record.source
    info.original_hash = digest(raw)
    info.original_blob = "blobs/" + info.original_hash
    record.id = (
        "source_"
        + digest(
            canonical(
                [
                    record.collection,
                    info.identity,
                    info.version,
                    info.original_hash,
                ]
            )
        )[:32]
    )
    if book.fs.exists(info.original_blob):
        if book.fs.read(info.original_blob) != raw:
            raise Denied("original source checksum mismatch")
    else:
        book.fs.write(info.original_blob, raw, exclusive=True)
    try:
        code, output = bounded_process(
            [sys.executable, "-m", "cairn.saving.sources"],
            raw,
            timeout=20,
            stdout_limit=4 * 1024 * 1024,
            env={
                "PATH": "/usr/local/bin:/usr/bin:/bin",
                "PYTHONPATH": str(Path(__file__).resolve().parents[2]),
                "LANG": "C.UTF-8",
            },
        )
        if code:
            raise CairnError("local PDF parser unavailable or failed")
        import json

        data = json.loads(output)
        info.pages = {int(k): v for k, v in data["pages"].items()}
        info.text = "\n\n".join(info.pages.values()) or None
        info.coverage = "excerpt" if data["partial"] or not info.text else "full_text"
        info.extraction_status = "extracted"
        info.warnings = data["warnings"]
    except (CairnError, OSError, ValueError):
        info.extraction_status = "failed"
        info.coverage = "failed" if info.text is None else "excerpt"
        info.warnings = ["PDF retained; local extraction unavailable or failed."]
    if info.text is not None:
        info.content_hash = digest(info.text.encode())
        info.blob = "blobs/" + info.content_hash
    record.coverage = info.coverage
    return record, info.text or "Original PDF retained; extracted text unavailable.\n"


def extract(raw: bytes) -> dict[str, Any]:
    import io

    import pypdf

    reader = pypdf.PdfReader(io.BytesIO(raw), strict=True)
    pages, warnings = {}, []
    budget = 1000000
    for i, page in enumerate(reader.pages[:200], 1):
        text = (page.extract_text() or "")[:budget]
        pages[i] = text
        budget -= len(text)
        if not text:
            warnings.append(f"Page {i}: no extractable text; figures need visual inspection.")
        if budget <= 0:
            break
    partial = len(pages) < len(reader.pages) or bool(warnings)
    warnings.append("Text extraction does not establish inspection of figures or equations.")
    return {"pages": pages, "partial": partial, "warnings": warnings}


if __name__ == "__main__":
    resource.setrlimit(resource.RLIMIT_CPU, (15, 15))
    resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
    sys.stdout.buffer.write(canonical(extract(sys.stdin.buffer.read(16 * 1024 * 1024 + 1))))
