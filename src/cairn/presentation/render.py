"""Deterministic templates; the renderer receives text values, never source markup."""

from __future__ import annotations

from urllib.parse import quote

from cairn.adapters.isolation import bounded_process, invoke_worker
from cairn.errors import Blocked, CairnError, Conflict, Denied
from cairn.presentation.models import (
    CatalogItem,
    CatalogPayload,
    EvidencePayload,
    FeedPayload,
    PagePayload,
    PaperPayload,
    ProjectPayload,
    ProposalPayload,
    QueryPayload,
    RenderJob,
    ViewBlock,
    ViewBundle,
    ViewDocument,
    ViewSection,
)
from cairn.presentation.service import RESOURCE, renderer_identity
from cairn.records.models import EvidenceRef, canonical, digest
from cairn.storage.workspace import Workspace


def document(bundle: ViewBundle, *, feedback: bool = False) -> ViewDocument:
    by_ref = {canonical(e.reference): e.key for e in bundle.evidence}

    def citations(refs: list[EvidenceRef]) -> list[str]:
        return list(
            dict.fromkeys(by_ref[canonical(ref)] for ref in refs if canonical(ref) in by_ref)
        )

    sections: list[ViewSection] = []

    def section(title: str, blocks: list[ViewBlock]) -> None:
        if blocks:
            sections.append(ViewSection(title=title, blocks=blocks))

    payload = bundle.payload
    if isinstance(payload, PagePayload):
        from cairn.proposals.service import all_refs

        section(
            "Contents",
            [
                ViewBlock(
                    kind="markdown",
                    text="\n".join(
                        f"- [{entry.record.title.replace('[', '').replace(']', '')}]"
                        f"(#{entry.record.id})"
                        for entry in payload.pages
                    ),
                )
            ],
        )
        for entry in payload.pages:
            section(
                entry.record.title,
                [
                    ViewBlock(
                        title=entry.record.id,
                        text=entry.markdown,
                        kind="markdown",
                        anchor=entry.record.id,
                        citations=citations(all_refs(entry.record)),
                    )
                ],
            )
        if payload.topics:
            section(
                "Connected topics",
                [
                    ViewBlock(
                        kind="markdown",
                        text="\n".join(
                            f"- [{title.replace('[', '').replace(']', '')}](#{key})"
                            for key, title in payload.topics.items()
                        ),
                    )
                ],
            )
            section(
                "Topic references",
                [
                    ViewBlock(title=title, text=key, anchor=key)
                    for key, title in payload.topics.items()
                ],
            )
    elif isinstance(payload, ProjectPayload):
        pack = payload.context
        section(
            "Project state",
            [
                ViewBlock(
                    title=pack.repository.status,
                    text=pack.repository.explanation,
                    labels=["Repository binding", f"Budget estimate: {pack.estimated_tokens}"],
                )
            ],
        )
        for key, items in pack.sections.items():
            section(
                key.replace("_", " ").capitalize(),
                [
                    ViewBlock(
                        title=item.id,
                        text=item.text,
                        citations=citations(item.sources),
                        labels=[
                            "Kind: " + payload.assertion_kinds.get(item.id, "not specified")
                            if item.verification != "owner_adopted"
                            else "Assertion kind: owner_decision",
                            "Adoption: owner adopted"
                            if item.verification == "owner_adopted"
                            else f"Verification: {item.verification}",
                            item.coverage or "",
                            item.version or "",
                        ],
                    )
                    for item in items
                ],
            )
        section(
            "Omitted material",
            [
                ViewBlock(text=f"{k}: {v} complete items omitted")
                for k, v in pack.omitted_sections.items()
            ],
        )
    elif isinstance(payload, QueryPayload):
        section(
            "Evidence search",
            [
                ViewBlock(
                    title=payload.status,
                    text="\n".join(payload.limitations),
                    labels=["Extractive; no model synthesis"],
                )
            ],
        )
        section(
            "Retrieved material",
            [
                ViewBlock(
                    title=h.title,
                    text=h.text,
                    kind="quote" if h.kind == "evidence" else "text",
                    citations=citations(h.sources),
                    labels=[
                        h.kind,
                        h.coverage or "",
                        *(f"Verification: {v}" for v in h.verification),
                        f"Record status: {h.status}",
                        f"Date: {h.source_date or 'unknown'}",
                        f"Version: {h.source_version or 'unknown'}",
                        *(
                            ["Conflicting or superseded material"]
                            if h.disputes or h.supersedes
                            else []
                        ),
                    ],
                )
                for h in payload.hits
            ],
        )
        section(
            "Assertion details",
            [
                ViewBlock(
                    title=a.id,
                    text=a.text,
                    citations=citations(a.sources),
                    labels=[f"Assertion kind: {a.kind}", f"Verification: {a.verification}"],
                )
                for assertions in payload.assertions.values()
                for a in assertions
            ],
        )
    elif isinstance(payload, EvidencePayload):
        section(
            "Source evidence",
            [
                ViewBlock(
                    text="Exact extracted passages are available below.", title=payload.source_id
                )
            ],
        )
    elif isinstance(payload, ProposalPayload):
        r = payload.report
        section(
            "Review status",
            [
                ViewBlock(
                    title=r.validation,
                    text=f"Proposal SHA256: {r.proposal_hash}\n"
                    f"Provider: {r.provider}; route: {r.route}\n"
                    f"Required acknowledgements: {', '.join(r.review_flags)}",
                    labels=[f"Stage: {r.stage}", "Current validity is shown separately"],
                )
            ],
        )
        section(
            "Workflow",
            [
                ViewBlock(
                    kind="diagram",
                    title="Owner-controlled knowledge workflow",
                    nodes=["Proposed", "Validated", "Owner approved", "Applied"],
                    text="This diagram describes the workflow; "
                    "it does not assert this proposal's stage.",
                )
            ],
        )
        for c in r.changes:
            section(
                c.title,
                [
                    ViewBlock(
                        title=c.id,
                        text=f"{c.rationale}\nExpected base: {c.base_hash}\n"
                        f"Current: {c.current_hash}\nProposed: {c.proposed_hash}",
                        labels=c.conflicts,
                    ),
                    ViewBlock(
                        title="Applicability",
                        text=canonical(c.period).decode() if c.period else "Unknown",
                    ),
                    ViewBlock(title="Current-to-proposed diff", text=c.diff, kind="code"),
                    *[
                        ViewBlock(
                            title=a.id,
                            text=a.text,
                            citations=citations(a.sources),
                            labels=[
                                f"Proposed kind: {a.kind}",
                                f"Proposed verification: {a.verification}",
                                "Proposal content; not an approval",
                            ],
                        )
                        for a in c.assertions
                    ],
                ],
            )
    elif isinstance(payload, (CatalogPayload, PaperPayload)):
        rows = payload.papers if isinstance(payload, CatalogPayload) else [payload.paper]
        section("Papers", [_paper(row) for row in rows])
        if isinstance(payload, PaperPayload):
            section(
                "Reading coverage",
                [
                    ViewBlock(
                        text=f"{payload.coverage}; "
                        f"{len(payload.inspected_pages)}/{payload.page_count or 'unknown'} "
                        "pages inspected; "
                        f"visual pages: {payload.visual_pages}"
                    )
                ],
            )
            if payload.summary:
                section(
                    "Generated reading summary",
                    [
                        ViewBlock(
                            text=payload.summary.summary,
                            labels=["Machine analysis; review state shown above"],
                        )
                    ],
                )
                for name in (
                    "research_question",
                    "methods",
                    "findings",
                    "assumptions",
                    "limitations",
                ):
                    section(
                        name.replace("_", " ").capitalize(),
                        [
                            ViewBlock(
                                title=f"Page {c.page}",
                                text=c.text,
                                citations=[
                                    e.key
                                    for e in bundle.evidence
                                    if e.reference.locator == f"page {c.page}"
                                    and e.reference.quote == c.quote
                                ],
                                labels=["Reported by reading model"],
                            )
                            for c in getattr(payload.summary, name)
                        ],
                    )
                section("Reading warnings", [ViewBlock(text=w) for w in payload.summary.warnings])
    elif isinstance(payload, FeedPayload):
        section(
            "Digest snapshot",
            [
                ViewBlock(
                    title=payload.digest.id,
                    text=payload.digest.at.isoformat(),
                    labels=["Saved journal feed"],
                )
            ],
        )
        for e in payload.digest.entries:
            section(
                e.title,
                [
                    ViewBlock(
                        text=f"{e.citation}\n{e.summary or 'Summary pending or unavailable.'}\n"
                        f"Evidence: {e.coverage}\n"
                        f"Verification: {'; '.join(e.verification) or 'Not sampled'}",
                        labels=[
                            e.event.kind,
                            e.availability,
                            f"Personal reading: {e.reading_status}",
                            f"Analysis: {e.analysis_status}",
                            f"Review: {e.review_state}",
                        ],
                        url="https://doi.org/" + quote(e.doi, safe="/") if e.doi else None,
                    )
                ],
            )
        section("Digest issues", [ViewBlock(text=w) for w in payload.digest.issues])
    section("Limitations", [ViewBlock(text=w) for w in bundle.warnings])
    return ViewDocument(
        title=bundle.title,
        bundle_id=bundle.id,
        bundle_hash=digest(canonical(bundle)),
        subtitle=f"{bundle.created_at.isoformat()} · Scope: {bundle.scope} · "
        f"{bundle.classification} · {bundle.processing}",
        sections=sections,
        evidence=bundle.evidence,
        targets=bundle.record_ids,
        feedback=feedback,
        assets=bundle.assets,
    )


def _paper(row: CatalogItem) -> ViewBlock:
    return ViewBlock(
        title=row.title,
        text=f"{'; '.join(row.authors) or 'Authors unknown'}\n"
        f"Year: {row.year or 'unknown'}\n{row.id}",
        labels=[
            row.availability,
            f"Personal reading: {row.reading}",
        ],
        url="https://doi.org/" + quote(row.doi, safe="/") if row.doi else None,
    )


def run_renderer(doc: ViewDocument) -> bytes:
    status, html = bounded_process(
        ["node", str(RESOURCE / "application.mjs")],
        canonical(doc),
        timeout=60,
        stdout_limit=32 * 1024 * 1024,
        env={"PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8"},
    )
    if status:
        raise CairnError("application renderer rejected document")
    validate_html(html, doc)
    return html


def validate_html(html: bytes, doc: ViewDocument) -> None:
    # Output is bound to a pinned executable and then checked again by the owner.
    # Browser/DOM policy tests exercise the complete generated document.
    from html.parser import HTMLParser

    class Check(HTMLParser):
        csp = False

        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            values = dict(attrs)
            if tag in {"iframe", "object", "embed", "base"}:
                raise Denied("renderer returned an embedded document")
            if any(k.startswith("on") or k in {"srcdoc", "action", "formaction"} for k in values):
                raise Denied("renderer returned active attributes")
            if tag == "meta" and values.get("http-equiv") == "Content-Security-Policy":
                content = values.get("content") or ""
                self.csp = "connect-src 'none'" in content and "default-src 'none'" in content
            if values.get("src") and not str(values["src"]).startswith("data:image/"):
                raise Denied("renderer returned a resource dependency")

    check = Check()
    check.feed(html.decode())
    if (
        not check.csp
        or doc.bundle_hash.encode() not in html
        or not html.startswith(b"<!doctype html>")
    ):
        raise Denied("invalid renderer envelope")


def render_bundle(
    ws: Workspace, bundle: ViewBundle, *, feedback: bool = False, inline_synthetic: bool = False
) -> bytes:
    if bundle.renderer != renderer_identity():
        raise Conflict("renderer changed; regenerate the view")
    doc = document(bundle, feedback=feedback)
    if inline_synthetic:
        if not ws.config.synthetic:
            raise Denied("inline rendering is synthetic-only")
        return run_renderer(doc)
    if not ws.config.worker_image:
        raise Blocked("view_renderer_unavailable")
    import base64

    from cairn.records.json import read_json

    result = read_json(invoke_worker(ws.config.worker_image, canonical(RenderJob(document=doc))))
    if (
        set(result) != {"html", "document_hash", "renderer"}
        or result["document_hash"] != digest(canonical(doc))
        or result["renderer"] != bundle.renderer
    ):
        raise Denied("renderer response binding mismatch")
    html = base64.b64decode(result["html"], validate=True)
    validate_html(html, doc)
    return html
