"""Version-specific reference validation, independent of proposal execution."""

from __future__ import annotations

from typing import TYPE_CHECKING

from cairn.errors import CairnError
from cairn.records.models import EvidenceRef, Record

if TYPE_CHECKING:
    from cairn.storage.workspace import Workspace


def all_refs(record: Record) -> list[EvidenceRef]:
    return [
        *record.sources,
        *(ref for assertion in record.assertions for ref in assertion.sources),
        *(
            ref
            for assertion in record.assertions
            for amount in assertion.amounts
            for ref in amount.sources
        ),
    ]


def check_reference(ws: Workspace, ref: EvidenceRef, scope_name: str) -> None:
    from cairn.ingest.service import load_extraction

    _, source, _ = ws.record(ref.id, ws.policy.scope(scope_name))
    extraction, key = load_extraction(ws, source)
    if ref.source_hash != extraction.source_hash or ref.evidence_hash != key:
        raise CairnError("citation version/hash mismatch")
    segments = [segment for segment in extraction.segments if segment.locator == ref.locator]
    if not segments:
        raise CairnError("citation locator does not exist")
    if ref.quote is not None and not ref.quote.strip():
        raise CairnError("empty quotes cannot support a citation")
    if ref.quote is not None and not any(ref.quote in segment.text for segment in segments):
        raise CairnError("quoted text does not exist at the cited locator")
