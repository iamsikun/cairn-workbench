import json
import subprocess
from pathlib import Path

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from cairn.adapters.protocol import Candidate, Result
from cairn.cli import app
from cairn.errors import CairnError, Denied
from cairn.ingest.bibliography import import_bibliography
from cairn.ingest.projects import create_project
from cairn.ingest.receipts import adopt_decision, import_receipt
from cairn.ingest.service import capture, extract
from cairn.proposals.models import Proposal
from cairn.proposals.service import approve, load_job, stage_result, validate
from cairn.records.continuity import ReceiptEntry, ReceiptMessage, SessionReceipt
from cairn.records.models import EvidenceRef, Record, canonical, digest
from cairn.retrieval.context import context_pack
from cairn.retrieval.repository import inspect_repository
from cairn.storage.markdown import decode, encode
from cairn.storage.workspace import Workspace
from cairn.transactions.apply import apply


def accept(ws: Workspace, proposal: Proposal) -> None:
    approve(
        ws,
        proposal.id,
        acknowledgements=proposal.review_flags,
        statement="Synthetic owner review of exact bytes and evidence.",
    )
    apply(ws, proposal.id)


@pytest.fixture
def project(ws: Workspace) -> Record:
    proposal = create_project(
        ws,
        title="Synthetic retrieval study",
        question="Can source locators improve repeatability?",
        objective="Measure reproducibility.",
        constraints="Use synthetic records only; no network.",
        scope_name="research",
        inline_synthetic=True,
    )
    accept(ws, proposal)
    return ws.record(proposal.changes[0].id)[1]


def test_bibliography_ids_dates_coverage_and_item_dedup(
    ws: Workspace,
    tmp_path: Path,
    project: Record,
) -> None:
    file = tmp_path / "selected-export.json"
    items = [
        {
            "id": "LIB-ITEM-A",
            "type": "article-journal",
            "title": "Synthetic evidence study",
            "citation-key": "Fiction2024",
            "author": [{"family": "Fiction", "given": "Ada"}],
            "issued": {"date-parts": [[2024]]},
            "abstract": "Synthetic abstract reports 12 trials.",
        },
        {
            "id": "LIB-ITEM-B",
            "type": "report",
            "title": "Metadata only",
            "issued": {"date-parts": [[2023, 2, 7]]},
        },
    ]
    file.write_text(json.dumps(items, indent=2))
    original = file.read_bytes()
    first = import_bibliography(
        ws, file, library_alias="library_synthetic", scope_name="research", project_id=project.id
    )
    _, source, _ = ws.record(first.item_source_ids[0])
    assert source.source and source.source.external_id == "LIB-ITEM-A"
    assert source.source.citation_key == "Fiction2024"
    assert source.source.authors == ["Ada Fiction"]
    assert source.source.source_date is None
    assert source.source.bibliography["issued"] == {"date-parts": [[2024]]}
    evidence, _ = extract(ws, source.id, inline_synthetic=True)
    assert evidence.coverage == "abstract_only"
    assert any(
        s.locator == "CSL field abstract" and "12 trials" in s.text for s in evidence.segments
    )
    other, _ = extract(ws, first.item_source_ids[1], inline_synthetic=True)
    assert other.coverage == "excerpt"
    repeated = import_bibliography(
        ws, file, library_alias="library_synthetic", scope_name="research", project_id=project.id
    )
    assert repeated == first
    items[1]["title"] = "Revised metadata only"
    file.write_text(json.dumps(items))
    revised = import_bibliography(
        ws, file, library_alias="library_synthetic", scope_name="research", project_id=project.id
    )
    assert revised.item_source_ids[0] == first.item_source_ids[0]
    assert revised.item_source_ids[1] != first.item_source_ids[1]
    assert first.item_source_ids[1] in ws.record(revised.item_source_ids[1])[1].source.supersedes
    export = ws.record(first.export_source_id)[1]
    assert ws.fs.read(export.source.blob) == original
    assert (
        import_bibliography(
            ws,
            file,
            library_alias="library_synthetic",
            scope_name="research",
            project_id=project.id,
        )
        == revised
    )


@pytest.mark.parametrize(
    "data",
    [
        b'[{"id":"x","id":"y","type":"report"}]',
        b'[{"id":"x","type":"report"},{"id":"x","type":"book"}]',
        b'[{"id":"x","type":"report","author":[{"family":12}]}]',
    ],
)
def test_bibliography_invalid_export_writes_nothing(
    ws: Workspace, tmp_path: Path, data: bytes
) -> None:
    file = tmp_path / "bad.json"
    file.write_bytes(data)
    before = ws.fs.files("vault/sources")
    with pytest.raises((CairnError, ValidationError)):
        import_bibliography(ws, file, library_alias="library_test", scope_name="research")
    assert ws.fs.files("vault/sources") == before


def session_file(tmp_path: Path, project: Record) -> Path:
    receipt = SessionReceipt(
        session_id="session_alpha",
        project_id=project.id,
        messages=[
            ReceiptMessage(role="user", content="Evaluate a scoped lexical baseline."),
            ReceiptMessage(role="assistant", content="I recommend retaining exact locators."),
        ],
        tried=[ReceiptEntry(text="A title-only lookup returned ambiguous evidence.")],
        failures=[ReceiptEntry(text="Do not repeat title-only lookup: it lost source locators.")],
        proposed_decisions=[
            ReceiptEntry(text="Retain exact source locators in every context pack.")
        ],
        unresolved=[ReceiptEntry(text="How does a two-character Chinese query behave?")],
        next_action=ReceiptEntry(
            text="Compare the scoped lexical baseline on two Chinese queries."
        ),
    )
    file = tmp_path / "session.json"
    file.write_bytes(canonical(receipt))
    return file


def test_session_receipt_requires_explicit_adoption_and_context_preserves_evidence(
    ws: Workspace,
    tmp_path: Path,
    project: Record,
) -> None:
    file = session_file(tmp_path, project)
    proposal = import_receipt(ws, file, scope_name="research", inline_synthetic=True)
    assert proposal and len(proposal.changes) == 2
    assert "owner_adoption" not in proposal.review_flags
    unchanged_project = ws.record(project.id)[1]
    assert not unchanged_project.assertions
    decision = next(
        decode(c.content.encode())[0] for c in proposal.changes if c.id.startswith("decision_")
    )
    assert decision.status == "draft" and decision.assertions[0].kind == "hypothesis"
    accept(ws, proposal)
    before_adoption = context_pack(
        ws, project.id, question="What should I try next?", budget=20000, scope_name="research"
    )
    assert before_adoption.sections["current_decisions"] == []
    assert any("Unadopted" in item.text for item in before_adoption.sections["open_issues"])
    assert import_receipt(ws, file, scope_name="research", inline_synthetic=True) is None
    adoption = adopt_decision(
        ws, decision.id, scope_name="research", statement="Use exact locators for this project."
    )
    assert adoption and "owner_adoption" in adoption.review_flags
    assert (
        context_pack(
            ws, project.id, question="Next?", budget=20000, scope_name="research"
        ).sections["current_decisions"]
        == []
    )
    accept(ws, adoption)
    snapshot = {
        path: ws.fs.read(path)
        for prefix in ("vault", "receipts", "approvals")
        for path in ws.fs.files(prefix)
    }
    pack = context_pack(
        ws,
        project.id,
        question="Plan session beta using the saved evidence.",
        budget=20000,
        scope_name="research",
    )
    assert len(pack.sections["current_decisions"]) == 1
    assert "exact source locators" in pack.sections["current_decisions"][0].text
    assert "Do not repeat title-only" in pack.sections["failed_approaches"][0].text
    assert "Chinese queries" in pack.sections["next_action"][0].text
    assert all(
        item.sources
        for key in ("current_decisions", "failed_approaches", "next_action")
        for item in pack.sections[key]
    )
    assert pack.source_ids and pack.processing == "local_only"
    assert pack.classification == "restricted"  # Unknown free-text question defaults conservative.
    assert pack.estimated_tokens == len(canonical(pack)) <= pack.budget
    assert all(ws.fs.read(path) == data for path, data in snapshot.items())
    # A plain owner edit invalidates adoption proof until reviewed through the writer again.
    path, changed, body = ws.record(decision.id)
    changed.assertions[0].text = "Unreviewed new instruction."
    ws.fs.write(path, encode(changed, body))
    after_edit = context_pack(ws, project.id, question="Next?", budget=20000, scope_name="research")
    assert not after_edit.sections["current_decisions"]
    assert "Unreviewed new instruction" not in canonical(after_edit).decode()
    assert any("adoption receipt" in warning for warning in after_edit.warnings)


def test_receipt_roles_fabricated_reference_and_claimed_authority(
    ws: Workspace,
    tmp_path: Path,
    project: Record,
) -> None:
    file = session_file(tmp_path, project)
    raw = json.loads(file.read_bytes())
    raw["owner_approved"] = True
    file.write_text(json.dumps(raw))
    with pytest.raises(ValidationError):
        import_receipt(ws, file, scope_name="research", inline_synthetic=True)
    del raw["owner_approved"]
    file.write_text(json.dumps(raw))
    proposal = import_receipt(ws, file, scope_name="research", inline_synthetic=True)
    assert proposal
    source = next(r for _, r, _ in ws.records() if r.source and r.source.source_type == "receipt")
    extracted, key = extract(ws, source.id, inline_synthetic=True)
    assert extracted.segments[0].role == "user"
    assert extracted.segments[1].role == "assistant"
    assert extracted.segments[1].text == raw["messages"][1]["content"]
    raw["session_id"] = "session_fake"
    raw["produced_evidence"] = [
        EvidenceRef(
            id=source.id,
            source_hash=source.source.content_hash,
            evidence_hash=key,
            locator="tried 1",
            quote="Fabricated successful result",
        ).model_dump()
    ]
    file.write_text(json.dumps(raw))
    count = len(ws.records())
    with pytest.raises(CairnError, match="quoted text"):
        import_receipt(ws, file, scope_name="research", inline_synthetic=True)
    assert len(ws.records()) == count


def test_context_scope_filters_titles_ids_and_denied_evidence(
    ws: Workspace,
    tmp_path: Path,
    project: Record,
) -> None:
    file = tmp_path / "secret.txt"
    file.write_text("SECRET-FINANCE-CONTENT")
    secret = capture(ws, file, domain="finance", title="SECRET-TITLE")
    extraction, key = extract(ws, secret.id, inline_synthetic=True)
    path, linked, body = ws.record(secret.id)
    linked.project_ids = [project.id]  # Hostile mislabeled relation must not widen scope.
    ws.fs.write(path, encode(linked, body))
    pack = context_pack(ws, project.id, question="Next?", budget=10000, scope_name="research")
    text = canonical(pack).decode()
    assert "SECRET" not in text and secret.id not in text
    # A citation to denied evidence cannot become an unsupported, leaked conclusion.
    path, changed, body = ws.record(project.id)
    changed.sources.append(
        EvidenceRef(
            id=secret.id, source_hash=extraction.source_hash, evidence_hash=key, locator="line 1"
        )
    )
    ws.fs.write(path, encode(changed, body))
    with pytest.raises(Denied, match="evidence unavailable"):
        context_pack(ws, project.id, question="Next?", budget=10000, scope_name="research")


def test_context_budget_omits_whole_items_and_keeps_locators(
    ws: Workspace,
    tmp_path: Path,
    project: Record,
) -> None:
    file = session_file(tmp_path, project)
    receipt = SessionReceipt.model_validate_json(file.read_bytes())
    receipt.unresolved = [
        ReceiptEntry(text=f"Question {i}: " + "Evidence needs inspection. " * 12) for i in range(20)
    ]
    file.write_bytes(canonical(receipt))
    proposal = import_receipt(ws, file, scope_name="research", inline_synthetic=True)
    assert proposal
    accept(ws, proposal)
    pack = context_pack(ws, project.id, question="What next?", budget=7000, scope_name="research")
    assert pack.omitted_sections["open_issues"] > 0
    assert len(canonical(pack)) == pack.estimated_tokens <= 7000
    assert all(item.sources for section in pack.sections.values() for item in section)
    with pytest.raises(CairnError, match="budget too small"):
        context_pack(ws, project.id, question="Q" * 3000, budget=1000, scope_name="research")


def test_repository_binding_flags_changed_or_unverifiable_context(
    ws: Workspace,
    tmp_path: Path,
    project: Record,
) -> None:
    root = tmp_path / "synthetic-project-repo"
    root.mkdir()
    subprocess.run(["git", "init", str(root)], check=True, capture_output=True)
    (root / "analysis.txt").write_text("synthetic baseline")
    subprocess.run(["git", "-C", str(root), "add", "analysis.txt"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "-c",
            "user.name=Synthetic",
            "-c",
            "user.email=synthetic@example.invalid",
            "-c",
            "core.hooksPath=/dev/null",
            "commit",
            "-m",
            "Synthetic baseline",
        ],
        check=True,
        capture_output=True,
    )
    binding = inspect_repository(
        root, alias="repo_synthetic", workspace_root=ws.root, run_ids=["run-a"]
    )
    file = session_file(tmp_path, project)
    receipt = SessionReceipt.model_validate_json(file.read_bytes())
    receipt.repository = binding
    file.write_bytes(canonical(receipt))
    proposal = import_receipt(ws, file, scope_name="research", inline_synthetic=True)
    assert proposal
    accept(ws, proposal)
    options = dict(question="Next?", budget=20000, scope_name="research")
    assert context_pack(ws, project.id, **options).repository.status == "unverified"
    current = context_pack(ws, project.id, repository_root=root, **options)
    assert current.repository.status == "current"
    assert current.repository.recorded.run_ids == ["run-a"]
    (root / "analysis.txt").write_text("changed baseline")
    assert (
        context_pack(ws, project.id, repository_root=root, **options).repository.status == "stale"
    )
    (root / "linked.txt").symlink_to(root / "analysis.txt")
    assert (
        context_pack(ws, project.id, repository_root=root, **options).repository.status
        == "unverified"
    )


def test_review_diff_tamper_is_rejected(ws: Workspace, tmp_path: Path, project: Record) -> None:
    file = session_file(tmp_path, project)
    proposal = import_receipt(ws, file, scope_name="research", inline_synthetic=True)
    assert proposal
    proposal.changes[0].diff = "No changes to review."
    ws.fs.write(f"proposals/{proposal.id}.json", canonical(proposal))
    with pytest.raises(CairnError, match="review diff"):
        validate(ws, proposal.id)


def test_superseded_adopted_decision_is_not_presented_as_current(
    ws: Workspace,
    tmp_path: Path,
    project: Record,
) -> None:
    imported = import_receipt(
        ws, session_file(tmp_path, project), scope_name="research", inline_synthetic=True
    )
    assert imported
    accept(ws, imported)
    decision_id = next(c.id for c in imported.changes if c.id.startswith("decision_"))
    adoption = adopt_decision(
        ws, decision_id, scope_name="research", statement="First owner choice."
    )
    assert adoption
    accept(ws, adoption)
    # A fresh, sealed job is required after the old version has been adopted.
    from cairn.proposals.service import prepare_job

    old = ws.record(decision_id)[1]
    job = prepare_job(ws, old.sources[0].id, scope_name="research", related_ids=[decision_id]).job
    revised = old.model_copy(deep=True)
    revised.id = "decision_successor"
    revised.assertions[0].id = "assert_successor"
    revised.assertions[0].text = "Retain locators plus extraction coverage in every context pack."
    revised.assertions[0].supersedes = [old.id]
    revised.assertions[0].rationale = "Owner expands the explicit provenance requirement."
    proposal = stage_result(
        ws,
        Result(
            job_id=job.id,
            input_hash=digest(canonical(job)),
            provider=job.provider,
            candidates=[Candidate(record=revised, body="", rationale="Owner revision")],
        ),
    )
    assert proposal and "conflicting_evidence" in proposal.review_flags
    accept(ws, proposal)
    pack = context_pack(ws, project.id, question="Next?", budget=20000, scope_name="research")
    assert len(pack.sections["current_decisions"]) == 1
    assert pack.sections["current_decisions"][0].id == revised.id
    assert ws.record(old.id)[1] == old


def test_missing_conflict_reference_is_rejected(
    ws: Workspace, tmp_path: Path, project: Record
) -> None:
    imported = import_receipt(
        ws, session_file(tmp_path, project), scope_name="research", inline_synthetic=True
    )
    assert imported
    job = load_job(ws, imported.job_id).job
    candidate = decode(imported.changes[0].content.encode())[0]
    candidate.assertions[0].disputes = ["assert_missing"]
    candidate.assertions[0].rationale = "Untrusted synthetic conflict claim."
    staged = stage_result(
        ws,
        Result(
            job_id=job.id,
            input_hash=digest(canonical(job)),
            provider=job.provider,
            candidates=[Candidate(record=candidate, body="", rationale="Propose dispute")],
        ),
    )
    assert staged
    with pytest.raises(Denied, match="reference unavailable"):
        validate(ws, staged.id)


def test_cli_research_context_and_save(ws: Workspace, project: Record) -> None:
    runner = CliRunner()
    options = ["--workspace", str(ws.root), "--json"]
    result = runner.invoke(
        app,
        [
            "context",
            project.id,
            "--scope",
            "research",
            "--question",
            "What should I do next?",
            "--budget",
            "10000",
            "--save",
            *options,
        ],
    )
    assert result.exit_code == 0, result.output
    pack = json.loads(result.stdout)
    assert pack["sections"]["objective"]
    assert ws.fs.exists(f"receipts/context/{pack['id']}.json")
    denied = runner.invoke(
        app, ["context", project.id, "--scope", "finance", "--question", "Next?", *options]
    )
    assert denied.exit_code == 3 and "Synthetic retrieval" not in denied.output
