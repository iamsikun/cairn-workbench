"""Bounded paper-note integration; the host supplies prose, Cairn supplies identity."""

from cairn.adapters.protocol import Candidate
from cairn.errors import Conflict, Denied
from cairn.ingest.service import load_extraction
from cairn.policies.models import Scope
from cairn.presentation.pages import page_record
from cairn.presentation.writing_models import PageDraft
from cairn.proposals.service import check_reference
from cairn.reading.models import FinchPacket, NotebookPlan
from cairn.records.models import Assertion, EvidenceRef, Labels, canonical, digest
from cairn.storage.workspace import Workspace


def family(ws: Workspace, source_id: str, scope: Scope) -> set[str]:
    records = {r.id: r.source.supersedes for _, r, _ in ws.records(scope) if r.source is not None}
    if source_id not in records:
        raise Denied("paper unavailable in this scope")
    selected = {source_id}
    while True:
        expanded = selected | {
            key
            for key, parents in records.items()
            if key in selected or selected.intersection(parents)
        }
        expanded |= {key for item in selected for key in records[item] if key in records}
        if expanded == selected:
            return selected
        selected = expanded


def notes(ws: Workspace, source_id: str, scope: Scope) -> list[dict[str, str]]:
    lineage = family(ws, source_id, scope)
    return [
        {"id": r.id, "title": r.title, "base_hash": digest(ws.fs.read(path))}
        for path, r, _ in ws.records(scope)
        if r.primary_source_id in lineage
    ]


def prepare(
    ws: Workspace,
    source_id: str,
    scope_name: str,
    *,
    target: str | None,
    base_hash: str | None,
    related: list[str] | None,
    pages: list[PageDraft],
) -> tuple[NotebookPlan, list[str]]:
    scope = ws.policy.scope(scope_name)
    _, source, _ = ws.record(source_id, scope)
    found = notes(ws, source_id, scope)
    if target is None and found:
        if len(found) != 1:
            raise Conflict("multiple paper notes; select a target and its base_hash")
        target = found[0]["id"]
    keys = [page.key for page in pages]
    if "paper" in keys or len(keys) != len(set(keys)):
        raise Denied("companion keys must be unique; paper is reserved")
    if len(pages) + 1 > ws.policy.max_changes:
        raise Denied("reading and companion pages exceed the owner's change budget")
    lineage = family(ws, source_id, scope)
    roots = []
    for key in sorted(lineage):
        version = ws.record(key, scope)[1].source
        assert version is not None
        if not set(version.supersedes) & lineage:
            roots.append(key)
    note_id = target or "concept_paper_" + digest(canonical(roots or sorted(lineage)))[:32]
    projects = set(source.project_ids)
    selected = {source_id}
    for key in related or []:
        if not key.startswith("@"):
            selected.add(key)
            item = ws.record(key, scope)[1]
            if item.type == "project":
                projects.add(key)
    if target:
        path, old, _ = ws.record(target, scope)
        if old.type != "concept" or (
            old.primary_source_id and old.primary_source_id not in lineage
        ):
            raise Denied("target is not a note for this paper")
        if digest(ws.fs.read(path)) != base_hash:
            raise Conflict("read the existing paper note and supply its current base_hash")
        projects = set(old.project_ids)
        selected.add(target)
    elif base_hash is not None:
        raise Denied("base_hash requires an existing paper note")
    for page in pages:
        if page.target:
            path, old, _ = ws.record(page.target, scope)
            if old.type == "source" or "cairn_library_v1" in old.sections:
                raise Denied("sources and catalog metadata are immutable")
            if digest(ws.fs.read(path)) != page.base_hash:
                raise Conflict("companion page changed; read it again")
            selected.add(page.target)
        for key in [*(page.related or []), *(page.project_ids or [])]:
            if not key.startswith("@"):
                selected.add(key)
        selected.update(ref.source_id for claim in page.claims for ref in claim.sources)
    return NotebookPlan(
        note_id=note_id,
        target=target,
        base_hash=base_hash,
        related=related,
        project_ids=sorted(projects),
        pages=pages,
    ), sorted(selected)


def candidates(
    ws: Workspace,
    packet: FinchPacket,
    primary: Candidate,
    session: EvidenceRef,
) -> list[Candidate]:
    plan = packet.notebook
    assert plan is not None
    existing = {p.record.id: p.record for p in packet.related}
    identities = {
        "paper": plan.note_id,
        **{
            page.key: page.target
            or f"{page.new_type}_" + digest(canonical([packet.id, page.key]))[:32]
            for page in plan.pages
        },
    }
    if len(set(identities.values())) != len(identities):
        raise Denied("duplicate page target")

    def resolve(values: list[str] | None) -> list[str] | None:
        if values is None:
            return None
        result = []
        for value in values:
            if value.startswith("@"):
                if value[1:] not in identities:
                    raise Denied("unknown companion page key")
                value = identities[value[1:]]
            elif value not in existing and value != packet.source.id:
                raise Denied("link was not included in the sealed reading inputs")
            result.append(value)
        return list(dict.fromkeys(result))

    old = existing.get(plan.target or "")
    primary.record = page_record(
        old=old,
        record_id=plan.note_id,
        record_type="concept",
        title=old.title if old else f"Reading: {packet.source.title}"[:500],
        labels=primary.record,
        at=primary.record.created_at,
        sources=primary.record.sources,
        assertions=primary.record.assertions,
        related=resolve(plan.related),
        project_ids=plan.project_ids,
        primary_source_id=packet.source.id,
    )
    result = [primary]
    for page in plan.pages:
        old = existing.get(page.target or "")
        assertions = []
        refs = []
        for i, claim in enumerate(page.claims):
            cited = []
            for citation in claim.sources:
                source = existing.get(citation.source_id) or (
                    packet.source if citation.source_id == packet.source.id else None
                )
                if source is None:
                    raise Denied("companion citation outside the sealed inputs")
                extraction, key = load_extraction(ws, source)
                ref = EvidenceRef(
                    id=source.id,
                    source_hash=extraction.source_hash,
                    evidence_hash=key,
                    locator=citation.locator,
                    quote=citation.quote,
                )
                check_reference(ws, ref, packet.scope)
                cited.append(ref)
            refs.extend(cited)
            assertions.append(
                Assertion(
                    id="assert_notebook_" + digest(canonical([packet.id, page.key, i]))[:32],
                    text=claim.text,
                    kind=claim.kind,
                    sources=cited,
                    rationale="Agent synthesis; unreviewed",
                )
            )
        domain = old.domain if old else page.domain
        labels = Labels(
            domain=domain,
            classification=primary.record.classification,
            processing=primary.record.processing,
            compartments=(primary.record.compartments | {primary.record.domain}) - {domain},
        )
        record = page_record(
            old=old,
            record_id=identities[page.key],
            record_type=old.type if old else page.new_type,
            title=page.title or (old.title if old else page.key),
            labels=labels,
            at=primary.record.updated_at,
            sources=[*refs, session],
            assertions=assertions,
            related=resolve(page.related),
            project_ids=resolve(page.project_ids)
            if page.project_ids is not None
            else (old.project_ids if old else plan.project_ids),
            aliases=page.aliases,
        )
        body = page.body_markdown.rstrip() + "\n"
        if page.limitations:
            body += "\n## Limitations\n\n" + "\n".join(f"- {v}" for v in page.limitations) + "\n"
        result.append(
            Candidate(record=record, body=body, rationale="Integrate the paper into a notebook")
        )
    return result
