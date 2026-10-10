"""Synthetic regressions for paper-to-notebook work, through the stdio MCP client."""

from test_mcp import Client, grant, reading
from test_presentation import source

from cairn.ingest.service import capture
from cairn.policies.audit import set_scope
from cairn.proposals.service import ingest
from cairn.records.models import Labels, Record, now
from cairn.retrieval.context import context_pack
from cairn.storage.markdown import encode


def accept_synthetic(ws, proposal_id):
    from cairn.proposals.accept import accept, plan

    return accept(ws, plan(ws, [proposal_id]), statement="Synthetic notebook acceptance")


def test_read_integrate_followup_and_fresh_session(ws, tmp_path):
    from cairn.ingest.service import extract
    from cairn.proposals.service import load_proposal
    from cairn.retrieval.search import rebuild_index
    from cairn.storage.backup import durable_contents, validate_payloads
    from cairn.storage.markdown import decode

    grant(ws)
    path = tmp_path / "synthetic-paper.txt"
    path.write_text("Synthetic sequence recommendation result: 42 under condition C.")
    paper = capture(ws, path, domain="research", processing="cloud_eligible")
    extract(ws, paper.id, scope_name="research", inline_synthetic=True)
    client = Client(ws)
    try:
        report = client.ok("evidence", source_id=paper.id)
        answer = reading(report)
        integrated = client.ok(
            "propose_reading",
            **answer,
            related=["@topic"],
            pages=[
                {
                    "key": "topic",
                    "title": "Generative recommendation",
                    "body_markdown": "Sequence generation connects to recommendation systems.",
                    "related": ["@paper", "@broader"],
                },
                {
                    "key": "broader",
                    "title": "Recommendation systems",
                    "body_markdown": "Generative recommendation is one approach.",
                    "related": ["@topic"],
                },
            ],
        )
        proposal = load_proposal(ws, integrated["proposal_id"])
        records = [decode(c.content.encode())[0] for c in proposal.changes]
        assert len(records) == 3
        note = next(r for r in records if r.primary_source_id)
        topic = next(r for r in records if r.title == "Generative recommendation")
        assert topic.id in note.related and note.id in topic.related
        assert not ws.fs.exists(f"vault/wiki/research/{note.id}.md")
        accept_synthetic(ws, proposal.id)
        existing = client.ok("page", record_id=note.id)
        assert any(v["id"] == topic.id for v in existing["backlinks"])
        assert client.ok("evidence", source_id=paper.id)["paper_notes"][0]["id"] == note.id
        changed = {**answer, "summary": "Earlier result retained. Follow-up: condition C matters."}
        failed, error = client.call("propose_reading", **changed)
        assert failed and error["error"] == "conflict"
        followup = client.ok(
            "propose_reading", **changed, target=note.id, base_hash=existing["base_hash"]
        )
        accept_synthetic(ws, followup["proposal_id"])
        path.write_text(
            "Synthetic second paper: another sequence model reports 42 under condition C."
        )
        second = capture(ws, path, domain="research", processing="cloud_eligible")
        extract(ws, second.id, scope_name="research", inline_synthetic=True)
        second_report = client.ok("evidence", source_id=second.id)
        topic_page = client.ok("page", record_id=topic.id)
        second_reading = client.ok(
            "propose_reading",
            **reading(second_report),
            related=[topic.id],
            pages=[
                {
                    "key": "topic",
                    "target": topic.id,
                    "base_hash": topic_page["base_hash"],
                    "body_markdown": "Two papers connect sequence generation to recommendations.",
                    "related": [*topic.related, "@paper"],
                }
            ],
        )
        accept_synthetic(ws, second_reading["proposal_id"])
        assert len([r for _, r, _ in ws.records() if r.primary_source_id]) == 2
        validate_payloads(durable_contents(ws))
    finally:
        client.close()
    rebuild_index(ws, "research")
    fresh = Client(ws)
    try:
        assert "Two papers" in fresh.ok("page", record_id=topic.id)["body"]
        assert any(h["id"] == topic.id for h in fresh.ok("search", query="recommendations")["hits"])
        assert len(fresh.ok("evidence", source_id=paper.id)["paper_notes"]) == 1
    finally:
        fresh.close()


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


def test_note_versions_ambiguity_and_stale_companion(ws):
    from cairn.proposals.service import load_proposal
    from cairn.records.models import digest
    from cairn.storage.markdown import decode

    grant(ws)
    first = source(ws, processing="cloud_eligible")
    client = Client(ws)
    try:
        proposal_id = client.ok(
            "propose_reading", **reading(client.ok("evidence", source_id=first.id))
        )["proposal_id"]
        accept_synthetic(ws, proposal_id)
        note = decode(load_proposal(ws, proposal_id).changes[0].content.encode())[0]
        revised = source(
            ws, text="Revision: 42 under condition C; extra evidence.", processing="cloud_eligible"
        )
        report = client.ok("evidence", source_id=revised.id)
        assert report["paper_notes"][0]["id"] == note.id
        page = client.ok("page", record_id=note.id)
        answer = reading(report)
        result = client.ok("propose_reading", **answer, target=note.id, base_hash=page["base_hash"])
        accept_synthetic(ws, result["proposal_id"])
        assert len([r for _, r, _ in ws.records() if r.primary_source_id]) == 1
        assert ws.record(note.id)[1].primary_source_id == revised.id
        # Historical duplicates never get merged by guessing.
        duplicate = note.model_copy(update={"id": "concept_historical"})
        ws.fs.write(
            "vault/wiki/research/concept_historical.md", encode(duplicate, "Keep this history.")
        )
        answer["summary"] = "Follow-up across versions."
        assert client.call("propose_reading", **answer)[0]
        page = client.ok("page", record_id=note.id)
        failed, _ = client.call(
            "propose_reading",
            **answer,
            target=note.id,
            base_hash=page["base_hash"],
            pages=[
                {
                    "key": "old",
                    "target": duplicate.id,
                    "base_hash": digest(b"wrong"),
                    "body_markdown": "Do not apply.",
                }
            ],
        )
        assert failed and ws.record(duplicate.id)[2] == "Keep this history."
    finally:
        client.close()


def test_pending_revocation_and_current_scope(ws):
    from cairn.policies.audit import revoke_grant
    from cairn.proposals.service import load_job, load_proposal

    grant(ws)
    paper = source(ws, processing="cloud_eligible")
    client = Client(ws)
    try:
        result = client.ok("propose_reading", **reading(client.ok("evidence", source_id=paper.id)))
        assert len(client.ok("pending")["proposals"]) == 1
        revoke_grant(ws, "grant_agent", base_hash=ws.policy_hash, statement="Synthetic revocation")
        assert client.call("pending")[0]
        assert client.call("search", query="!!!")[0]
        grant(ws)
        job = load_job(ws, load_proposal(ws, result["proposal_id"]).job_id).job
        narrowed = ws.policy.scope("research").model_copy(update={"record_ids": {job.source.id}})
        set_scope(ws, narrowed, base_hash=ws.policy_hash, statement="Synthetic narrowed scope")
        grant(ws)
        assert client.ok("pending") == {"proposals": []}
    finally:
        client.close()


def test_project_capture_and_reading_membership(ws, tmp_path):
    from cairn.proposals.service import load_job, load_proposal
    from cairn.records.models import canonical
    from cairn.storage.markdown import decode

    project, _ = project_and_note(ws)
    scope = ws.policy.scope("research").model_copy(update={"project_ids": {project.id}})
    set_scope(ws, scope, base_hash=ws.policy_hash, statement="Synthetic project")
    grant(ws)
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    paper = incoming / "paper.txt"
    paper.write_text("Synthetic result: 42 under condition C.")
    labels = tmp_path / "labels.json"
    labels.write_bytes(canonical(Labels(domain="research", processing="cloud_eligible")))
    client = Client(ws, "--capture-root", str(incoming), "--capture-labels", str(labels))
    try:
        report = client.ok(
            "capture", path=str(paper), identity="synthetic-project-paper", version="v1"
        )
        assert report["source"]["project_ids"] == [project.id]
        result = client.ok("propose_reading", **reading(report))
        proposal = load_proposal(ws, result["proposal_id"])
        note = decode(proposal.changes[0].content.encode())[0]
        assert note.project_ids == [project.id]
        assert load_job(ws, proposal.job_id).job.source.project_ids == [project.id]
        accept_synthetic(ws, proposal.id)
        page = client.ok("page", record_id=note.id)
        answer = {**reading(report), "summary": "Follow-up in this project."}
        followup = client.ok(
            "propose_reading", **answer, target=note.id, base_hash=page["base_hash"]
        )
        assert decode(load_proposal(ws, followup["proposal_id"]).changes[0].content.encode())[
            0
        ].project_ids == [project.id]
    finally:
        client.close()
