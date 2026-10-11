import base64
import json
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from cairn.errors import Conflict, RecoveryRequired
from cairn.saving.connections import connection
from cairn.saving.mcp import call, instructions
from cairn.saving.models import Capture, SourceInput
from cairn.saving.service import save
from cairn.saving.workspace import Book
from cairn.storage.files import RootFS


@pytest.mark.parametrize("client", ["claude", "codex"])
def test_connection_idempotency_repair_and_disconnect(tmp_path: Path, client: str) -> None:
    book = Book.init(tmp_path / "book", synthetic=True)
    home = tmp_path / "synthetic-home"
    home.mkdir()
    fs = RootFS(home)
    path = ".claude.json" if client == "claude" else ".codex/config.toml"
    original = (
        b'{"theme":"dark","mcpServers":{"other":{"command":"other"}}}\n'
        if client == "claude"
        else b'# My settings\nmodel = "example"\n[mcp_servers.other]\ncommand = "other"\n'
    )
    fs.write(path, original)
    result = connection(home, client, book, "research")
    after = fs.read(path)
    assert result == connection(home, client, book, "research")
    assert fs.read(path) == after
    assert connection(home, client, book, "research", "check")["configured"]
    modified = after.replace(sys.executable.encode(), b"changed-command")
    fs.write(path, modified)
    with pytest.raises(Conflict):
        connection(home, client, book, "research")
    assert not connection(home, client, book, "research", "check")["configured"]
    connection(home, client, book, "research", "repair")
    connection(home, client, book, "research", "disconnect")
    parsed = (
        json.loads(fs.read(path)) if client == "claude" else tomllib.loads(fs.read(path).decode())
    )
    assert parsed == (
        json.loads(original) if client == "claude" else tomllib.loads(original.decode())
    )
    assert result["client_trial"] == "unverified"


def test_interrupted_registration_recovers_only_unchanged_settings(
    tmp_path: Path, monkeypatch
) -> None:
    book = Book.init(tmp_path / "book", synthetic=True)
    home = tmp_path / "synthetic-home"
    home.mkdir()
    original = RootFS.write

    def fail(self, path, data, **kwargs):
        if path == ".claude.json":
            raise OSError("interrupted")
        return original(self, path, data, **kwargs)

    monkeypatch.setattr(RootFS, "write", fail)
    with pytest.raises(OSError):
        connection(home, "claude", book, "research")
    monkeypatch.setattr(RootFS, "write", original)
    with pytest.raises(RecoveryRequired):
        connection(home, "claude", book, "research")
    assert connection(home, "claude", book, "research", "repair")["status"] == "connected"


def test_cli_and_six_tool_stdio_checkpoint(tmp_path: Path) -> None:
    root = tmp_path / "book"
    command = [sys.executable, "-m", "cairn"]
    initialized = subprocess.run(
        [*command, "init", str(root), "--synthetic"], capture_output=True, check=True
    )
    assert json.loads(initialized.stdout)["schema"] == 4
    process = subprocess.Popen(
        [*command, "mcp", "--workspace", str(root)], stdin=subprocess.PIPE, stdout=subprocess.PIPE
    )
    assert process.stdin and process.stdout

    def rpc(method, params=None):
        process.stdin.write(
            json.dumps(
                {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
            ).encode()
            + b"\n"
        )
        process.stdin.flush()
        return json.loads(process.stdout.readline())["result"]

    try:
        assert "Finch" in rpc("initialize")["instructions"]
        assert {t["name"] for t in rpc("tools/list")["tools"]} == {
            "capture",
            "search",
            "get_note",
            "list_topics",
            "save_reading",
            "save_note",
        }
        request = {
            "operation_key": "checkpoint",
            "paper": {"identity": "doi:10.999/demo", "title": "Synthetic paper"},
            "note": {
                "title": "Paper A",
                "markdown": "Partial reading",
                "unresolved": ["Connect architecture"],
                "enrichment": "pending",
            },
        }
        first = rpc("tools/call", {"name": "save_reading", "arguments": request})
        assert not first["isError"]
        assert first == rpc("tools/call", {"name": "save_reading", "arguments": request})
        results = rpc("tools/call", {"name": "search", "arguments": {"query": "Partial"}})
        identity = json.loads(results["content"][0]["text"])[0]["id"]
        current = rpc("tools/call", {"name": "get_note", "arguments": {"id": identity}})
        assert json.loads(current["content"][0]["text"])["unresolved"] == ["Connect architecture"]
        assert rpc(
            "tools/call", {"name": "save_note", "arguments": {**request, "collection": "finance"}}
        )["isError"]
    finally:
        process.stdin.close()
        process.wait(timeout=15)


def test_external_reference_and_failed_pdf_are_still_saved(tmp_path: Path) -> None:
    book = Book.init(tmp_path / "book", synthetic=True)
    request = Capture(
        operation_key="external",
        source=SourceInput(identity="https://example.invalid/paper", title="Paper"),
    )
    external = save(book, "research", request)
    source = book.record(external["notes"][0]["id"], "research")[1].source
    assert source and source.extraction_status == "unavailable" and source.authors == []
    broken = b"%PDF-1.7\ntruncated"
    failed = save(
        book,
        "research",
        Capture(
            operation_key="pdf", source=request.source, pdf_base64=base64.b64encode(broken).decode()
        ),
    )
    source = book.record(failed["notes"][0]["id"], "research")[1].source
    assert source and source.extraction_status == "failed" and source.original_blob
    assert book.fs.read(source.original_blob) == broken
    assert "If a skill is unavailable" in instructions()
    assert call(book, "research", "get_note", {"id": "concept_nonexistent"})["isError"]


def test_native_pdf_capture_reuses_registered_source_for_reading(tmp_path: Path):
    from test_library_catalog import pdf

    from cairn.saving.models import NoteChange, SaveReading

    book = Book.init(tmp_path / "book", synthetic=True)
    raw = pdf("Synthetic paper text")
    source = SourceInput(identity="doi:10.999/pdf", title="Synthetic PDF")
    captured = save(
        book,
        "research",
        Capture(operation_key="pdf", source=source, pdf_base64=base64.b64encode(raw).decode()),
    )
    identity = captured["notes"][0]["id"]
    info = book.record(identity, "research")[1].source
    assert info and info.extraction_status == "extracted" and info.original_blob
    assert book.fs.read(info.original_blob) == raw
    reading = save(
        book,
        "research",
        SaveReading(
            operation_key="read",
            paper=source,
            source_id=identity,
            note=NoteChange(title="My reading", markdown="A partial interpretation"),
        ),
    )
    record = book.record(reading["notes"][0]["id"], "research")[1]
    assert record.primary_source_id == identity and record.source_versions == [identity]
