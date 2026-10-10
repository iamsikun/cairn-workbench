import io
import json
from pathlib import Path

import pypdf
import pytest
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
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


PAGE_TEXT = "Synthetic result: four examples."


def text_pdf(text: str = PAGE_TEXT) -> bytes:
    """A one-page synthetic PDF whose deterministic text extraction is ``text``."""
    writer = pypdf.PdfWriter()
    page = writer.add_blank_page(width=300, height=100)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
    )
    content = DecodedStreamObject()
    content.set_data(f"BT /F1 10 Tf 10 50 Td ({text}) Tj ET".encode())
    page[NameObject("/Contents")] = writer._add_object(content)
    writer.add_metadata({"/Title": "Synthetic paper", "/Author": "A. Example"})
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def setup(ws: Workspace, tmp_path: Path, data: bytes | None = None) -> tuple[str, DeviceConfig]:
    root = library(ws, tmp_path)
    (root / "Example Journal" / "a.pdf").write_bytes(text_pdf() if data is None else data)
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
                segments=[Segment(locator="page 1", text=PAGE_TEXT)],
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


def test_device_text_must_match_owner_extraction(ws: Workspace, tmp_path: Path) -> None:
    # A device that invents page text and quotes it consistently passes its own
    # result validation; only the owner-side deterministic comparison catches it.
    paper_id, device = setup(ws, tmp_path)
    state = enqueue(ws, paper_id, device.id)

    def invented(config: DeviceConfig, packet: bytes) -> bytes:
        data = json.loads(response(config, packet))
        data["extraction"]["segments"][0]["text"] = "Synthetic effect is significant."
        data["summary"]["findings"][0]["quote"] = "effect is significant"
        return canonical(data)

    failed = run(ws, state.job.id, transport=invented)
    assert failed.status == "failed"
    assert not failed.proposal_id
    assert run(ws, state.job.id, retry=True, transport=response).status == "completed"


def test_device_cannot_understate_page_count(ws: Workspace, tmp_path: Path) -> None:
    writer = pypdf.PdfWriter()
    for text in ("Synthetic first page.", "Synthetic second page."):
        writer.add_page(pypdf.PdfReader(io.BytesIO(text_pdf(text))).pages[0])
    out = io.BytesIO()
    writer.write(out)
    paper_id, device = setup(ws, tmp_path, out.getvalue())
    state = enqueue(ws, paper_id, device.id)

    def one_page(config: DeviceConfig, packet: bytes) -> bytes:
        data = json.loads(response(config, packet))
        data["extraction"]["segments"][0]["text"] = "Synthetic first page."
        data["summary"]["findings"][0]["quote"] = "first page"
        return canonical(data)

    assert run(ws, state.job.id, transport=one_page).status == "failed"


def test_worker_visual_scans_and_bad_references(ws: Workspace, tmp_path: Path) -> None:
    paper_id, device = setup(ws, tmp_path, pdf())
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
