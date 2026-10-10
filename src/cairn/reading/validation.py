"""Validate durable Finch artifacts on backup/restore without authorizing execution."""

from collections.abc import Mapping

from cairn.errors import Conflict
from cairn.presentation.writing_models import ExportReceipt
from cairn.proposals.models import Proposal
from cairn.reading.models import FinchGuard, FinchPacket, FinchReceipt, FinchResponse
from cairn.reading.workflow import PREFIX, identity
from cairn.records.models import Record, canonical, digest
from cairn.storage.files import components


def validate_reading(payloads: Mapping[str, bytes], records: dict[str, Record]) -> None:
    packets = {}
    for path, raw in payloads.items():
        if not path.startswith(f"{PREFIX}/jobs/"):
            continue
        stored_packet = FinchPacket.model_validate_json(raw)
        if path != f"{PREFIX}/jobs/{stored_packet.id}.json" or stored_packet.id != identity(
            stored_packet
        ):
            raise Conflict("saved Finch packet identity mismatch")
        guard_path = f"{PREFIX}/guards/{stored_packet.id}.json"
        guard_raw = payloads.get(guard_path)
        if guard_raw is None or digest(guard_raw) != stored_packet.guard_hash:
            raise Conflict("saved Finch owner guard missing or corrupt")
        guard = FinchGuard.model_validate_json(guard_raw)
        for name in {**stored_packet.input_hashes, **guard.protected_hashes}:
            components(name)
        evidence = payloads.get(f"evidence/{stored_packet.evidence_hash}.json")
        if evidence != canonical(stored_packet.extraction):
            raise Conflict("saved Finch extraction mismatch")
        if (
            stored_packet.source.source is None
            or stored_packet.source.id != stored_packet.extraction.source_id
            or stored_packet.source.source.content_hash != stored_packet.extraction.source_hash
        ):
            raise Conflict("saved Finch source binding mismatch")
        packets[stored_packet.id] = stored_packet
    for path, raw in payloads.items():
        if not path.startswith(f"{PREFIX}/") or path.startswith(f"{PREFIX}/jobs/"):
            continue
        if path.startswith(f"{PREFIX}/submissions/"):
            # Retry records name the receipt they returned; it must be the saved import.
            submitted = FinchReceipt.model_validate_json(raw)
            imported = payloads.get(f"{PREFIX}/imports/{submitted.session_id}.json")
            if imported is None or FinchReceipt.model_validate_json(imported) != submitted:
                raise Conflict("saved Finch submission does not match its import")
            continue
        session_id = path.rsplit("/", 1)[-1].removesuffix(".json")
        packet = packets.get(session_id)
        if packet is None:
            raise Conflict("saved Finch artifact has no packet")
        category = path.removeprefix(f"{PREFIX}/").split("/", 1)[0]
        if category == "guards":
            continue
        if category == "exports":
            exported = ExportReceipt.model_validate_json(raw)
            if (
                exported.job_id != session_id
                or exported.input_hash != digest(canonical(packet))
                or exported.policy_hash != packet.policy_hash
                or exported.provider != packet.provider
                or exported.destination != packet.destination
            ):
                raise Conflict("saved Finch export mismatch")
        elif category == "responses":
            response = FinchResponse.model_validate_json(raw)
            if response.session_id != session_id or response.input_hash != digest(
                canonical(packet)
            ):
                raise Conflict("saved Finch response mismatch")
            for claim in response.claims:
                for ref in claim.sources:
                    segments = [
                        s.text for s in packet.extraction.segments if s.locator == ref.locator
                    ]
                    if (
                        ref.id != packet.source.id
                        or ref.source_hash != packet.extraction.source_hash
                        or ref.evidence_hash != packet.evidence_hash
                        or not segments
                        or (ref.quote is not None and not any(ref.quote in s for s in segments))
                    ):
                        raise Conflict("saved Finch claim evidence mismatch")
        elif category == "imports":
            receipt = FinchReceipt.model_validate_json(raw)
            response_raw = payloads.get(f"{PREFIX}/responses/{session_id}.json")
            proposal_raw = payloads.get(f"proposals/{receipt.proposal_id}.json")
            if (
                receipt.session_id != session_id
                or response_raw is None
                or digest(response_raw) != receipt.response_hash
                or f"blobs/{receipt.response_hash}" not in payloads
                or proposal_raw is None
            ):
                raise Conflict("saved Finch import binding mismatch")
            proposal = Proposal.model_validate_json(proposal_raw)
            if proposal.job_id != "job_finch_" + session_id.removeprefix("finch_"):
                raise Conflict("saved Finch proposal binding mismatch")
            source = records.get(receipt.source_id)
            if (
                source is None
                or source.source is None
                or source.source.content_hash != receipt.response_hash
            ):
                raise Conflict("saved Finch conversation binding mismatch")
        else:
            raise Conflict("unknown saved Finch artifact")
