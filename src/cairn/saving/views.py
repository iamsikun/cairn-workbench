"""Requested offline companions; source records and resources remain authoritative."""

import base64
import hashlib
import html
import json
from decimal import Decimal, localcontext
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from cairn.errors import CairnError, Conflict, Denied
from cairn.presentation.models import EvidenceItem, ViewAsset, ViewBlock, ViewDocument, ViewSection
from cairn.presentation.render import run_renderer, validate_html
from cairn.presentation.service import RESOURCE
from cairn.records.models import ID, Digest, Domain, EvidenceRef, Model, canonical, digest, new_id
from cairn.saving.models import NoteChange, Observation, SaveNote, SaveReceipt
from cairn.saving.workspace import Book


class Scenario(Model):
    initial: Decimal = Field(ge=0, le=10**12)
    annual_contribution: Decimal = Field(ge=0, le=10**12)
    annual_rate: Decimal = Field(gt=-1, le=1)
    years: int = Field(ge=0, le=100)
    unit: str = Field(min_length=1, max_length=30)


class FeedbackEntry(Model):
    target_id: ID
    comment: str = Field(min_length=1, max_length=10000)
    suggested_text: str | None = Field(default=None, max_length=20000)


class NotebookFeedback(Model):
    schema_version: Literal[1] = 1
    bundle_id: ID
    bundle_hash: Digest
    entries: list[FeedbackEntry] = Field(min_length=1, max_length=50)


def future_value(s: Scenario) -> Decimal:
    with localcontext() as context:
        context.prec = 80
        value = s.initial
        for _ in range(s.years):
            value = value * (1 + s.annual_rate) + s.annual_contribution
        return value.quantize(Decimal("0.01"))


SCENARIO_SCRIPT = """document.querySelectorAll('[data-cairn-scenario]').forEach(root=>{
const inputs=Array.from(root.querySelectorAll('input'));
const update=()=>{const [initial,payment,rate,years]=inputs.map(e=>Number(e.value));
if(inputs.some(e=>!e.checkValidity())||![initial,payment,rate,years].every(Number.isFinite)){
root.querySelector('output').textContent='Enter values within the displayed limits.';return;}
let amount=initial; for(let y=0;y<years;y++) amount=amount*(1+rate)+payment;
root.querySelector('output').textContent=amount.toFixed(2)+' '+root.dataset.unit;
root.querySelector('[data-years]').textContent=String(years);};
inputs.forEach(input=>input.addEventListener('input',update)); update();
});"""


def _scenario_markup(s: Scenario) -> str:
    fields = [
        ("Initial amount", str(s.initial), "number", "0", str(10**12), "0.01"),
        (
            "Contribution at each year end",
            str(s.annual_contribution),
            "number",
            "0",
            str(10**12),
            "0.01",
        ),
        ("Annual rate (decimal)", str(s.annual_rate), "number", "-0.99", "1", "0.001"),
        ("Years", str(s.years), "range", "0", "100", "1"),
    ]
    controls = "".join(
        f'<label>{html.escape(label)} <input type="{kind}" value="{value}" '
        f'min="{low}" max="{high}" step="{step}"></label>'
        for label, value, kind, low, high, step in fields
    )
    return (
        f'<div data-cairn-scenario="true" data-unit="{html.escape(s.unit, quote=True)}">'
        "<p>Illustrative scenario; annual compounding and "
        "year-end contributions. Controls are temporary and do not save a plan.</p>"
        f"{controls}<p><span data-years>{s.years}</span> years: "
        f'<output aria-live="polite">{future_value(s)} {html.escape(s.unit)}</output></p></div>'
    )


def _render(
    book: Book, collection: Domain, identity: str, *, snapshot: bool = False
) -> dict[str, Any]:
    rows = book.records(collection)
    _, record, _ = book.record(identity, collection)
    visible = {k: row for k, row in rows.items() if not row[1].archived}
    selected = {identity}
    selected.update(
        r.target for r in record.relationships if r.state == "active" and r.target in visible
    )
    selected.update(c.id for c in record.citations if c.id in visible)
    if record.primary_source_id in visible:
        selected.add(record.primary_source_id)
    pending = list(selected)
    while pending:
        note = visible[pending.pop()][1]
        required = {c.id for c in note.citations}
        required.update(c.id for relationship in note.relationships for c in relationship.sources)
        if note.primary_source_id:
            required.add(note.primary_source_id)
        required.update(t for resource in note.resources for t in resource.synthesis_inputs)
        for target in required & visible.keys() - selected:
            selected.add(target)
            pending.append(target)
        if len(selected) > 100:
            raise Denied("view exceeds dependency budget")
    if len(selected) > 100:
        raise Denied("view exceeds related-note budget")
    dependencies = {key: book.revision(visible[key][0]) for key in sorted(selected)}
    renderer_hash = digest(
        Path(__file__).read_bytes() + (RESOURCE / "application.mjs").read_bytes()
    )
    key = new_id("view") if snapshot else identity
    manifest_path = f"views/{collection}/{key}.json"
    old = None
    if book.fs.exists(manifest_path):
        old = json.loads(book.fs.read(manifest_path))
        output = old["html_path"]
        if output != f"views/{collection}/outputs/{old['html_hash']}.html":
            raise Denied("invalid companion path")
        if book.fs.exists(output) and digest(book.fs.read(output)) != old["html_hash"]:
            raise Conflict("HTML was edited outside Cairn; existing output preserved")
        if old["inputs"] == dependencies and old.get("renderer_hash") == renderer_hash:
            return {**old, "path": str(book.root / output), "freshness": "current"}
    for note_id in selected:
        _, note, body = visible[note_id]
        for resource in note.resources:
            stale = (
                resource.synthesis_markdown_hash is not None
                and resource.synthesis_markdown_hash != digest(body.encode())
            )
            stale = stale or any(
                target not in visible or book.revision(visible[target][0]) != revision
                for target, revision in resource.synthesis_inputs.items()
            )
            if stale:
                if old is not None:
                    return {
                        **old,
                        "path": str(book.root / old["html_path"]),
                        "freshness": "needs_synthesis",
                    }
                raise Conflict("visual source requires renewed agent synthesis before rendering")
    sections, assets = [], []
    scenarios: dict[str, str] = {}
    evidence: dict[str, EvidenceItem] = {}
    labels = {i: visible[i][1].title for i in selected}
    feedback_targets = {
        i: {"note": i, "resource": None} for i in selected if visible[i][1].type != "source"
    }
    for note_id in [identity, *sorted(selected - {identity})]:
        _, note, body = visible[note_id]
        from cairn.saving.references import validate_references

        validate_references(note, {k: r for k, (_, r, _) in visible.items()})
        citations = []
        for citation in note.citations:
            source = visible[citation.id][1]
            assert source.source is not None
            if citation.quote is None:
                continue
            evidence_key = "evidence_" + digest(canonical(citation))[:24]
            evidence[evidence_key] = EvidenceItem(
                key=evidence_key,
                title=source.title,
                reference=EvidenceRef(
                    id=source.id,
                    source_hash=source.source.original_hash
                    or source.source.content_hash
                    or dependencies[source.id],
                    evidence_hash=dependencies[source.id],
                    locator=citation.locator or "supplied text",
                    quote=citation.quote,
                ),
                text=citation.quote,
                version=source.source.version,
                coverage=source.source.coverage,
                tables_inspected=False,
                images_inspected=False,
                support="Quote present in retained text; "
                "this does not establish truth or entailment.",
            )
            citations.append(evidence_key)
        blocks = [
            ViewBlock(
                kind="markdown",
                text=body,
                anchor=note.id,
                labels=[note.coverage, "Unreviewed", note.enrichment],
                citations=citations,
            )
        ]
        blocks.extend(
            ViewBlock(title=f"{o.author} observation", text=o.text, anchor=o.id)
            for o in note.observations
        )
        for resource in note.resources:
            anchor = "asset_" + digest(canonical([note.id, resource.key]))[:24]
            feedback_targets[anchor] = {"note": note.id, "resource": resource.key}
            labels[anchor] = note.title + " / " + resource.title
            if resource.kind == "figure":
                value = json.loads(resource.content)
                if (
                    not isinstance(value, dict)
                    or not isinstance(value.get("data"), str)
                    or not isinstance(value.get("mime"), str)
                ):
                    raise Denied("figure needs a MIME type and base64 data")
                raw = base64.b64decode(value["data"], validate=True)
                assets.append(
                    ViewAsset(id=anchor, mime=value["mime"], data=value["data"], sha256=digest(raw))
                )
                blocks.append(
                    ViewBlock(
                        title=resource.title,
                        text=resource.description,
                        asset_id=anchor,
                        anchor=anchor,
                    )
                )
            elif resource.kind == "diagram":
                nodes = json.loads(resource.content)
                if (
                    not isinstance(nodes, list)
                    or len(nodes) > 100
                    or any(not isinstance(n, str) for n in nodes)
                ):
                    raise Denied("diagram must contain a bounded list of labeled steps")
                blocks.append(
                    ViewBlock(
                        title=resource.title,
                        text=resource.description,
                        kind="diagram",
                        nodes=nodes,
                        anchor=anchor,
                    )
                )
            elif resource.kind == "scenario":
                scenario = Scenario.model_validate_json(resource.content)
                scenarios[anchor] = _scenario_markup(scenario)
                blocks.append(
                    ViewBlock(title=resource.title, text=resource.description, anchor=anchor)
                )
            else:
                blocks.append(
                    ViewBlock(
                        title=resource.title,
                        text=resource.description + "\n\n" + resource.content,
                        kind="markdown",
                        anchor=anchor,
                    )
                )
        if note.relationships:
            blocks.append(
                ViewBlock(
                    title="Connections",
                    text="\n".join(
                        f"{r.kind}: {visible[r.target][1].title} — {r.explanation} ({r.basis})"
                        for r in note.relationships
                        if r.state == "active" and r.target in visible
                    ),
                )
            )
        if note.citations:
            blocks.append(
                ViewBlock(
                    title="References",
                    text="\n\n".join(
                        f"{visible[c.id][1].title}; {c.locator or 'locator unavailable'}"
                        + (f"\nQuote: {c.quote}" if c.quote else "")
                        for c in note.citations
                        if c.id in visible
                    ),
                )
            )
        sections.append(ViewSection(title=note.title, blocks=blocks))
    bundle_hash = digest(canonical([dependencies, renderer_hash]))
    doc = ViewDocument(
        title=record.title,
        bundle_id="view_" + digest(key.encode())[:24],
        bundle_hash=bundle_hash,
        subtitle="Learning notebook · " + collection,
        sections=sections,
        evidence=list(evidence.values()),
        targets=sorted(feedback_targets),
        assets=assets,
        feedback=True,
    )
    rendered = run_renderer(doc)
    rendered = rendered.replace(b"Feedback for owner review", b"Notebook feedback")
    rendered = rendered.replace(
        b"This exports a file. It does not approve or apply changes.",
        b"Export comments for import into the notebook's attributed observations.",
    )
    for target in feedback_targets:
        rendered = rendered.replace(
            f"<option>{target}</option>".encode(),
            f'<option value="{target}">{html.escape(labels[target])}</option>'.encode(),
        )
    rendered = rendered.replace(b"<label>Record <select", b"<label>Notebook or figure <select")
    if not evidence:
        rendered = rendered.replace(
            b"<section><h2>Evidence</h2><p>No supporting excerpts in this bundle.</p></section>",
            b"",
        )
    if scenarios:
        text = rendered.decode()
        script_hash = base64.b64encode(hashlib.sha256(SCENARIO_SCRIPT.encode()).digest()).decode()
        text = text.replace("script-src ", f"script-src 'sha256-{script_hash}' ", 1)
        for anchor, controls in scenarios.items():
            start = text.index(f'<article id="{anchor}">')
            end = text.index("</article>", start)
            text = text[:end] + controls + text[end:]
        text = text.replace("</body>", f"<script>{SCENARIO_SCRIPT}</script></body>", 1)
        rendered = text.encode()
        validate_html(rendered, doc)
    output = f"views/{collection}/outputs/{digest(rendered)}.html"
    manifest = {
        "id": key,
        "note_id": identity,
        "collection": collection,
        "inputs": dependencies,
        "html_hash": digest(rendered),
        "snapshot": snapshot,
        "bundle_id": doc.bundle_id,
        "bundle_hash": bundle_hash,
        "html_path": output,
        "feedback_targets": feedback_targets,
        "renderer_hash": renderer_hash,
    }
    book.fs.write(output, rendered)
    book.fs.write(
        f"views/{collection}/manifests/{doc.bundle_id}_{bundle_hash}.json", canonical(manifest)
    )
    book.fs.write(manifest_path, canonical(manifest))
    return {**manifest, "path": str(book.root / output), "freshness": "current"}


def render(
    book: Book, collection: Domain, identity: str, *, snapshot: bool = False
) -> dict[str, Any]:
    with book.lock():
        return _render(book, collection, identity, snapshot=snapshot)


def maintain(book: Book, collection: Domain) -> str:
    """Caller holds the save lock. A failed view leaves its old manifest and bytes intact."""
    state = "not_requested"
    for path in book.fs.files(f"views/{collection}"):
        if not path.endswith(".json") or len(path.split("/")) != 3:
            continue
        manifest = json.loads(book.fs.read(path))
        if manifest["snapshot"]:
            continue
        try:
            result = _render(book, collection, manifest["note_id"])
            if result["freshness"] != "current":
                state = "pending"
            elif state != "pending":
                state = "current"
        except (CairnError, OSError, ValueError):
            state = "pending"
    return state


def feedback(book: Book, collection: Domain, data: dict[str, Any]) -> list[dict[str, Any]]:
    from cairn.saving.retrieval import get_note
    from cairn.saving.service import _result, save
    from cairn.transactions.writer import operation_hash

    parsed = NotebookFeedback.model_validate(data)

    with book.lock():
        manifests = [
            json.loads(book.fs.read(p))
            for p in book.fs.files(f"views/{collection}")
            if p.endswith(".json")
        ]
    original = next(
        (
            m
            for m in manifests
            if m["bundle_id"] == parsed.bundle_id and m["bundle_hash"] == parsed.bundle_hash
        ),
        None,
    )
    if original is None:
        raise Denied("feedback view is unavailable")
    results = []
    for entry in parsed.entries:
        target = original["feedback_targets"].get(entry.target_id)
        if target is None:
            raise Denied("feedback target is outside the view")
        identity = target["note"]
        key = digest(canonical([parsed.bundle_hash, entry]))
        operation = "feedback-" + key
        receipt_path = f"revisions/{collection}/{operation_hash(collection, operation)}.json"
        with book.lock():
            if book.fs.exists(receipt_path):
                results.append(
                    _result(book, SaveReceipt.model_validate_json(book.fs.read(receipt_path)))
                )
                continue
        current = get_note(book, collection, identity)
        text = f"Feedback on {target['resource'] or 'notebook'}: {entry.comment}"
        if entry.suggested_text:
            text += "\nSuggested text: " + entry.suggested_text
        observations = [
            Observation(
                id="observation_" + digest(canonical([key, i]))[:24], text=text[i : i + 20000]
            )
            for i in range(0, len(text), 20000)
        ]
        results.append(
            save(
                book,
                collection,
                SaveNote(
                    operation_key=operation,
                    note=NoteChange(
                        id=identity,
                        expected_revision=current["revision"],
                        type=current["type"],
                        kind=current["kind"],
                        title=current["title"],
                        markdown=current["markdown"],
                        observations=observations,
                    ),
                ),
            )
        )
    return results
