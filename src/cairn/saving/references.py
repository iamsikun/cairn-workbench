"""Collection-scoped evidence and relationship validation."""

from collections.abc import Mapping

from cairn.errors import Denied
from cairn.saving.models import KnowledgeRecord


def validate_references(record: KnowledgeRecord, available: Mapping[str, KnowledgeRecord]) -> None:
    refs = [*record.citations, *(c for r in record.relationships for c in r.sources)]
    targets = [r.target for r in record.relationships if r.state == "active"]
    if record.primary_source_id:
        targets.append(record.primary_source_id)
    if any(t not in available or available[t].archived for t in targets):
        raise Denied("relationship target unavailable in this collection")
    if any(
        t not in available or available[t].archived
        for resource in record.resources
        for t in resource.synthesis_inputs
    ):
        raise Denied("visual dependency unavailable in this collection")
    for ref in refs:
        source = available.get(ref.id)
        if source is None or source.source is None:
            raise Denied("citation source unavailable in this collection")
        text = source.source.text
        if ref.quote and (text is None or ref.quote not in text):
            raise Denied("quote cannot be verified against supplied source material")
        if ref.locator and ref.quote:
            from cairn.saving.sources import located_text

            located = located_text(source.source, ref.locator)
            if located is None or ref.quote not in located:
                raise Denied("quote cannot be verified at its supplied locator")
