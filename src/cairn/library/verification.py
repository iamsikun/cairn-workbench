"""Deterministic sampling and bounded subscription exports authorized by the owner."""

from __future__ import annotations

import base64
from collections import defaultdict
from collections.abc import Callable

from cairn.adapters.isolation import invoke_worker
from cairn.errors import Blocked, Conflict, Denied
from cairn.ingest.service import capture_bytes
from cairn.library.catalog import get_paper
from cairn.library.models import Journal, metadata
from cairn.library.reader import jobs, state_path
from cairn.library.reader_models import ReaderResult, ReadState
from cairn.library.store import commit_unlocked
from cairn.library.subscriptions import verify as client_verify
from cairn.library.verification_models import (
    ProviderName,
    VerificationConfig,
    VerificationPacket,
    VerificationResult,
    VerificationState,
)
from cairn.policies.audit import set_grant
from cairn.policies.models import RouteGrant
from cairn.records.models import Labels, canonical, digest, now
from cairn.storage.workspace import Workspace

CONFIG = "receipts/library/verification.json"
DESTINATIONS = {"codex": "https://chatgpt.com", "claude": "https://claude.ai"}


def configure(ws: Workspace, config: VerificationConfig) -> None:
    if config.valid_until.tzinfo is None or config.valid_until <= now():
        raise Denied("verification consent requires a future timezone-aware expiry")
    with ws.lock():
        scope = ws.policy.scope(config.scope)
        for journal_id in config.journal_ids:
            _, record, _ = ws.record(journal_id, scope)
            if not isinstance(metadata(record), Journal):
                raise Denied("verification consent requires explicit journal IDs")
    # The owner authorizes ONLY separately preserved evidence packets. Original
    # PDFs, notes, catalog entries and reading outputs keep their processing labels.
    for provider in ("codex", "claude"):
        set_grant(
            ws,
            RouteGrant(
                id=f"grant_library_{provider}",
                scope=config.scope,
                provider=provider,
                destination=DESTINATIONS[provider],
                operations={"client_export"},
                valid_until=config.valid_until,
                owner_consent=config.owner_statement,
            ),
            base_hash=ws.policy_hash,
            statement=config.owner_statement,
        )
    with ws.lock(write=True):
        commit_unlocked(ws, {CONFIG: canonical(config)}, "owner_verification_consent")


def packet(ws: Workspace, state: ReadState) -> VerificationPacket:
    with ws.lock():
        get_paper(ws, state.job.paper_id, state.job.scope)
        raw = ws.fs.read(f"receipts/library/results/{state.job.id}.json")
        if digest(raw) != state.result_hash:
            raise Conflict("summary result changed")
        result = ReaderResult.model_validate_json(raw)
        _, source, _ = ws.record(state.job.source_id, ws.policy.scope(state.job.scope))
        assert source.source is not None
        source_bytes = ws.fs.read(source.source.blob)
        if digest(source_bytes) != state.job.source_hash:
            raise Conflict("verification source changed")
    cited_pages = sorted({claim.page for claim in result.summary.claims()})
    pages = cited_pages[:12]
    passages = [
        segment
        for segment in result.extraction.segments
        if segment.locator in {f"page {page}" for page in pages}
    ]
    images = {}
    visual = [p for p in pages if p in result.visual_pages][:4]
    if visual:
        if not ws.config.worker_image:
            raise Blocked("page_renderer_unavailable")
        from cairn.records.json import read_json

        images = read_json(
            invoke_worker(
                ws.config.worker_image,
                canonical(
                    {
                        "operation": "render_pages",
                        "data": base64.b64encode(source_bytes).decode(),
                        "pages": visual,
                    }
                ),
            )
        )
        if set(images) != {str(p) for p in visual}:
            raise Denied("renderer returned unexpected pages")
    return VerificationPacket(
        read_id=state.job.id,
        paper_id=state.job.paper_id,
        source_id=state.job.source_id,
        source_hash=state.job.source_hash,
        result_hash=digest(raw),
        summary=result.summary,
        passages=passages,
        images=images,
        coverage=result.extraction.coverage,
        omitted_pages=sorted(
            set(cited_pages) - set(pages) | (set(result.visual_pages) - set(visual))
        ),
    )


def select(ws: Workspace, scope: str = "research") -> dict[str, tuple[list[ProviderName], str]]:
    completed = [state for state in jobs(ws, scope) if state.status == "completed"]
    selected: dict[str, tuple[list[ProviderName], str]] = {}
    for state in completed[:10]:
        selected[state.job.id] = (["codex", "claude"], "first_ten_calibration")
    strata: dict[tuple[str, str], list[ReadState]] = defaultdict(list)
    with ws.lock():
        for state in completed[10:]:
            _, paper = get_paper(ws, state.job.paper_id, scope)
            result = ReaderResult.model_validate_json(
                ws.fs.read(f"receipts/library/results/{state.job.id}.json")
            )
            mode = "visual" if result.visual_pages else "text"
            for journal_id in paper.journal_ids:
                ws.record(journal_id, ws.policy.scope(scope))
                strata[(journal_id, mode)].append(state)
            if result.summary.warnings or result.extraction.coverage != "full_text":
                selected[state.job.id] = (["codex", "claude"], "flagged_evidence")
    # One hash-selected position per cohort of ten in each journal/modality.
    # Completed cohorts are exactly 10%; a partial cohort has 0 or 1 selections.
    # Decisions do not change when later readings arrive.
    for key, states in sorted(strata.items()):
        for index, state in enumerate(states):
            cohort, position = divmod(index, 10)
            if position == int(digest(canonical([key, cohort])), 16) % 10:
                selected.setdefault(
                    state.job.id,
                    (
                        [
                            "codex"
                            if (cohort + int(digest(canonical(key)), 16)) % 2 == 0
                            else "claude"
                        ],
                        "stratified_ten_percent",
                    ),
                )
    return selected


def checks(ws: Workspace, read_id: str) -> list[VerificationState]:
    state = ReadState.model_validate_json(ws.fs.read(state_path(read_id)))
    get_paper(ws, state.job.paper_id, state.job.scope)
    return [
        value
        for path in ws.fs.files("receipts/library/checks")
        if (value := VerificationState.model_validate_json(ws.fs.read(path))).read_id == read_id
    ]


def run_check(
    ws: Workspace,
    state: ReadState,
    provider: ProviderName,
    reason: str,
    client: Callable[[ProviderName, str, VerificationPacket], VerificationResult] | None = None,
) -> VerificationState:
    if client is not None and not ws.config.synthetic:
        raise Denied("injected verifier is synthetic-only")
    identity = "verify_" + digest(canonical([state.job.id, state.result_hash, provider]))[:32]
    path = f"receipts/library/checks/{identity}.json"
    with ws.lock():
        if ws.fs.exists(path):
            old = VerificationState.model_validate_json(ws.fs.read(path))
            if old.status == "completed":
                return old
    check = VerificationState(
        id=identity,
        read_id=state.job.id,
        packet_hash="0" * 64,
        result_hash=state.result_hash or "0" * 64,
        source_hash=state.job.source_hash,
        provider=provider,
        reason=reason,
        at=now(),
    )
    try:
        with ws.lock():
            if not ws.fs.exists(CONFIG):
                raise Blocked("owner_verification_consent_not_configured")
            config_raw = ws.fs.read(CONFIG)
            config = VerificationConfig.model_validate_json(config_raw)
            record, paper = get_paper(ws, state.job.paper_id, state.job.scope)
            if (
                config.scope != state.job.scope
                or config.valid_until <= now()
                or not set(paper.journal_ids) & set(config.journal_ids)
            ):
                raise Denied("verification consent does not cover this reading")
            policy_hash = ws.policy_hash
        payload = packet(ws, state)
        raw = canonical(payload)
        if len(raw) > 20 * 1024 * 1024:
            raise Blocked("verification_packet_exceeds_budget")
        check.packet_hash = digest(raw)
        # This owner-controlled copy is an explicit, bounded export. It does not
        # relabel the paper or give models access to its workspace or human notes.
        exported = capture_bytes(
            ws,
            raw,
            origin=f"verification:{state.job.id}",
            identity=f"verification-packet:{check.packet_hash}",
            title="Bounded verification packet",
            domain="research",
            source_type="text",
            classification=record.classification,
            processing="cloud_eligible",
            compartments=record.compartments,
            project_ids=record.project_ids,
            scope_name=config.scope,
        )
        with ws.lock(write=True):
            if ws.policy_hash != policy_hash or ws.fs.read(CONFIG) != config_raw:
                raise Conflict("verification consent changed")
            labels = Labels(
                domain="research",
                classification=record.classification,
                processing="cloud_eligible",
                compartments=record.compartments,
            )
            ws.policy.authorize_route(
                ws.policy.scope(config.scope),
                [exported],
                route="cloud",
                provider=provider,
                operation="client_export",
                destination=DESTINATIONS[provider],
                question=labels,
                extra_parts=[labels],
            )
            commit_unlocked(ws, {path: canonical(check)}, "verification_export_authorized")
        value = (client or client_verify)(
            provider, config.codex_model if provider == "codex" else config.claude_model, payload
        )
        if value.packet_hash != check.packet_hash:
            raise Denied("verification binding mismatch")
        with ws.lock():
            current = ReadState.model_validate_json(ws.fs.read(state_path(state.job.id)))
            if (
                current.result_hash != state.result_hash
                or ws.policy_hash != policy_hash
                or ws.fs.read(CONFIG) != config_raw
            ):
                raise Conflict("verification became stale")
        check.result = value
        check.status = "completed"
    except Exception as exc:
        check.status = "stale" if isinstance(exc, Conflict) else "blocked"
        check.issue = (
            str(exc) if isinstance(exc, (Blocked, Conflict, Denied)) else "invalid_verifier_output"
        )
    with ws.lock(write=True):
        commit_unlocked(ws, {path: canonical(check)}, "verification_result")
    return check


def verify(
    ws: Workspace,
    scope: str = "research",
    *,
    client: Callable[[ProviderName, str, VerificationPacket], VerificationResult] | None = None,
) -> list[VerificationState]:
    selected = select(ws, scope)
    completed = {state.job.id: state for state in jobs(ws, scope) if state.status == "completed"}
    # Retry queued/blocked checks even when the hash-ranked sample changes later.
    with ws.lock():
        for path in ws.fs.files("receipts/library/checks"):
            old = VerificationState.model_validate_json(ws.fs.read(path))
            if old.read_id in completed:
                providers, reason = selected.setdefault(old.read_id, ([], old.reason))
                if old.provider not in providers:
                    providers.append(old.provider)
    output = []
    with ws.lock(write=True):
        plans = {
            f"receipts/library/verification_plans/{read_id}.json": canonical(
                {
                    "read_id": read_id,
                    "result_hash": state.result_hash,
                    "providers": selected.get(read_id, ([], "not_sampled"))[0],
                }
            )
            for read_id, state in completed.items()
        }
        commit_unlocked(ws, plans, "verification_sampling_plan")
    for read_id, (providers, reason) in sorted(selected.items()):
        state = completed[read_id]
        results = [run_check(ws, state, p, reason, client) for p in providers]
        if any(item.result and item.result.verdict != "supported" for item in results):
            for provider in ("codex", "claude"):
                if provider not in providers:
                    results.append(run_check(ws, state, provider, "concern_escalation", client))
        output.extend(results)
    return output


def require_ready_for_acceptance(ws: Workspace, proposal_id: str) -> None:
    from cairn.records.json import read_json

    for path in ws.fs.files("receipts/library/reads"):
        state = ReadState.model_validate_json(ws.fs.read(path))
        if state.proposal_id != proposal_id:
            continue
        plan_path = f"receipts/library/verification_plans/{state.job.id}.json"
        if not ws.fs.exists(plan_path):
            raise Blocked("run library verify before accepting a reading")
        plan = read_json(ws.fs.read(plan_path))
        completed = {
            value.provider
            for value in checks(ws, state.job.id)
            if value.status == "completed" and value.result_hash == state.result_hash
        }
        if plan["result_hash"] != state.result_hash or not set(plan["providers"]) <= completed:
            raise Blocked("required subscription verification is pending")
        require_no_failed_checks(ws, proposal_id)


def require_no_failed_checks(ws: Workspace, proposal_id: str) -> None:
    # Called inside proposal validation's existing workspace lock.
    for path in ws.fs.files("receipts/library/reads"):
        state = ReadState.model_validate_json(ws.fs.read(path))
        if state.proposal_id != proposal_id:
            continue
        for check in checks(ws, state.job.id):
            if check.result_hash != state.result_hash:
                raise Conflict("verification belongs to an older reading")
            if check.result and check.result.verdict != "supported":
                raise Denied("verification concerns block acceptance; revise and reread the paper")
