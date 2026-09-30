"""Validate durable library links during backup/restore, without filesystem authority."""

from collections.abc import Mapping

from cairn.errors import Conflict
from cairn.library.feed import FeedDigest, FeedEvent
from cairn.library.models import Journal, LibraryConfig, Paper, ScanReport, metadata
from cairn.library.reader_models import DeviceConfig, ReaderResult, ReadState
from cairn.library.verification_models import VerificationConfig, VerificationState
from cairn.records.models import Record, canonical, digest


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
    for path in payloads:
        if not path.startswith("receipts/library/"):
            continue
        if path == "receipts/library/config.json":
            LibraryConfig.model_validate_json(payloads[path])
        elif path == "receipts/library/verification.json":
            VerificationConfig.model_validate_json(payloads[path])
        elif path.startswith("receipts/library/devices/"):
            device = DeviceConfig.model_validate_json(payloads[path])
            if path != f"receipts/library/devices/{device.id}.json":
                raise Conflict("library device identity mismatch")
        elif path.startswith("receipts/library/scans/"):
            report = ScanReport.model_validate_json(payloads[path])
            if path != f"receipts/library/scans/{report.id}.json":
                raise Conflict("library scan identity mismatch")
        elif path.startswith("receipts/library/reads/"):
            state = ReadState.model_validate_json(payloads[path])
            if path != f"receipts/library/reads/{state.job.id}.json":
                raise Conflict("library reading identity mismatch")
            paper(state.job.paper_id)
            source(state.job.source_id, state.job.source_hash)
            if state.status == "completed":
                result_path = f"receipts/library/results/{state.job.id}.json"
                if (
                    result_path not in payloads
                    or digest(payloads[result_path]) != state.result_hash
                ):
                    raise Conflict("completed reading result missing or changed")
                if f"proposals/{state.proposal_id}.json" not in payloads:
                    raise Conflict("completed reading proposal missing")
        elif path.startswith("receipts/library/results/"):
            result = ReaderResult.model_validate_json(payloads[path])
            if path != f"receipts/library/results/{result.job_id}.json":
                raise Conflict("reader result identity mismatch")
            state = ReadState.model_validate_json(
                payloads[f"receipts/library/reads/{result.job_id}.json"]
            )
            if (
                result.input_hash != digest(canonical(state.job))
                or result.model_hash != state.job.model_hash
            ):
                raise Conflict("reader result job binding mismatch")
            source(result.extraction.source_id, result.extraction.source_hash)
        elif path.startswith("receipts/library/checks/"):
            check = VerificationState.model_validate_json(payloads[path])
            if path != f"receipts/library/checks/{check.id}.json":
                raise Conflict("verification identity mismatch")
            state = ReadState.model_validate_json(
                payloads[f"receipts/library/reads/{check.read_id}.json"]
            )
            if state.result_hash != check.result_hash or state.job.source_hash != check.source_hash:
                raise Conflict("verification reading binding mismatch")
            if check.result and check.result.packet_hash != check.packet_hash:
                raise Conflict("verification packet binding mismatch")
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
