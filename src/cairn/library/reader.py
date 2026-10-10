"""Resumable owner-side reading. Remote output can only become a proposal."""

from __future__ import annotations

import base64
import re
from collections.abc import Callable
from pathlib import Path

from cairn.adapters.protocol import Candidate, Job, Result
from cairn.errors import Blocked, CairnError, Conflict, Denied
from cairn.ingest.service import SourceType, capture_bytes, run_extraction_unlocked
from cairn.library.catalog import check_library_root, config_unlocked, get_paper
from cairn.library.device import device_path, exchange, load_device, require_device
from cairn.library.models import set_metadata
from cairn.library.reader_models import (
    PAGE_TEXT_BUDGET,
    VISUAL_ONLY,
    DeviceConfig,
    ReaderJob,
    ReaderResult,
    ReadState,
)
from cairn.library.store import commit_unlocked, entity_bytes, record_path
from cairn.proposals.models import JobEnvelope
from cairn.proposals.service import stage_result
from cairn.reading.skill import guidance_hash
from cairn.records.models import (
    Assertion,
    Event,
    EvidenceRef,
    Extraction,
    ExtractionMetadata,
    Record,
    canonical,
    digest,
    new_id,
    now,
)
from cairn.storage.files import RootFS
from cairn.storage.markdown import encode
from cairn.storage.workspace import Workspace


def state_path(job_id: str) -> str:
    from pydantic import TypeAdapter

    from cairn.records.models import ID

    TypeAdapter(ID).validate_python(job_id)
    return f"receipts/library/reads/{job_id}.json"


def jobs(ws: Workspace, scope: str = "research") -> list[ReadState]:
    with ws.lock():
        result = []
        for path in ws.fs.files("receipts/library/reads"):
            state = ReadState.model_validate_json(ws.fs.read(path))
            if state.job.scope == scope:
                get_paper(ws, state.job.paper_id, scope)
                result.append(state)
        return sorted(result, key=lambda item: (item.at, item.job.id))


def capture_paper(ws: Workspace, paper_id: str, scope: str = "research") -> Record:
    with ws.lock():
        config = config_unlocked(ws)
        record, paper = get_paper(ws, paper_id, scope)
        files = sorted(
            (f for f in paper.files if f.availability == "available" or f.source_id),
            key=lambda f: (f.availability == "available", f.mtime_ns, f.path),
            reverse=True,
        )
        if paper.conflicts:
            raise Blocked("paper_identity_requires_review")
        if files:
            location = files[0]
            try:
                raw = RootFS(check_library_root(ws, Path(config.root))).read(location.path)
            except (OSError, CairnError):
                if not location.source_id:
                    raise Blocked("paper_unavailable_and_not_preserved") from None
                _, preserved, _ = ws.record(location.source_id, ws.policy.scope(scope))
                if (
                    preserved.source is None
                    or preserved.source.content_hash != location.content_hash
                ):
                    raise Conflict("preserved library source mismatch") from None
                raw = ws.fs.read(preserved.source.blob)
            if digest(raw) != location.content_hash:
                raise Conflict("library file changed; scan before reading")
            source_type: SourceType = "pdf"
            origin = f"library:{config.id}/{location.path}"
        else:
            if not paper.abstract:
                raise Blocked("no_local_pdf_or_abstract")
            raw = canonical(
                {
                    "title": record.title,
                    "doi": paper.doi,
                    "authors": paper.authors,
                    "abstract": paper.abstract,
                }
            )
            source_type = "bibliography"
            origin = f"library:{config.id}/{paper_id}"
    source = capture_bytes(
        ws,
        raw,
        origin=origin,
        title=record.title,
        identity=f"library-paper:{paper_id}",
        domain="research",
        source_type=source_type,
        scope_name=scope,
        classification=record.classification,
        processing=record.processing,
        compartments=record.compartments,
        project_ids=record.project_ids,
        library_alias="cairn_library",
    )
    with ws.lock(write=True):
        record, paper = get_paper(ws, paper_id, scope)
        if source.id not in paper.source_ids:
            paper.source_ids.append(source.id)
        for file in paper.files:
            if file.content_hash == digest(raw):
                file.source_id = source.id
        set_metadata(record, paper)
        commit_unlocked(ws, {record_path(record): entity_bytes(record)}, "capture_paper")
    return source


def enqueue(
    ws: Workspace, paper_id: str, device_id: str, *, scope: str = "research", revision: int = 1
) -> ReadState:
    with ws.lock():
        device = require_device(ws, device_id, scope)
    source = capture_paper(ws, paper_id, scope)
    assert source.source is not None
    with ws.lock(write=True):
        if canonical(device) != canonical(require_device(ws, device_id, scope)):
            raise Conflict("device changed during capture")
        job = ReaderJob(
            id="read_pending",
            paper_id=paper_id,
            source_id=source.id,
            source_hash=source.source.content_hash,
            policy_hash=ws.policy_hash,
            device_hash=digest(canonical(device)),
            device_id=device.id,
            scope=scope,
            source_type="pdf" if source.source.source_type == "pdf" else "bibliography",
            title=source.title,
            model_hash=device.model_hash,
            projection_hash=device.projection_hash,
            reading_revision=revision,
            guidance_hash=guidance_hash(),
        )
        job.id = "read_" + digest(canonical(job))[:32]
        path = state_path(job.id)
        if ws.fs.exists(path):
            return ReadState.model_validate_json(ws.fs.read(path))
        state = ReadState(job=job, at=now())
        commit_unlocked(ws, {path: canonical(state)}, "queue_read")
        return state


def check_binding(ws: Workspace, job: ReaderJob) -> tuple[DeviceConfig, Record, bytes]:
    if job.prompt_version != "finch-paper-reader-v1" or job.guidance_hash != guidance_hash():
        raise Conflict("Finch guidance changed; queue a new reading revision")
    device = require_device(ws, job.device_id, job.scope)
    if digest(canonical(device)) != job.device_hash or ws.policy_hash != job.policy_hash:
        raise Conflict("reader route or policy changed")
    _, paper = get_paper(ws, job.paper_id, job.scope)
    _, source, _ = ws.record(job.source_id, ws.policy.scope(job.scope))
    if source.source is None or source.source.content_hash != job.source_hash:
        raise Conflict("reader source changed")
    raw = ws.fs.read(source.source.blob)
    if digest(raw) != job.source_hash:
        raise Conflict("reader source checksum changed")
    if job.source_type == "pdf" and not any(
        file.content_hash == job.source_hash for file in paper.files
    ):
        raise Conflict("selected library version is no longer current")
    if job.source_type == "bibliography":
        record, _ = get_paper(ws, job.paper_id, job.scope)
        if (
            digest(
                canonical(
                    {
                        "title": record.title,
                        "doi": paper.doi,
                        "authors": paper.authors,
                        "abstract": paper.abstract,
                    }
                )
            )
            != job.source_hash
        ):
            raise Conflict("bibliographic evidence changed")
    return device, source, raw


def cancel(ws: Workspace, job_id: str) -> ReadState:
    with ws.lock(write=True):
        state = ReadState.model_validate_json(ws.fs.read(state_path(job_id)))
        if state.status != "completed":
            state.status = "cancelled"
            state.at = now()
            commit_unlocked(ws, {state_path(job_id): canonical(state)}, "cancel_read")
    if state.status == "cancelled" and not ws.config.synthetic:
        try:
            device = load_device(ws, state.job.device_id)
            exchange(
                device,
                canonical({"operation": "cancel", "job_id": job_id, "image": device.image}),
                timeout=30,
            )
        except Exception:
            state.reason = "cancelled_locally_remote_cleanup_pending"
            with ws.lock(write=True):
                commit_unlocked(ws, {state_path(job_id): canonical(state)}, "cancel_read_pending")
    return state


_LINE_LOCATOR = re.compile(r"^page (\d+), line \d+$")


def _normalized(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if line.strip())


def owner_pages(extraction: Extraction) -> dict[int, str]:
    pages: dict[int, list[str]] = {}
    for segment in extraction.segments:
        match = _LINE_LOCATOR.match(segment.locator)
        if match is None:
            raise Conflict("unexpected deterministic extraction locator")
        pages.setdefault(int(match.group(1)), []).append(segment.text)
    return {page: "\n".join(lines) for page, lines in pages.items()}


def verify_device_text(result: ReaderResult, pages: dict[int, str]) -> None:
    """Device page text becomes evidence only if it matches owner-side extraction."""
    if any(page > result.page_count for page, text in pages.items() if _normalized(text)):
        raise Denied("reader page count disagrees with deterministic extraction")
    locators = [segment.locator for segment in result.extraction.segments]
    if len(locators) != len(set(locators)) or set(locators) != {
        f"page {page}" for page in result.inspected_pages
    }:
        raise Denied("reader segments do not match its inspected pages")
    for segment in result.extraction.segments:
        text = "" if segment.text == VISUAL_ONLY else segment.text
        device = _normalized(text)
        owner = _normalized(pages.get(int(segment.locator.removeprefix("page ")), ""))
        truncated = len(text) == PAGE_TEXT_BUDGET and owner.startswith(device)
        if device != owner and not truncated:
            raise Denied(f"reader text for {segment.locator} differs from deterministic extraction")


def accept_result(ws: Workspace, state: ReadState, result: ReaderResult) -> str:
    job = state.job
    if (
        result.job_id != job.id
        or result.input_hash != digest(canonical(job))
        or result.model_hash != job.model_hash
        or result.extraction.source_id != job.source_id
        or result.extraction.source_hash != job.source_hash
    ):
        raise Denied("reader result binding mismatch")
    if len(result.inspected_pages) > job.page_limit:
        raise Denied("reader exceeded its page budget")
    with ws.lock(write=True):
        device, source, raw = check_binding(ws, job)
        current = ReadState.model_validate_json(ws.fs.read(state_path(job.id)))
        if current.status == "cancelled":
            raise Conflict("reading was cancelled")
        if job.source_type == "pdf":
            # Parse untrusted PDF bytes only in the isolated extraction worker.
            pages = owner_pages(
                run_extraction_unlocked(
                    ws, source, raw, scope_name=job.scope, inline_synthetic=True
                )
            )
        else:
            pages = {1: raw.decode()}
        verify_device_text(result, pages)
        key = digest(canonical(result.extraction))
        if not ws.fs.exists(f"evidence/{key}.json"):
            ws.fs.write(f"evidence/{key}.json", canonical(result.extraction), exclusive=True)
        assert source.source is not None
        source.source.extraction = ExtractionMetadata(
            evidence_hash=key,
            method=result.extraction.method,
            method_version=result.extraction.method_version,
            coverage=result.extraction.coverage,
            images_inspected=bool(result.visual_pages),
            tables_inspected=result.extraction.tables_inspected,
        )
        source_path = f"vault/sources/{source.id}.md"
        ws.fs.write(source_path, encode(source, ""))
        ws.event(
            Event(
                id=new_id("event"),
                object_id=source.id,
                attempt_id=job.id,
                stage="extracted",
                at=now(),
                hashes={"evidence": key},
            )
        )
        proposal_job = Job(
            id="job_" + job.id.removeprefix("read_"),
            policy_hash=job.policy_hash,
            scope_name=job.scope,
            route="owner_device",
            provider="qwen3.5-9b",
            execution_image=device.image,
            source=source,
            extraction=result.extraction,
            evidence_hash=key,
            max_changes=1,
        )
        envelope = JobEnvelope(
            job=proposal_job,
            scope=ws.policy.scope(job.scope),
            input_hashes={
                source_path: digest(ws.fs.read(source_path)),
                f"evidence/{key}.json": key,
                device_path(device.id): job.device_hash,
            },
            protected_hashes=ws.protected_hashes(),
        )
        envelope_path = f"proposals/jobs/{proposal_job.id}.json"
        if ws.fs.exists(envelope_path) and ws.fs.read(envelope_path) != canonical(envelope):
            raise Conflict("reading already produced different evidence")
        ws.fs.write(envelope_path, canonical(envelope))
        commit_unlocked(
            ws, {f"receipts/library/results/{job.id}.json": canonical(result)}, "reader_result"
        )
    claims = result.summary.claims()
    refs = [
        EvidenceRef(
            id=source.id,
            source_hash=job.source_hash,
            evidence_hash=key,
            locator=f"page {claim.page}",
            quote=claim.quote,
        )
        for claim in claims
    ]
    record = Record(
        id="concept_" + job.id.removeprefix("read_"),
        type="concept",
        title=f"Reading: {source.title}"[:500],
        domain=source.domain,
        classification=source.classification,
        processing=source.processing,
        compartments=source.compartments,
        project_ids=source.project_ids,
        created_at=source.created_at,
        updated_at=source.created_at,
        sources=list({canonical(ref): ref for ref in refs}.values()),
        assertions=[
            Assertion(
                id=f"assertion_{job.id}_{i}",
                text=claim.text,
                kind=claim.kind,
                sources=[refs[i]],
            )
            for i, claim in enumerate(claims)
        ],
    )
    body = "# Unreviewed paper reading\n\n" + result.summary.summary + "\n\n"
    for field in ("research_question", "methods", "findings", "assumptions", "limitations"):
        body += f"## {field.replace('_', ' ').title()}\n\n"
        entries = getattr(result.summary, field)
        body += "\n".join(f"- {c.text} (page {c.page})" for c in entries) if entries else "Unknown."
        body += "\n\n"
    body += f"Coverage: {len(result.inspected_pages)}/{result.page_count} pages; "
    body += f"images inspected on {result.visual_pages}.\n"
    body += "\n".join(f"Warning: {warning}" for warning in result.summary.warnings)
    proposal = stage_result(
        ws,
        Result(
            job_id=proposal_job.id,
            input_hash=digest(canonical(proposal_job)),
            provider=proposal_job.provider,
            candidates=[
                Candidate(
                    record=record,
                    body=body,
                    rationale="Owner-device reading; requires evidence review",
                )
            ],
        ),
    )
    if proposal is None:
        raise Conflict("reading did not produce a proposal")
    return proposal.id


def run(
    ws: Workspace,
    job_id: str,
    *,
    retry: bool = False,
    transport: Callable[[DeviceConfig, bytes], bytes] | None = None,
) -> ReadState:
    if transport is not None and not ws.config.synthetic:
        raise Denied("injected reader transport is synthetic-only")
    with ws.lock(write=True):
        state = ReadState.model_validate_json(ws.fs.read(state_path(job_id)))
        if state.status == "completed" or (state.status == "cancelled" and not retry):
            return state
        if state.status == "running" and not retry:
            raise Blocked("read_running_use_explicit_retry_after_interruption")
        state.status = "running"
        state.at = now()
        state.attempts += 1
        state.reason = None
        commit_unlocked(ws, {state_path(job_id): canonical(state)}, "start_read")
    try:
        with ws.lock():
            device, _, raw = check_binding(ws, state.job)
            cached = f"receipts/library/results/{job_id}.json"
            result_raw = ws.fs.read(cached) if ws.fs.exists(cached) else None
        if result_raw is None:
            result_raw = (transport or exchange)(
                device,
                canonical(
                    {"operation": "read", "job": state.job, "data": base64.b64encode(raw).decode()}
                ),
            )
        result = ReaderResult.model_validate_json(result_raw)
        state.proposal_id = accept_result(ws, state, result)
        state.result_hash = digest(canonical(result))
        state.status = "completed"
    except Exception as exc:
        state.status = (
            "blocked"
            if isinstance(exc, Blocked)
            else ("stale" if isinstance(exc, Conflict) else "failed")
        )
        # Never persist raw client output, prompts, credentials, or remote diagnostics.
        state.reason = (
            str(exc) if isinstance(exc, (Blocked, Conflict, Denied)) else "invalid_reader_result"
        )
    with ws.lock(write=True):
        current = ReadState.model_validate_json(ws.fs.read(state_path(job_id)))
        if current.status == "cancelled":
            return current
        state.at = now()
        outputs = {state_path(job_id): canonical(state)}
        if state.status == "completed" and state.proposal_id:
            record, paper = get_paper(ws, state.job.paper_id, state.job.scope)
            if state.proposal_id not in paper.analysis_ids:
                paper.analysis_ids.append(state.proposal_id)
                set_metadata(record, paper)
                outputs[record_path(record)] = entity_bytes(record)
        commit_unlocked(ws, outputs, "finish_read")
    return state
