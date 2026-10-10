"""Synthetic regressions for paper-to-notebook work, through the stdio MCP client."""

from test_mcp import Client, grant
from test_presentation import source

from cairn.ingest.service import capture
from cairn.policies.audit import set_scope
from cairn.proposals.service import ingest
from cairn.records.models import Labels, Record, now
from cairn.retrieval.context import context_pack
from cairn.storage.markdown import encode


def project_and_note(ws):
    at = now()
    project = Record(
        id="project_synthetic",
        type="project",
        title="Synthetic research",
        domain="research",
        processing="cloud_eligible",
        created_at=at,
        updated_at=at,
    )
    note = Record(
        id="concept_synthetic",
        type="concept",
        title="Synthetic paper note",
        domain="research",
        processing="cloud_eligible",
        created_at=at,
        updated_at=at,
        project_ids=[project.id],
    )
    for record, body in [
        (project, "PROJECT-BODY: compare sequence models."),
        (note, "CONCEPT-BODY: learned sequential connection."),
    ]:
        ws.fs.write(f"vault/wiki/research/{record.id}.md", encode(record, body))
    return project, note


def test_large_source_one_citation(ws):
    grant(ws)
    paper = source(
        ws, text="\n".join(f"Synthetic line {i}." for i in range(501)), processing="cloud_eligible"
    )
    client = Client(ws)
    try:
        report = client.ok("evidence", source_id=paper.id)
        result = client.ok(
            "propose_page",
            instructions="Save one detail.",
            new_type="concept",
            title="Detail",
            body_markdown="Synthetic line 0.",
            claims=[
                {
                    "text": "Synthetic line 0.",
                    "kind": "reported_result",
                    "sources": [
                        {"source_id": paper.id, "locator": report["segments"][0]["locator"]}
                    ],
                }
            ],
        )
        assert result["proposal_id"]
    finally:
        client.close()


def test_content_identity_and_explicit_revisions(ws, tmp_path):
    first = tmp_path / "a" / "main.txt"
    second = tmp_path / "b" / "main.txt"
    first.parent.mkdir()
    second.parent.mkdir()
    first.write_text("Synthetic first paper.")
    second.write_text("Synthetic other paper.")
    a = capture(ws, first, domain="research")
    b = capture(ws, second, domain="research")
    assert b.source.supersedes == [] and b.id != a.id
    second.write_bytes(first.read_bytes())
    assert capture(ws, second, domain="research").id == a.id
    original = capture(ws, first, domain="research", identity="synthetic-paper", version="v1")
    first.write_text("Synthetic revised paper.")
    revised = capture(ws, first, domain="research", identity="synthetic-paper", version="v2")
    assert original.id in revised.source.supersedes


def test_context_keeps_project_body_and_paper_notes(ws):
    project, note = project_and_note(ws)
    pack = context_pack(
        ws,
        project.id,
        question="What did we learn?",
        budget=8000,
        scope_name="research",
        question_labels=Labels(domain="research"),
    )
    assert "PROJECT-BODY" in pack.sections["objective"][0].text
    assert any("CONCEPT-BODY" in item.text for item in pack.sections["relevant_literature"])
    assert note.id in pack.input_hashes


def test_project_scoped_revision(ws):
    project, note = project_and_note(ws)
    narrow = ws.policy.scope("research").model_copy(update={"project_ids": {project.id}})
    set_scope(ws, narrow, base_hash=ws.policy_hash, statement="Synthetic scoped research.")
    grant(ws)
    client = Client(ws)
    try:
        page = client.ok("page", record_id=note.id)
        result = client.ok(
            "propose_page",
            instructions="Clarify.",
            target=note.id,
            base_hash=page["base_hash"],
            body_markdown="A clarified connection.",
        )
        assert result["proposal_id"]
    finally:
        client.close()


def test_search_filters_before_limit_and_no_hidden_counts(ws):
    grant(ws)
    allowed = source(ws, text="A study mentions Quasar.", processing="cloud_eligible")
    client = Client(ws)
    try:
        before = client.ok("search", query="Quasar", limit=1)
        source(ws, text="Quasar Quasar Quasar.", processing="local_only")
        after = client.ok("search", query="Quasar", limit=1)
        assert after == before
        assert [h["id"] for h in after["hits"]] == [allowed.id]
        assert set(after) == {"hits"}
    finally:
        client.close()


def test_pending_requires_grant_and_hides_local_proposals(ws):
    paper = source(ws)
    ingest(ws, paper.id, scope_name="research", inline_synthetic=True)
    client = Client(ws)
    try:
        failed, _ = client.call("pending")
        assert failed and not ws.fs.files("receipts/agent")
        grant(ws)
        assert client.ok("pending") == {"proposals": []}
        assert len(ws.fs.files("receipts/agent")) == 1
    finally:
        client.close()
