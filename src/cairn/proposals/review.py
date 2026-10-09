"""Shared read-only review model and terminal/Markdown presentation."""

from __future__ import annotations

import difflib
import re
import unicodedata
from urllib.parse import quote

from cairn.errors import CairnError, Denied
from cairn.ingest.service import load_extraction
from cairn.presentation.models import ReviewChange, ReviewReport
from cairn.proposals.models import Approval, Proposal
from cairn.proposals.service import (
    all_refs,
    check_reference,
    load_job,
    target_path,
    validate_unlocked,
)
from cairn.records.models import Event, EvidenceRef, canonical, digest
from cairn.storage.markdown import decode
from cairn.storage.workspace import Workspace


def _controls(value: str) -> str:
    return "".join(
        f"\\u{ord(c):04x}" if unicodedata.category(c) in ("Cc", "Cf") and c not in "\n\t" else c
        for c in value
    )


def _text(value: str, markdown: bool) -> str:
    value = _controls(value).replace("\n", " ").replace("\t", " ")
    return re.sub(r"([\\`*_{}\[\]<>()!#|>~])", r"\\\1", value) if markdown else value


def _block(value: str, language: str, markdown: bool) -> str:
    value = _controls(value)
    if not markdown:
        return value
    fence = "`" * max(3, 1 + max((len(x) for x in re.findall(r"`+", value)), default=0))
    return f"{fence}{language}\n{value.removesuffix(chr(10))}\n{fence}"


def review_stage(ws: Workspace, proposal: Proposal) -> str:
    from cairn.transactions.apply import ApplyReceipt

    key = digest(canonical(proposal))
    applied = f"receipts/applied/{proposal.id}.json"
    approved = f"approvals/{proposal.id}.json"
    if ws.fs.exists(applied):
        receipt = ApplyReceipt.model_validate_json(ws.fs.read(applied))
        if receipt.proposal_hash == key:
            return "applied"
    if ws.fs.exists(approved):
        approval = Approval.model_validate_json(ws.fs.read(approved))
        if approval.proposal_hash == key and approval.policy_hash == ws.policy_hash:
            return "owner approved"
    for path in ws.fs.files("receipts/events"):
        event = Event.model_validate_json(ws.fs.read(path))
        if (
            event.attempt_id == proposal.id
            and event.stage == "validated"
            and event.hashes.get("proposal") == key
        ):
            return "validated previously; current validity shown separately"
    return "proposed"


def review_snapshot(ws: Workspace, proposal: Proposal) -> str:
    envelope = load_job(ws, proposal.job_id)
    paths = set(envelope.input_hashes) | set(envelope.protected_hashes)
    paths.update((f"approvals/{proposal.id}.json", f"receipts/applied/{proposal.id}.json"))
    for path in ws.fs.files("receipts/events"):
        if Event.model_validate_json(ws.fs.read(path)).attempt_id == proposal.id:
            paths.add(path)
    return digest(
        canonical({p: digest(ws.fs.read(p)) if ws.fs.exists(p) else None for p in sorted(paths)})
    )


def review_model(ws: Workspace, proposal: Proposal) -> ReviewReport:
    """Caller holds the owner lock. No approval, validation event, or durable write."""
    job = load_job(ws, proposal.job_id).job
    scope = ws.policy.scope(job.scope_name)
    for record_id in [job.source.id, *(p.record.id for p in job.related)]:
        ws.record(record_id, scope)
    records = [decode(c.content.encode())[0] for c in proposal.changes]
    refs: dict[bytes, EvidenceRef] = {}
    for record in records:
        scope.require(record)
        for ref in all_refs(record):
            ws.record(ref.id, scope)
            refs[canonical(ref)] = ref
    try:
        validate_unlocked(ws, proposal)
        validation = "Valid against current inputs; owner approval is still required."
    except Denied:
        raise
    except CairnError as exc:
        validation = f"Not valid for apply: {exc.code}: {exc}"
    changes = []
    for change, record in zip(proposal.changes, records, strict=True):
        path = target_path(record)
        before = ws.fs.read(path).decode() if ws.fs.exists(path) else ""
        actual_diff = "".join(
            line if line.endswith("\n") else line + "\n\\ No newline at end of file\n"
            for line in difflib.unified_diff(
                before.splitlines(keepends=True),
                change.content.splitlines(keepends=True),
                fromfile=f"current/{path}",
                tofile=f"proposed/{path}",
            )
        )
        changes.append(
            ReviewChange(
                id=record.id,
                title=record.title,
                target=path,
                base_hash=change.base_hash,
                current_hash=digest(before.encode()) if before else None,
                proposed_hash=digest(change.content.encode()),
                rationale=change.rationale,
                period=record.period,
                diff=actual_diff,
                assertions=record.assertions,
                conflicts=[
                    f"Conflict: {a.id}; {a.verification}; disputes={','.join(a.disputes)}; "
                    f"supersedes={','.join(a.supersedes)}; rationale={a.rationale or 'unknown'}"
                    for a in record.assertions
                    if a.disputes or a.supersedes or a.verification in ("disputed", "superseded")
                ],
            )
        )
    return ReviewReport(
        id=proposal.id,
        proposal_hash=digest(canonical(proposal)),
        provider=proposal.provider,
        route=proposal.route,
        scope=job.scope_name,
        validation=validation,
        stage=review_stage(ws, proposal),
        review_flags=sorted(proposal.review_flags),
        changes=changes,
        references=list(refs.values()),
    )


def render_review(ws: Workspace, proposal: Proposal, *, markdown: bool = False) -> str:
    report = review_model(ws, proposal)
    lines = [
        ("# " if markdown else "") + f"Proposal {report.id}",
        "",
        _text(report.validation, markdown),
        f"Proposal SHA256: {report.proposal_hash}",
        f"Stage: {report.stage}",
        f"Provider: {_text(report.provider, markdown)}; "
        f"route: {report.route}; scope: {report.scope}",
        f"Pages affected: {len(report.changes)}",
        "Required acknowledgements: " + _text(", ".join(report.review_flags), markdown),
        "Quote matches establish presence, not entailment. Reviewed does not mean true.",
        "Diffs below compare the proposed bytes with the current canonical files.",
        "",
    ]
    for c in report.changes:
        period = (
            "; ".join(
                f"{key.replace('_', ' ')}: {value}"
                for key, value in c.period.model_dump(mode="json", exclude_none=True).items()
            )
            if c.period
            else "unknown"
        )
        lines.extend(
            [
                ("## " if markdown else "") + _text(c.title, markdown),
                "",
                f"Record: {c.id}; target: {c.target}",
                f"Expected base: {c.base_hash or 'new file'}; "
                f"current: {c.current_hash or 'absent or empty'}",
                f"Proposed SHA256: {c.proposed_hash}",
                "Rationale: " + _text(c.rationale, markdown),
                "Applicability: " + _text(period, markdown),
                *(_text(x, markdown) for x in c.conflicts),
                "",
                _block(c.diff, "diff", markdown),
                "",
            ]
        )
    lines.extend([("## " if markdown else "") + "Evidence", ""])
    for ref in report.references:
        source_path, source, _ = ws.record(ref.id, ws.policy.scope(report.scope))
        assert source.source
        extraction, evidence_hash = load_extraction(ws, source)
        try:
            check_reference(ws, ref, report.scope)
            support = "Hash, locator, and any quote match."
        except CairnError as exc:
            support = f"Unsupported citation: {exc}"
        lines.extend(
            [
                _text(f"{source.title} — {ref.id}; {ref.locator}", markdown),
                _text(
                    f"Date: {source.source.source_date or 'unknown'}; "
                    f"version: {source.source.version or 'unknown'}; "
                    f"coverage: {extraction.coverage}; "
                    f"tables inspected: {extraction.tables_inspected}; "
                    f"images inspected: {extraction.images_inspected}",
                    markdown,
                ),
                _text(support, markdown),
            ]
        )
        for label, path in (
            ("Source manifest", source_path),
            ("Original bytes", source.source.blob),
            (f"Evidence at {ref.locator}", f"evidence/{evidence_hash}.json"),
        ):
            ws.fs.read(path)
            link = quote(str(ws.root / path), safe="/")
            lines.append(f"[{_text(label, True)}](<{link}>)" if markdown else f"{label}: {link}")
        if ref.quote is not None:
            lines.extend(["", _block(ref.quote, "text", markdown)])
        lines.append("")
    return "\n".join(lines)
