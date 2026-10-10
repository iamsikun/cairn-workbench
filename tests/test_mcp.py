"""The stdio MCP server, driven as an agent host would: one JSON-RPC line at a time."""

import json
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

import pytest
from test_draft_packet import drafted
from test_finch import returned
from test_presentation import source
from typer.testing import CliRunner

from cairn.adapters.protocol import Job
from cairn.cli import app
from cairn.mcp import TOOLS
from cairn.policies.audit import set_grant
from cairn.policies.models import RouteGrant
from cairn.reading.models import FinchPacket
from cairn.records.models import canonical, digest, now
from cairn.storage.backup import durable_contents, validate_payloads
from cairn.storage.workspace import Workspace

ROUTE = {"provider": "synthetic-agent", "destination": "https://synthetic.invalid"}
AGENT_TOOLS = {
    "search",
    "evidence",
    "context",
    "pending",
    "proposal_show",
    "reading_begin",
    "reading_finish",
    "writing_begin",
    "writing_finish",
    "draft_begin",
    "draft_finish",
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
    def __init__(self, ws: Workspace, tmp_path: Path, *extra: str):
        self.packets = tmp_path / "agent-packets"
        self.process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "cairn",
                "mcp",
                "--workspace",
                str(ws.root),
                "--scope",
                "research",
                "--provider",
                ROUTE["provider"],
                "--destination",
                ROUTE["destination"],
                "--packets-dir",
                str(self.packets),
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

    def close(self) -> None:
        assert self.process.stdin
        self.process.stdin.close()
        assert self.process.wait(timeout=30) == 0


@pytest.fixture
def client(ws, tmp_path):
    value = Client(ws, tmp_path)
    yield value
    value.close()


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
    finch_schema = next(t for t in tools if t["name"] == "reading_finish")["inputSchema"]
    assert "FinchResponse" in finch_schema["$defs"]  # References resolve at the schema root.
    assert client.request("no/such")["error"]["code"] == -32601
    assert client.request("tools/call", {"name": "approve"})["error"]["code"] == -32602
    client.send(b"{not json")
    assert client.receive()["error"]["code"] == -32700
    client.send({"jsonrpc": "1.0", "id": 99, "method": "ping"})
    assert client.receive()["error"]["code"] == -32600
    failed, error = client.call("search", query="x", limit=1000)
    assert failed and error["error"] == "invalid" and "limit" in error["message"]


def test_reading_writing_and_drafting_round_trips(ws, tmp_path, client):
    grant(ws)
    paper = source(ws, processing="cloud_eligible")

    failed, began = client.call("reading_begin", source=paper.id)
    assert not failed, began
    assert "source_bytes_base64" not in began["packet"]
    assert Path(began["path"]).is_relative_to(client.packets)
    assert "source_bytes_base64" in json.loads(Path(began["path"]).read_bytes())
    packet = FinchPacket.model_validate(began["packet"]["packet"])
    assert client.call("reading_begin", source=paper.id)[1]["session_id"] == packet.id
    response = returned(packet).model_dump(mode="json")
    failed, read = client.call("reading_finish", response=response)
    assert not failed and read["workflow_stage"] == "validated", read
    assert client.call("reading_finish", response=response)[1] == read

    failed, wrote = client.call(
        "writing_begin",
        instructions="Write a short concept page on the result.",
        new_type="concept",
        title="Result C",
        from_ids=[paper.id],
    )
    assert not failed, wrote
    quill_packet = wrote["packet"]["packet"]
    failed, written = client.call(
        "writing_finish",
        response={
            "packet_id": quill_packet["id"],
            "input_hash": wrote["input_hash"],
            "body_markdown": "The synthetic study reports 42 under condition C.\n",
            "claims": [
                {
                    "text": "The reported value is 42 under condition C.",
                    "kind": "reported_result",
                    "evidence_keys": ["ev1"],
                    "quotations": [{"evidence_key": "ev1", "text": "42 under condition C"}],
                }
            ],
        },
    )
    assert not failed, written

    failed, began_draft = client.call("draft_begin", source=paper.id)
    assert not failed, began_draft
    job = Job.model_validate(began_draft["packet"]["packet"])
    failed, drafted_receipt = client.call(
        "draft_finish", response=drafted(job).model_dump(mode="json")
    )
    assert not failed and drafted_receipt["workflow_stage"] == "validated", drafted_receipt

    failed, queue = client.call("pending")
    assert not failed and not queue["packets"]
    staged = {item["proposal_id"] for item in queue["proposals"]}
    assert staged == {
        read["proposal_id"],
        written["proposal_id"],
        drafted_receipt["proposal_id"],
    }
    failed, report = client.call("proposal_show", proposal_id=read["proposal_id"])
    assert not failed and report["id"] == read["proposal_id"]
    failed, hits = client.call("search", query="synthetic result")
    assert not failed and hits["hits"]
    failed, evidence = client.call("evidence", source_id=paper.id)
    assert not failed and evidence["segments"]
    # Nothing was approved or applied; the owner's steps remain.
    assert not ws.fs.files("approvals")
    validate_payloads(durable_contents(Workspace(ws.root)))


def test_grants_bound_every_tool(ws, tmp_path, client):
    paper = source(ws, processing="cloud_eligible")
    private = source(ws, text="Local-only synthetic 42.", processing="local_only")
    failed, error = client.call("reading_begin", source=paper.id)
    assert failed and error["error"] == "denied"
    failed, error = client.call("evidence", source_id=paper.id)
    assert failed and error["error"] == "denied"
    assert not ws.fs.files("receipts/finch/exports")
    assert not client.packets.exists() or not any(client.packets.rglob("*.json"))
    grant(ws)
    failed, hits = client.call("search", query="synthetic")
    assert not failed
    assert {hit["id"] for hit in hits["hits"]} == {paper.id}
    assert hits["withheld_local_only_or_ungranted"] >= 1
    failed, error = client.call("evidence", source_id=private.id)
    assert failed and error["error"] == "denied"
    failed, error = client.call("draft_begin", source=private.id)
    assert failed and error["error"] == "denied"


def test_untrusted_responses_are_rejected_without_side_effects(ws, tmp_path, client):
    grant(ws)
    paper = source(ws, processing="cloud_eligible")
    _, began = client.call("reading_begin", source=paper.id)
    packet = FinchPacket.model_validate(began["packet"]["packet"])
    forged = returned(packet).model_dump(mode="json") | {"approved": True}
    failed, error = client.call("reading_finish", response=forged)
    assert failed and error["error"] == "invalid"
    wrong = returned(packet).model_dump(mode="json") | {"input_hash": "0" * 64}
    failed, error = client.call("reading_finish", response=wrong)
    assert failed and error["error"] == "denied"
    assert not ws.fs.files("receipts/finch/imports")
    assert digest(canonical(packet)) == began["input_hash"]


def test_file_capture_needs_owner_root_and_labels(ws, tmp_path):
    grant(ws)
    papers = tmp_path / "papers"
    papers.mkdir()
    inside = papers / "paper.txt"
    inside.write_text("Synthetic captured result: 42 under condition C.")
    outside = tmp_path / "elsewhere.txt"
    outside.write_text("Synthetic outside file.")
    unconfigured = Client(ws, tmp_path)
    failed, error = unconfigured.call("reading_begin", source=str(inside))
    assert failed and "capture" in error["message"]
    unconfigured.close()
    labels = tmp_path / "labels.json"
    labels.write_text(json.dumps({"domain": "research", "processing": "cloud_eligible"}))
    client = Client(
        ws, tmp_path, "--capture-root", str(papers), "--capture-labels", str(labels)
    )
    failed, error = client.call("reading_begin", source=str(outside))
    assert failed and "capture root" in error["message"]
    failed, began = client.call("reading_begin", source=str(inside))
    assert not failed, began
    assert began["source_id"].startswith("source_")
    client.close()


def test_launch_validation_and_print_config(ws, tmp_path):
    runner = CliRunner()
    base = ["mcp", "--workspace", str(ws.root), "--provider", "synthetic-agent"]
    base += ["--destination", "https://synthetic.invalid"]
    inside = runner.invoke(app, [*base, "--packets-dir", str(ws.root / "packets")])
    assert inside.exit_code == 3 and "outside the workspace" in inside.output
    unknown = runner.invoke(
        app, [*base, "--packets-dir", str(tmp_path / "p"), "--scope", "nowhere"]
    )
    assert unknown.exit_code == 3
    printed = runner.invoke(app, [*base, "--packets-dir", str(tmp_path / "p"), "--print-config"])
    assert printed.exit_code == 0, printed.output
    config = json.loads(printed.stdout)
    assert config["claude_code"].startswith("claude mcp add cairn -- ")
    assert config["codex"].startswith("codex mcp add cairn -- ")
    assert config["cursor_mcp_json"]["mcpServers"]["cairn"]["args"][0] == "mcp"
    assert "Bash(cairn approve:*)" in config["claude_code_deny_rules"]
