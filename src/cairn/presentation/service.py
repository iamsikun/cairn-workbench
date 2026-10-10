"""Owner assembly, version checking, private caching and atomic view delivery."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cairn.errors import Blocked, CairnError, Conflict, Denied
from cairn.ingest.service import load_extraction
from cairn.library.feed import history
from cairn.library.index import papers
from cairn.policies.models import LEVEL
from cairn.presentation.models import (
    CatalogItem,
    CatalogPayload,
    EvidenceItem,
    EvidencePayload,
    FeedPayload,
    PageEntry,
    PagePayload,
    PaperPayload,
    Payload,
    ProjectPayload,
    ProposalPayload,
    QueryPayload,
    ViewBundle,
)
from cairn.proposals.service import all_refs, check_reference, load_job, load_proposal
from cairn.records.models import EvidenceRef, Labels, Record, canonical, digest, now
from cairn.retrieval.context import context_pack
from cairn.retrieval.search import query
from cairn.storage.files import RootFS, disjoint
from cairn.storage.workspace import Workspace

RESOURCE = Path(__file__).parent / "resources"


def renderer_identity() -> str:
    return "application-v1:" + digest((RESOURCE / "application.mjs").read_bytes())


def identity(bundle: ViewBundle) -> str:
    value = bundle.model_dump(mode="json")
    value["id"] = "view_pending"
    return "view_" + digest(canonical(value))[:32]


def _catalog_item(row: dict[str, Any]) -> CatalogItem:
    meta = row["metadata"]
    return CatalogItem(
        id=row["id"],
        title=row["title"],
        authors=meta["authors"],
        year=meta["year"],
        doi=meta["doi"],
        reading=meta["reading"],
        availability="PDF available"
        if any(f["availability"] == "available" or f["source_id"] for f in meta["files"])
        else "Metadata only",
    )


def _stamp(ws: Workspace, scope: str) -> str:
    # An owner-side consistency check only: unrelated IDs/paths never enter the packet.
    return digest(
        canonical(
            {
                "policy": ws.policy_hash,
                "records": {
                    p: digest(ws.fs.read(p)) for p, _, _ in ws.records(ws.policy.scope(scope))
                },
            }
        )
    )


def assemble(
    ws: Workspace,
    kind: str,
    *,
    scope: str,
    object_id: str | None = None,
    question: str = "",
    budget: int = 8000,
    repository_root: Path | None = None,
    question_labels: Labels | None = None,
    cloud_route: tuple[str, str] | None = None,
) -> ViewBundle:
    with ws.lock():
        if kind == "proposal":
            if not object_id:
                raise CairnError("proposal ID required")
            scope = load_job(ws, load_proposal(ws, object_id).job_id).job.scope_name
        before = _stamp(ws, scope)
    refs: list[EvidenceRef] = []
    selected: set[str] = set()
    auxiliary: dict[str, str] = {}
    warnings: list[str] = []
    payload: Payload
    review_hash = None
    title = "Cairn " + kind
    if kind == "page":
        with ws.lock():
            effective = ws.policy.scope(scope)
            if cloud_route:
                from cairn.retrieval.search import authorized_scope

                effective = authorized_scope(ws, scope, *cloud_route)
            _, root, body = ws.record(object_id or "", effective)
            if root.type == "source":
                raise Denied("page views require a canonical note or notebook")
            entries = [PageEntry(record=root, markdown=body)]
            topics = {}
            visible = {r.id: (r, body) for _, r, body in ws.records(effective)}
            for entry in entries:
                entry.record = entry.record.model_copy(
                    update={
                        "related": [k for k in entry.record.related if k in visible],
                        "project_ids": [k for k in entry.record.project_ids if k in visible],
                    }
                )
            for key in root.related:
                if key not in visible:
                    continue
                linked, body = visible[key]
                if linked.primary_source_id:
                    if linked.primary_source_id not in visible:
                        continue
                    linked = linked.model_copy(
                        update={
                            "related": [k for k in linked.related if k in visible],
                            "project_ids": [k for k in linked.project_ids if k in visible],
                        }
                    )
                    entries.append(PageEntry(record=linked, markdown=body))
                else:
                    topics[key] = linked.title
                selected.add(key)
            selected.update(e.record.id for e in entries)
            selected.update(
                e.record.primary_source_id for e in entries if e.record.primary_source_id
            )
            payload = PagePayload(pages=entries, topics=topics)
            title = root.title
    elif kind == "project":
        pack = context_pack(
            ws,
            object_id or "",
            question=question,
            budget=budget,
            scope_name=scope,
            repository_root=repository_root,
            question_labels=question_labels,
        )
        payload = ProjectPayload(context=pack)
        selected.update(pack.input_hashes)
        refs.extend(
            ref for items in pack.sections.values() for item in items for ref in item.sources
        )
        warnings.extend(pack.warnings)
        title = "Project brief"
    elif kind == "query":
        result = query(ws, question, scope_name=scope)
        payload = QueryPayload(
            status=result["status"], hits=result["hits"], limitations=result["limitations"]
        )
        for hit in payload.hits:
            selected.add(hit.id.split(":", 1)[0])
            refs.extend(hit.sources)
        title = question
    elif kind == "evidence":
        with ws.lock():
            _, record, _ = ws.record(object_id or "", ws.policy.scope(scope))
            extraction, key = load_extraction(ws, record)
            selected.add(record.id)
            refs.extend(
                EvidenceRef(
                    id=record.id,
                    source_hash=extraction.source_hash,
                    evidence_hash=key,
                    locator=s.locator,
                )
                for s in extraction.segments
                if not question or s.locator == question
            )
            if not refs:
                raise CairnError("evidence locator unavailable")
            payload = EvidencePayload(source_id=record.id)
            title = record.title
    elif kind in ("catalog", "paper"):
        rows = papers(ws, scope=scope)
        if kind == "catalog":
            payload = CatalogPayload(papers=[_catalog_item(row) for row in rows])
            selected.update(row["id"] for row in rows)
            title = "Research library"
        else:
            row = next((row for row in rows if row["id"] == object_id), None)
            if row is None:
                raise Denied("paper unavailable in this scope")
            payload = PaperPayload(paper=_catalog_item(row))
            selected.add(row["id"])
            title = row["title"]
    elif kind == "feed":
        values = history(ws, scope)
        value = (
            next((v for v in values if v.id == object_id), None)
            if object_id
            else (values[0] if values else None)
        )
        if value is None:
            raise Blocked("no_saved_digest")
        payload = FeedPayload(digest=value)
        selected.update(e.event.paper_id for e in value.entries)
        selected.update(j for e in value.entries for j in e.journal_ids)
        with ws.lock():
            path = f"receipts/library/feeds/{value.id}.json"
            auxiliary[path] = digest(ws.fs.read(path))
        title = "Journal updates"
    elif kind == "proposal":
        from cairn.proposals.review import review_model, review_snapshot

        with ws.lock():
            proposal = load_proposal(ws, object_id or "")
            report = review_model(ws, proposal)
            review_hash = review_snapshot(ws, proposal)
            payload = ProposalPayload(report=report)
            job = load_job(ws, proposal.job_id).job
            selected.update([job.source.id, *(p.record.id for p in job.related)])
            selected.update(c.id for c in report.changes if c.current_hash)
            refs.extend(report.references)
            for path in (f"proposals/{proposal.id}.json", f"proposals/jobs/{job.id}.json"):
                auxiliary[path] = digest(ws.fs.read(path))
            title = f"Proposal review: {proposal.id}"
    else:
        raise CairnError("unsupported view kind")
    with ws.lock():
        if before != _stamp(ws, scope):
            raise Conflict("inputs changed while assembling view; retry")
        records: dict[str, Record] = {}
        inputs = dict(auxiliary)
        effective = ws.policy.scope(scope)
        for key in sorted(selected):
            path, record, _ = ws.record(key, effective)
            records[key] = record
            inputs[path] = digest(ws.fs.read(path))
            if not isinstance(payload, PagePayload) or any(
                entry.record.id == key for entry in payload.pages
            ):
                refs.extend(all_refs(record))
        if isinstance(payload, QueryPayload):
            payload.assertions = {r.id: r.assertions for r in records.values() if r.assertions}
        if isinstance(payload, ProjectPayload):
            visible_items = {
                item.id for items in payload.context.sections.values() for item in items
            }
            payload.assertion_kinds = {
                a.id: a.kind
                for r in records.values()
                for a in r.assertions
                if a.id in visible_items
            }
        evidence = []
        for ref in {canonical(r): r for r in refs}.values():
            path, source, _ = ws.record(ref.id, effective)
            records[source.id] = source
            inputs[path] = digest(ws.fs.read(path))
            extraction, key = load_extraction(ws, source)
            inputs[f"evidence/{key}.json"] = key
            assert source.source
            # Verify original content too, without exposing its absolute location.
            blob = source.source.blob
            if digest(ws.fs.read(blob)) != extraction.source_hash:
                raise Conflict("source blob checksum mismatch")
            inputs[blob] = extraction.source_hash
            support = "Hash and locator checked; quote presence does not establish entailment."
            try:
                check_reference(ws, ref, scope)
            except CairnError:
                if kind != "proposal":
                    raise
                support = "Unsupported citation; inspect the proposal validation result."
            segments = [s.text for s in extraction.segments if s.locator == ref.locator]
            evidence.append(
                EvidenceItem(
                    key="evidence_" + digest(canonical(ref))[:24],
                    reference=ref,
                    title=source.title,
                    text=ref.quote if ref.quote is not None else "\n".join(segments),
                    source_date=str(source.source.source_date)
                    if source.source.source_date
                    else None,
                    version=source.source.version,
                    coverage=extraction.coverage,
                    tables_inspected=extraction.tables_inspected,
                    images_inspected=extraction.images_inspected,
                    support=support,
                )
            )
        labels: list[Labels] = list(records.values())
        if isinstance(payload, ProjectPayload):
            labels.append(payload.context)
        elif question:
            labels.append(
                question_labels
                or Labels(domain=next(iter(sorted(effective.domains))), classification="restricted")
            )
        if not labels:
            labels.append(Labels(domain=next(iter(sorted(effective.domains)))))
        bundle = ViewBundle(
            id="view_pending",
            workspace_id=ws.config.id,
            scope=scope,
            policy_hash=ws.policy_hash,
            created_at=now(),
            question=question,
            title=title,
            input_hashes=inputs,
            review_state_hash=review_hash,
            record_ids=sorted(records),
            evidence=evidence,
            payload=payload,
            warnings=warnings,
            domain=labels[0].domain,
            classification=max((r.classification for r in labels), key=LEVEL.__getitem__),
            processing="local_only"
            if any(r.processing == "local_only" for r in labels)
            else "cloud_eligible",
            compartments=set().union(*(r.compartments | {r.domain} for r in labels)),
            renderer=renderer_identity(),
        )
        ws.policy.authorize_route(
            effective,
            list(records.values()),
            route="local",
            provider="cairn-view-v1",
            operation="context",
        )
        if cloud_route:
            ws.policy.authorize_route(
                effective,
                list(records.values()),
                route="cloud",
                provider=cloud_route[0],
                destination=cloud_route[1],
                operation="client_export",
                question=Labels(domain=sorted(effective.domains)[0], processing="cloud_eligible"),
            )
        bundle.id = identity(bundle)
        return bundle


def recheck(ws: Workspace, bundle: ViewBundle, *, historical: bool = False) -> None:
    if bundle.workspace_id != ws.config.id or identity(bundle) != bundle.id:
        raise Denied("view identity or workspace mismatch")
    scope = ws.policy.scope(bundle.scope)
    for key in bundle.record_ids:
        ws.record(key, scope)
    if bundle.policy_hash != ws.policy_hash:
        raise Conflict("view policy changed; regenerate the view")
    if not historical:
        if bundle.review_state_hash and isinstance(bundle.payload, ProposalPayload):
            from cairn.proposals.review import review_snapshot

            proposal = load_proposal(ws, bundle.payload.report.id)
            if review_snapshot(ws, proposal) != bundle.review_state_hash:
                raise Conflict("view review state changed; regenerate the view")
        if bundle.library_state_hash:
            # Only views from the retired library reader carry reading state.
            raise Conflict("view library status changed; regenerate the view")
        for path, expected in bundle.input_hashes.items():
            if not ws.fs.exists(path) or digest(ws.fs.read(path)) != expected:
                raise Conflict("view inputs changed; regenerate the view")


def remember(ws: Workspace, bundle: ViewBundle, *, save: bool = False) -> None:
    with ws.lock(write=True):
        recheck(ws, bundle)
        path = f"{'receipts' if save else 'cache'}/presentation/views/{bundle.id}.json"
        if not ws.fs.exists(path):
            ws.fs.write(path, canonical(bundle), exclusive=True)


def load_view(ws: Workspace, view_id: str, *, historical: bool = False) -> ViewBundle:
    from pydantic import TypeAdapter

    from cairn.records.models import ID

    TypeAdapter(ID).validate_python(view_id)
    with ws.lock():
        paths = [f"{base}/presentation/views/{view_id}.json" for base in ("receipts", "cache")]
        path = next((p for p in paths if ws.fs.exists(p)), None)
        if path is None:
            raise CairnError("view unavailable; regenerate or explicitly save it")
        bundle = ViewBundle.model_validate_json(ws.fs.read(path))
        recheck(ws, bundle, historical=historical)
        return bundle


def output_bytes(ws: Workspace, output: Path, data: bytes) -> None:
    """Caller holds the lock. External owner-selected destinations only."""
    output = output.absolute()
    if any(p.is_symlink() for p in (output, *output.parents)) or not disjoint(output, ws.root):
        raise Denied("output must be outside canonical workspace storage without symlinks")
    if any(not disjoint(output, Path(p)) for p in ws.config.code_roots):
        raise Denied("output must be outside public code")
    # Descriptor-relative traversal rejects symlinks, including during parent creation.
    RootFS(Path(output.anchor)).write(output.relative_to(output.anchor).as_posix(), data)


def export_view(
    ws: Workspace,
    bundle: ViewBundle,
    output: Path,
    *,
    save: bool = False,
    feedback: bool = False,
    inline_synthetic: bool = False,
) -> dict[str, str]:
    from cairn.presentation.render import render_bundle

    rendered = render_bundle(ws, bundle, feedback=feedback, inline_synthetic=inline_synthetic)
    with ws.lock(write=True):
        recheck(ws, bundle)
        ws.fs.write(f"cache/presentation/{bundle.id}.html", rendered)
        path = f"{'receipts' if save else 'cache'}/presentation/views/{bundle.id}.json"
        if not ws.fs.exists(path):
            ws.fs.write(path, canonical(bundle), exclusive=True)
        output_bytes(ws, output, rendered)
    return {"path": str(output.absolute()), "bundle_id": bundle.id, "sha256": digest(rendered)}
