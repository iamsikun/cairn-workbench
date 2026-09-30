"""Read-only owner reports with escaped text and links derived from safe local paths."""

from __future__ import annotations

import difflib
import re
import unicodedata
from urllib.parse import quote

from cairn.errors import CairnError, Denied
from cairn.ingest.service import load_extraction
from cairn.proposals.models import Proposal
from cairn.proposals.service import (
    all_refs,
    check_reference,
    load_job,
    target_path,
    validate_unlocked,
)
from cairn.records.models import EvidenceRef, canonical, digest
from cairn.storage.markdown import decode
from cairn.storage.workspace import Workspace


def _controls(value: str) -> str:
    return "".join(
        f"\\u{ord(character):04x}"
        if unicodedata.category(character) in ("Cc", "Cf") and character not in "\n\t"
        else character
        for character in value
    )


def _text(value: str, markdown: bool) -> str:
    value = _controls(value).replace("\n", " ").replace("\t", " ")
    return re.sub(r"([\\`*_{}\[\]<>()!#|>~])", r"\\\1", value) if markdown else value


def _block(value: str, language: str, markdown: bool) -> str:
    value = _controls(value)
    if not markdown:
        return value
    fence = "`" * max(3, 1 + max((len(run) for run in re.findall(r"`+", value)), default=0))
    value = value.removesuffix("\n")
    return f"{fence}{language}\n{value}\n{fence}"


def render_review(ws: Workspace, proposal: Proposal, *, markdown: bool = False) -> str:
    """Caller holds the owner lock. No approvals, events, or caches are written."""
    job = load_job(ws, proposal.job_id).job
    scope = ws.policy.scope(job.scope_name)
    # A previously sealed job does not override later scope revocation. Check current
    # input membership before exposing either proposed text or imported titles.
    for record_id in [job.source.id, *(page.record.id for page in job.related)]:
        ws.record(record_id, scope)
    records = [decode(change.content.encode())[0] for change in proposal.changes]
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
    heading = "# " if markdown else ""
    lines = [
        f"{heading}Proposal {_text(proposal.id, markdown)}",
        "",
        _text(validation, markdown),
        f"Proposal SHA256: {digest(canonical(proposal))}",
        f"Provider: {_text(proposal.provider, markdown)}; route: {proposal.route}; "
        f"scope: {_text(job.scope_name, markdown)}",
        f"Pages affected: {len(proposal.changes)}",
        "Required acknowledgements: " + _text(", ".join(sorted(proposal.review_flags)), markdown),
        "Quote matches establish presence, not entailment. Reviewed does not mean true.",
        "Diffs below compare the proposed bytes with the current canonical files.",
        "",
    ]
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
        lines.extend(
            [
                ("## " if markdown else "") + _text(record.title, markdown),
                "",
                f"Record: {_text(record.id, markdown)}; target: {_text(path, markdown)}",
                f"Expected base: {change.base_hash or 'new file'}; "
                f"current: {digest(before.encode()) if before else 'absent or empty'}",
                f"Proposed SHA256: {digest(change.content.encode())}",
                "Rationale: " + _text(change.rationale, markdown),
                "Applicability: "
                + _text(
                    "; ".join(
                        f"{key.replace('_', ' ')}: {value}"
                        for key, value in record.period.model_dump(
                            mode="json", exclude_none=True
                        ).items()
                    )
                    if record.period
                    else "unknown",
                    markdown,
                ),
            ]
        )
        for assertion in record.assertions:
            if (
                assertion.disputes
                or assertion.supersedes
                or assertion.verification in ("disputed", "superseded")
            ):
                lines.append(
                    _text(
                        f"Conflict: {assertion.id}; {assertion.verification}; "
                        f"disputes={','.join(assertion.disputes)}; "
                        f"supersedes={','.join(assertion.supersedes)}; "
                        f"rationale={assertion.rationale or 'unknown'}",
                        markdown,
                    )
                )
        lines.extend(["", _block(actual_diff, "diff", markdown), ""])
    lines.extend([("## " if markdown else "") + "Evidence", ""])
    for ref in refs.values():
        source_path, source, _ = ws.record(ref.id, scope)
        assert source.source
        extraction, evidence_hash = load_extraction(ws, source)
        try:
            check_reference(ws, ref, job.scope_name)
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
            # RootFS validates paths, including links/hardlinks, before making them clickable.
            ws.fs.read(path)
            link = quote(str(ws.root / path), safe="/")
            lines.append(f"[{_text(label, True)}](<{link}>)" if markdown else f"{label}: {link}")
        if ref.quote is not None:
            lines.extend(["", _block(ref.quote, "text", markdown)])
        lines.append("")
    return "\n".join(lines)
