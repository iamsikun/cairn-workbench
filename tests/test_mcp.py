"""The stdio MCP server, driven as an agent host would: one JSON-RPC line at a time."""

import json
import subprocess
import sys
from datetime import timedelta

import pytest
from test_presentation import source
from test_quill_write import concept
from typer.testing import CliRunner

from cairn.cli import app
from cairn.mcp import TOOLS
from cairn.policies.audit import set_grant
from cairn.policies.models import RouteGrant
from cairn.presentation.service import assemble, remember
from cairn.records.models import Labels, canonical, now
from cairn.storage.backup import durable_contents, validate_payloads
from cairn.storage.workspace import Workspace

ROUTE = {"provider": "synthetic-agent", "destination": "https://synthetic.invalid"}
AGENT_TOOLS = {
    "search",
    "evidence",
    "page",
    "context",
    "view",
    "feedback",
    "capture",
    "pending",
    "proposal_show",
    "propose_reading",
    "propose_page",
    "propose_changes",
    "propose_explanation",
}


def grant(ws: Workspace, operations=("generation", "client_export", "query", "context")) -> None:
    set_grant(
        ws,
        RouteGrant(
            id="grant_agent",
            scope="research",
            operations=set(operations),
            valid_until=now() + timedelta(days=1),
            owner_consent="Synthetic agent consent",
            **ROUTE,
        ),
        base_hash=ws.policy_hash,
        statement="Synthetic agent consent",
    )


class Client:
    def __init__(self, ws: Workspace, *extra: str):
        self.process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "cairn",
                "legacy",
                "mcp",
                "--workspace",
                str(ws.root),
                "--scope",
                "research",
                "--provider",
                ROUTE["provider"],
                "--destination",
                ROUTE["destination"],
                "--inline-synthetic",
                *extra,
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.next_id = 0

    def send(self, message: object) -> None:
        assert self.process.stdin
        self.process.stdin.write(message if isinstance(message, bytes) else canonical(message))
        self.process.stdin.write(b"\n")
        self.process.stdin.flush()

    def receive(self) -> dict:
        assert self.process.stdout
        line = self.process.stdout.readline()
        assert line, self.process.stderr.read() if self.process.stderr else ""
        return json.loads(line)

    def request(self, method: str, params: dict | None = None) -> dict:
        self.next_id += 1
        self.send({"jsonrpc": "2.0", "id": self.next_id, "method": method, "params": params or {}})
        response = self.receive()
        assert response["id"] == self.next_id
        return response

    def call(self, name: str, **arguments) -> tuple[bool, dict]:
        result = self.request("tools/call", {"name": name, "arguments": arguments})["result"]
        payload = json.loads(result["content"][0]["text"])
        if not result.get("isError"):
            assert result["structuredContent"] == payload
        return bool(result.get("isError")), payload

    def ok(self, name: str, **arguments) -> dict:
        failed, payload = self.call(name, **arguments)
        assert not failed, payload
        return payload

    def close(self) -> None:
        assert self.process.stdin
        self.process.stdin.close()
        assert self.process.wait(timeout=30) == 0


@pytest.fixture
def client(ws):
    value = Client(ws)
    yield value
    value.close()


def reference(report: dict, quote: str = "42 under condition C") -> dict:
    """An evidence reference copied from the `evidence` tool, as an agent would."""
    return {
        "id": report["source"]["id"],
        "source_hash": report["source"]["source"]["content_hash"],
        "evidence_hash": report["evidence_hash"],
        "locator": report["segments"][0]["locator"],
        "quote": quote,
    }


def reading(report: dict) -> dict:
    cited = {"text": "42 under condition C", "kind": "reported_result"}
    return {
        "source_id": report["source"]["id"],
        "summary": "The synthetic paper reports 42 under condition C.",
        "claims": [
            cited | {"sources": [reference(report)]},
            {"text": "Changing C may change the result", "kind": "hypothesis"},
        ],
        "messages": [
            {"role": "user", "content": "Explain this synthetic paper."},
            {"role": "assistant", "content": "42 under condition C; unreviewed."},
        ],
        "limitations": ["Synthetic excerpt only"],
    }


def test_protocol_and_tool_surface_exclude_owner_operations(client):
    init = client.request(
        "initialize",
        {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "synthetic", "version": "0"},
        },
    )["result"]
    assert init["protocolVersion"] == "2025-06-18"
    assert init["serverInfo"]["name"] == "cairn" and "cairn approve" in init["instructions"]
    client.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert client.request("ping")["result"] == {}  # The notification produced no reply.
    tools = client.request("tools/list")["result"]["tools"]
    assert {tool["name"] for tool in tools} == AGENT_TOOLS == set(TOOLS)
    names = " ".join(tool["name"] for tool in tools)
    for owner in ("approve", "accept", "apply", "policy", "backup", "restore", "update", "grant"):
        assert owner not in names
    assert all(tool["inputSchema"]["type"] == "object" for tool in tools)
    reading_tool = next(t for t in tools if t["name"] == "propose_reading")
    assert "FinchClaim" in reading_tool["inputSchema"]["$defs"]
    assert "exact text" in reading_tool["description"]  # The contract travels with the tool.
    assert client.request("no/such")["error"]["code"] == -32601
    assert client.request("tools/call", {"name": "approve"})["error"]["code"] == -32602
    client.send(b"{not json")
    assert client.receive()["error"]["code"] == -32700
    client.send({"jsonrpc": "1.0", "id": 99, "method": "ping"})
    assert client.receive()["error"]["code"] == -32600
    failed, error = client.call("search", query="x", limit=1000)
    assert failed and error["error"] == "invalid" and "limit" in error["message"]


def test_read_then_propose_reading_page_changes_and_explanation(ws, client):
    grant(ws)
    paper = source(ws, processing="cloud_eligible")
    report = client.ok("evidence", source_id=paper.id)
    assert report["segments"] and len(ws.fs.files("receipts/agent")) == 1

    read = client.ok("propose_reading", **reading(report))
    assert read["workflow_stage"] == "validated"
    assert client.ok("propose_reading", **reading(report)) == read  # Retry is idempotent.

    concept(ws)
    page = client.ok("page", record_id="concept_owner_page")
    cite = {"source_id": paper.id, "locator": report["segments"][0]["locator"]}
    claims = [{"text": "42 under condition C", "kind": "reported_result", "sources": [cite]}]
    revision = {
        "instructions": "Cite the synthetic result.",
        "target": "concept_owner_page",
        "body_markdown": "Owner draft, now citing 42 under condition C.\n",
        "claims": claims,
    }
    failed, error = client.call("propose_page", **revision, base_hash="0" * 64)
    assert failed and error["error"] == "conflict"
    written = client.ok("propose_page", **revision, base_hash=page["base_hash"])
    created = client.ok(
        "propose_page",
        instructions="Write a short concept page.",
        new_type="concept",
        title="Result C",
        body_markdown="The synthetic study reports 42 under condition C.\n",
        claims=claims,
    )

    candidate = {
        "record": {
            "id": "concept_mcp_draft",
            "type": "concept",
            "title": "Draft from the synthetic paper",
            "domain": "research",
            "classification": "public",
            "processing": "cloud_eligible",
            "created_at": paper.created_at.isoformat(),
            "updated_at": paper.updated_at.isoformat(),
            "sources": [reference(report)],
            "assertions": [
                {
                    "id": "assertion_mcp_draft",
                    "text": "Reports 42 under condition C.",
                    "kind": "reported_result",
                    "sources": [reference(report)],
                }
            ],
        },
        "body": "The source reports 42 under condition C.\n",
        "rationale": "Integrate the reported result.",
    }
    drafted = client.ok("propose_changes", source_id=paper.id, candidates=[candidate])
    assert drafted["workflow_stage"] == "validated"
    candidate["record"]["assertions"][0]["verification"] = "reviewed"
    failed, error = client.call("propose_changes", source_id=paper.id, candidates=[candidate])
    assert failed and error["error"] == "denied"

    bundle = assemble(ws, "evidence", scope="research", object_id=paper.id)
    remember(ws, bundle, save=True)
    shown = client.ok("view", view_id=bundle.id)
    key = shown["evidence"][0]["key"]
    block = {"text": "The value is 42.", "kind": "reported_result", "evidence_keys": [key]}
    explained = client.ok("propose_explanation", view_id=bundle.id, blocks=[block])
    assert explained["next"].startswith("owner renders it: cairn view explanation")

    queue = client.ok("pending")
    assert {item["proposal_id"] for item in queue["proposals"]} == {
        read["proposal_id"],
        written["proposal_id"],
        created["proposal_id"],
        drafted["proposal_id"],
    }
    assert client.ok("proposal_show", proposal_id=read["proposal_id"])["id"] == read["proposal_id"]
    assert client.ok("search", query="synthetic result")["hits"]
    # Nothing was approved or applied; the owner's steps remain.
    assert not ws.fs.files("approvals")
    validate_payloads(durable_contents(Workspace(ws.root)))


def test_feedback_revision_through_tools(ws, tmp_path, client):
    from cairn.presentation.writing import import_feedback
    from cairn.presentation.writing_models import Feedback, FeedbackEntry
    from cairn.records.models import digest

    grant(ws)
    concept(ws)
    bundle = assemble(
        ws,
        "query",
        scope="research",
        question="Owner",
        question_labels=Labels(
            domain="research", classification="public", processing="cloud_eligible"
        ),
    )
    remember(ws, bundle)
    file = tmp_path / "feedback.json"
    file.write_bytes(
        canonical(
            Feedback(
                bundle_id=bundle.id,
                bundle_hash=digest(canonical(bundle)),
                entries=[FeedbackEntry(target_id="concept_owner_page", comment="Add context.")],
            )
        )
    )
    imported = import_feedback(ws, file, inline_synthetic=True)
    shown = client.ok("feedback", feedback_id=imported.id)
    assert shown["feedback"]["entries"][0]["comment"] == "Add context."
    page = client.ok("page", record_id="concept_owner_page")
    revised = client.ok(
        "propose_page",
        instructions="Address the feedback.",
        feedback_id=imported.id,
        base_hash=page["base_hash"],
        body_markdown="Owner draft with context.\n",
    )
    assert revised["proposal_id"]


def test_grants_bound_every_tool(ws, client):
    paper = source(ws, processing="cloud_eligible")
    private = source(ws, text="Local-only synthetic 42.", processing="local_only")
    failed, error = client.call("evidence", source_id=paper.id)
    assert failed and error["error"] == "denied"
    assert not ws.fs.files("receipts/agent")
    grant(ws, operations=("query",))
    report = client.ok("evidence", source_id=paper.id)
    failed, error = client.call("propose_reading", **reading(report))
    assert failed and error["error"] == "denied"
    assert not ws.fs.files("receipts/finch/exports")
    hits = client.ok("search", query="synthetic")
    assert {hit["id"] for hit in hits["hits"]} == {paper.id}
    assert set(hits) == {"hits"}
    failed, error = client.call("evidence", source_id=private.id)
    assert failed and error["error"] == "denied"


def test_untrusted_answers_are_rejected_without_side_effects(ws, client):
    grant(ws)
    paper = source(ws, processing="cloud_eligible")
    report = client.ok("evidence", source_id=paper.id)
    failed, error = client.call("propose_reading", **reading(report), approved=True)
    assert failed and error["error"] == "invalid"
    forged = reading(report)
    forged["claims"][0]["sources"][0]["quote"] = "Fabricated 99"
    failed, error = client.call("propose_reading", **forged)
    assert failed
    assert not ws.fs.files("receipts/finch/imports") and not ws.fs.files("proposals")


def test_file_capture_needs_owner_root_and_labels(ws, tmp_path):
    grant(ws)
    papers = tmp_path / "papers"
    papers.mkdir()
    inside = papers / "paper.txt"
    inside.write_text("Synthetic captured result: 42 under condition C.")
    outside = tmp_path / "elsewhere.txt"
    outside.write_text("Synthetic outside file.")
    unconfigured = Client(ws)
    failed, error = unconfigured.call("capture", path=str(inside))
    assert failed and "capture" in error["message"]
    unconfigured.close()
    labels = tmp_path / "labels.json"
    labels.write_text(json.dumps({"domain": "research", "processing": "cloud_eligible"}))
    client = Client(ws, "--capture-root", str(papers), "--capture-labels", str(labels))
    failed, error = client.call("capture", path=str(outside))
    assert failed and "capture root" in error["message"]
    captured = client.ok("capture", path=str(inside))
    assert captured["source"]["id"].startswith("source_") and captured["segments"]
    assert client.ok("propose_reading", **reading(captured))["workflow_stage"] == "validated"
    client.close()


def test_launch_validation_and_print_config(ws, tmp_path):
    runner = CliRunner()
    base = ["mcp", "--workspace", str(ws.root), "--provider", "synthetic-agent"]
    base += ["--destination", "https://synthetic.invalid"]
    assert runner.invoke(app, [*base, "--scope", "nowhere"]).exit_code == 3
    labels = tmp_path / "labels.json"
    labels.write_text(json.dumps({"domain": "research"}))
    inside = runner.invoke(
        app, [*base, "--capture-root", str(ws.root), "--capture-labels", str(labels)]
    )
    assert inside.exit_code == 3 and "outside the knowledge base" in inside.output
    printed = runner.invoke(app, [*base, "--print-config"])
    assert printed.exit_code == 0, printed.output
    config = json.loads(printed.stdout)
    assert config["claude_code"].startswith("claude mcp add cairn -- ")
    assert config["codex"].startswith("codex mcp add cairn -- ")
    assert config["cursor_mcp_json"]["mcpServers"]["cairn"]["args"][0] == "mcp"
    settings = config["claude_code_settings"]
    assert settings["sandbox"]["enabled"]
    assert str(ws.root.absolute()) in settings["sandbox"]["filesystem"]["denyWrite"]
    assert f"Edit(/{ws.root.absolute()}/**)" in settings["permissions"]["deny"]
    assert "Bash(cairn approve *)" in settings["permissions"]["deny"]
    assert "writable_roots" in config["codex_sandbox"]
