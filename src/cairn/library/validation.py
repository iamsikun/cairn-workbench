"""Validate durable library links during backup/restore, without filesystem authority."""

from collections.abc import Mapping

from cairn.errors import Conflict
from cairn.library.feed import FeedDigest, FeedEvent
from cairn.library.models import Journal, LibraryConfig, Paper, ScanReport, metadata
from cairn.records.models import Record


def validate_library(payloads: Mapping[str, bytes], records: dict[str, Record]) -> None:
    def source(identity: str, checksum: str | None = None) -> None:
        value = records.get(identity)
        if (
            value is None
            or value.source is None
            or (checksum and value.source.content_hash != checksum)
        ):
            raise Conflict("library references missing or changed source")

    def paper(identity: str) -> None:
        value = records.get(identity)
        if value is None or not isinstance(metadata(value), Paper):
            raise Conflict("library references missing paper")

    for record in records.values():
        value = metadata(record)
        if not isinstance(value, Paper):
            continue
        for journal_id in value.journal_ids:
            journal = records.get(journal_id)
            if journal is None or not isinstance(metadata(journal), Journal):
                raise Conflict("paper references missing journal")
        for source_id in value.source_ids:
            source(source_id)
        for file in value.files:
            if file.source_id:
                source(file.source_id, file.content_hash)
        for evidence in value.metadata_evidence.values():
            if evidence.source_id:
                source(evidence.source_id)
    # Receipts left by the retired library reader are kept but no longer interpreted.
    for path in payloads:
        if not path.startswith("receipts/library/"):
            continue
        if path == "receipts/library/config.json":
            LibraryConfig.model_validate_json(payloads[path])
        elif path.startswith("receipts/library/scans/"):
            report = ScanReport.model_validate_json(payloads[path])
            if path != f"receipts/library/scans/{report.id}.json":
                raise Conflict("library scan identity mismatch")
        elif path.startswith("receipts/library/feed_events/"):
            event = FeedEvent.model_validate_json(payloads[path])
            paper(event.paper_id)
            if path != f"receipts/library/feed_events/{event.id}.json":
                raise Conflict("feed event identity mismatch")
        elif path.startswith("receipts/library/feeds/"):
            saved_feed = FeedDigest.model_validate_json(payloads[path])
            if path != f"receipts/library/feeds/{saved_feed.id}.json":
                raise Conflict("feed digest identity mismatch")
            for entry in saved_feed.entries:
                paper(entry.event.paper_id)
