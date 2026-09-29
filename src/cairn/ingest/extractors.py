from __future__ import annotations

import io
import json

import pypdf

from cairn.errors import CairnError
from cairn.records.continuity import SessionReceipt
from cairn.records.domains import FinancialSnapshot, LifeDossier
from cairn.records.json import read_json
from cairn.records.models import Extraction, Record, Segment, canonical, digest


def extract_bytes(source: Record, data: bytes) -> Extraction:
    if source.source is None or digest(data) != source.source.content_hash:
        raise CairnError("source checksum mismatch")
    kind = source.source.source_type
    segments: list[Segment] = []
    warnings: list[str] = []
    coverage = "full_text"
    method: str = kind
    version = "1"
    if kind in ("text", "markdown"):
        segments = [
            Segment(locator=f"line {i}", text=line)
            for i, line in enumerate(data.decode("utf-8").splitlines(), 1)
            if line.strip()
        ]
    elif kind == "finance_snapshot":
        snapshot = FinancialSnapshot.model_validate(read_json(data))
        segments = [
            Segment(
                locator=f"value {value.key}",
                text=canonical(
                    {
                        "value": value,
                        "owner_alias": snapshot.owner_alias,
                        "account_alias": snapshot.account_alias,
                        "as_of": snapshot.as_of,
                        "statement_period": snapshot.statement_period,
                    }
                )
                .decode()
                .strip(),
            )
            for value in snapshot.values
        ]
        warnings.append(
            "Structured source snapshot; no live balance lookup or wiki-ledger inference."
        )
    elif kind == "life_dossier":
        dossier = LifeDossier.model_validate(read_json(data))
        segments = [
            Segment(
                locator="entity metadata",
                text=canonical(
                    {
                        "entity_alias": dossier.entity_alias,
                        "entity_kind": dossier.entity_kind,
                        "title": dossier.title,
                        "review_date": dossier.review_date,
                    }
                )
                .decode()
                .strip(),
            )
        ]
        for i, event in enumerate(dossier.service_history, 1):
            segments.append(
                Segment(locator=f"service event {i}", text=canonical(event).decode().strip())
            )
        for i, term in enumerate(dossier.terms, 1):
            segments.append(Segment(locator=f"term {i}", text=canonical(term).decode().strip()))
        for i, document in enumerate(dossier.authoritative_documents, 1):
            segments.append(
                Segment(
                    locator=f"authoritative document {i}", text=canonical(document).decode().strip()
                )
            )
        for i, procedure in enumerate(dossier.procedures, 1):
            segments.append(
                Segment(locator=f"procedure {i}", text=canonical(procedure).decode().strip())
            )
    elif kind == "bibliography":
        # The adapter supplies a single preserved CSL-JSON item. A raw BibTeX capture
        # is kept as an excerpt; this release does not pretend to parse BibTeX.
        if source.source.bibliography is None:
            segments = [Segment(locator="bibliography export", text=data.decode("utf-8"))]
            coverage = "excerpt"
            warnings.append("Unparsed bibliography text; no paper full text has been read.")
        else:
            item = read_json(data)
            if canonical(item) != canonical(source.source.bibliography):
                raise CairnError("bibliography metadata differs from preserved item")
            segments = [
                Segment(
                    locator=f"CSL field {key}",
                    text=value if isinstance(value, str) else canonical(value).decode().strip(),
                )
                for key, value in sorted(item.items())
            ]
            coverage = "abstract_only" if item.get("abstract") else "excerpt"
            method = "csl-json-item"
            warnings.append("Bibliographic metadata only; paper full text has not been read.")
    elif kind == "receipt":
        receipt = SessionReceipt.model_validate(read_json(data))
        segments = [
            Segment(
                locator=f"message {i}; role {message.role}", text=message.content, role=message.role
            )
            for i, message in enumerate(receipt.messages, 1)
        ]
        for field in ("tried", "proposed_decisions", "failures", "unresolved"):
            segments.extend(
                Segment(locator=f"{field} {i}", text=entry.text, role="assistant")
                for i, entry in enumerate(getattr(receipt, field), 1)
            )
        if receipt.next_action:
            segments.append(
                Segment(locator="next_action", text=receipt.next_action.text, role="assistant")
            )
        segments.append(
            Segment(
                locator="session metadata",
                text=canonical(
                    {
                        "session_id": receipt.session_id,
                        "project_id": receipt.project_id,
                        "repository": receipt.repository,
                        "produced_evidence": receipt.produced_evidence,
                    }
                )
                .decode()
                .strip(),
            )
        )
        warnings.append("Session reports and proposed decisions are not owner adoption.")
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
