import json
from pathlib import Path

import pytest
from test_library_catalog import library, pdf

from cairn.errors import Blocked, Conflict, Denied
from cairn.library.catalog import get_paper, scan
from cairn.library.device import enroll, revoke
from cairn.library.reader import cancel, enqueue, run
from cairn.library.reader_models import (
    DeviceConfig,
    DeviceProbe,
    PaperClaim,
    PaperSummary,
    ReaderJob,
    ReaderResult,
)
from cairn.library.reader_worker import read
from cairn.proposals.service import validate
from cairn.records.models import Extraction, Segment, canonical, digest, now
from cairn.records.runtime import PROBE_CHECKS, ProbeResult
from cairn.storage.workspace import Workspace


def enrolled(ws: Workspace) -> DeviceConfig:
    config = DeviceConfig(
        id="device_example",
        ssh_alias="example",
        known_hosts="/keys/known_hosts",
        known_hosts_hash="1" * 64,
        image="sha256:" + "2" * 64,
        model_hash="3" * 64,
        projection_hash="4" * 64,
        model_revision="5" * 40,
        runtime_revision="6" * 40,
    )

    def probe(config: DeviceConfig, raw: bytes) -> bytes:
        nonce = json.loads(raw)["nonce"]
        return canonical(
            DeviceProbe(
                nonce=nonce,
                image=config.image,
                model_hash=config.model_hash,
                projection_hash=config.projection_hash,
                result=ProbeResult(nonce=nonce, checks=dict.fromkeys(PROBE_CHECKS, True)),
                host_canary_preserved=True,
                gpu="SYNTHETIC GPU; no hardware or quality evidence",
                at=now(),
            )
        )

    return enroll(ws, config, probe)


def setup(ws: Workspace, tmp_path: Path) -> tuple[str, DeviceConfig]:
    root = library(ws, tmp_path)
    (root / "Example Journal" / "a.pdf").write_bytes(pdf())
    return scan(ws).added[0], enrolled(ws)


def response(config: DeviceConfig, packet: bytes) -> bytes:
    job = ReaderJob.model_validate(json.loads(packet)["job"])
    return canonical(
        ReaderResult(
            job_id=job.id,
            input_hash=digest(canonical(job)),
            model_hash=job.model_hash,
            extraction=Extraction(
                source_id=job.source_id,
                source_hash=job.source_hash,
                method="synthetic",
                method_version="1",
                coverage="full_text",
                segments=[Segment(locator="page 1", text="Synthetic result: four examples.")],
            ),
            summary=PaperSummary(
                summary="Synthetic reading",
                findings=[PaperClaim(text="Four examples", page=1, quote="four examples")],
            ),
            inspected_pages=[1],
            page_count=1,
        )
    )


def test_read_is_idempotent_proposal_only(ws: Workspace, tmp_path: Path) -> None:
    paper_id, device = setup(ws, tmp_path)
    state = enqueue(ws, paper_id, device.id)
    assert enqueue(ws, paper_id, device.id).job.id == state.job.id
    result = run(ws, state.job.id, transport=response)
    assert result.status == "completed", result.reason
    assert run(ws, state.job.id, transport=response) == result
    assert result.proposal_id
    assert validate(ws, result.proposal_id).route == "owner_device"
    with ws.lock():
        _, paper = get_paper(ws, paper_id, "research")
        assert paper.reading == "unknown" and paper.analysis_ids == [result.proposal_id]
        assert not ws.fs.files("approvals")


def test_unavailable_retry_and_revoked_device(ws: Workspace, tmp_path: Path) -> None:
    paper_id, device = setup(ws, tmp_path)
    state = enqueue(ws, paper_id, device.id)

    def unavailable(*args: object) -> bytes:
        raise Blocked("owner_device_unavailable")

    assert run(ws, state.job.id, transport=unavailable).status == "blocked"
    completed = run(ws, state.job.id, retry=True, transport=response)
    assert completed.status == "completed"
    revoke(ws, device.id)
    with pytest.raises((Conflict, Denied)):
        validate(ws, completed.proposal_id or "proposal_missing")


def test_preserved_pdf_can_be_read_while_box_is_offline(ws: Workspace, tmp_path: Path) -> None:
    paper_id, device = setup(ws, tmp_path)
    root = tmp_path / "synthetic-library"
    root.rename(tmp_path / "offline-library")
    assert not scan(ws).complete
    state = enqueue(ws, paper_id, device.id)
    assert run(ws, state.job.id, transport=response).status == "completed"


def test_cancellation_and_changed_source(ws: Workspace, tmp_path: Path) -> None:
    paper_id, device = setup(ws, tmp_path)
    state = enqueue(ws, paper_id, device.id)
    cancel(ws, state.job.id)
    assert run(ws, state.job.id, transport=response).status == "cancelled"
    (tmp_path / "synthetic-library/Example Journal/a.pdf").write_bytes(pdf("Changed"))
    scan(ws)
    assert run(ws, state.job.id, retry=True, transport=response).status == "stale"


def test_fabricated_quote_rejected(ws: Workspace, tmp_path: Path) -> None:
    paper_id, device = setup(ws, tmp_path)
    state = enqueue(ws, paper_id, device.id)

    def fabricated(config: DeviceConfig, packet: bytes) -> bytes:
        data = json.loads(response(config, packet))
        data["summary"]["findings"][0]["quote"] = "unsupported numerical claim"
        return canonical(data)

    assert run(ws, state.job.id, transport=fabricated).status == "failed"


def test_worker_visual_scans_and_bad_references(ws: Workspace, tmp_path: Path) -> None:
    paper_id, device = setup(ws, tmp_path)
    job = enqueue(ws, paper_id, device.id).job
    with ws.lock():
        source = ws.record(job.source_id)[1]
        assert source.source
        raw = ws.fs.read(source.source.blob)
    result = read(
        job,
        raw,
        lambda _: PaperSummary(
            summary="Image inspected", limitations=[PaperClaim(text="Synthetic blank page", page=1)]
        ),
        lambda *_: "synthetic",
    )
    assert result.visual_pages == [1]
    with pytest.raises(ValueError, match="uninspected"):
        read(
            job,
            raw,
            lambda _: PaperSummary(
                summary="Bad reference", findings=[PaperClaim(text="Invented", page=2)]
            ),
            lambda *_: "synthetic",
        )
