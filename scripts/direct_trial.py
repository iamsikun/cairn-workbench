"""Installed-package trial with synthetic homes and a real subprocess MCP client.

Run in native synthetic scratch after installing the wheel. No agent model is invoked.
"""

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any


def trial(python: Path, env: dict[str, str], root: Path) -> dict[str, Any]:
    directory = Path(tempfile.mkdtemp(prefix="direct-save-", dir=root))
    workspace = directory / "knowledge"
    settings = directory / "synthetic-home"
    settings.mkdir()

    def cli(*args: str) -> Any:
        result = subprocess.run(
            [str(python), "-I", "-B", "-m", "cairn", *args],
            env=env,
            capture_output=True,
            check=True,
            timeout=30,
        )
        return json.loads(result.stdout)

    assert cli("init", str(workspace), "--synthetic")["schema"] == 4
    subprocess.run(
        [str(python.parent / "cairn"), "--help"],
        env=env,
        capture_output=True,
        check=True,
        timeout=30,
    )
    legacy = directory / "legacy"
    code = directory / "synthetic-code"
    code.mkdir()
    cli("legacy", "init", "--workspace", str(legacy), "--code-root", str(code), "--synthetic")
    cli(
        "legacy",
        "note",
        "Synthetic personal research observation",
        "--domain",
        "research",
        "--workspace",
        str(legacy),
        "--json",
    )
    assert (
        cli("migrate", "--workspace", str(legacy), "--backup", str(directory / "legacy.zip"))[
            "status"
        ]
        == "migrated"
    )
    assert cli("search", "observation", "--workspace", str(legacy))
    for client in ("claude", "codex"):
        args = ("connect", client, "--workspace", str(workspace), "--settings-home", str(settings))
        first = cli(*args)
        assert cli(*args) == first
        assert cli(*args, "--check")["configured"]
    process = subprocess.Popen(
        [str(python), "-I", "-B", "-m", "cairn", "mcp", "--workspace", str(workspace)],
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
    )
    assert process.stdin and process.stdout

    def rpc(method: str, params: dict[str, Any] | None = None) -> Any:
        assert process.stdin and process.stdout
        process.stdin.write(
            json.dumps(
                {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
            ).encode()
            + b"\n"
        )
        process.stdin.flush()
        return json.loads(process.stdout.readline())["result"]

    try:
        assert "Quill" in rpc("initialize")["instructions"]
        assert len(rpc("tools/list")["tools"]) == 6
        request = {
            "operation_key": "installed",
            "note": {
                "title": "Installed notebook",
                "kind": "topic",
                "markdown": "Synthetic package evidence.",
                "observations": [{"id": "observation_trial", "text": "Original observation"}],
            },
        }
        first = rpc("tools/call", {"name": "save_note", "arguments": request})
        assert not first["isError"]
        assert rpc("tools/call", {"name": "save_note", "arguments": request}) == first
        result = json.loads(first["content"][0]["text"])
        identity = result["notes"][0]["id"]
    finally:
        process.stdin.close()
        process.wait(timeout=30)
    assert cli("search", "package", "--workspace", str(workspace))[0]["id"] == identity
    view = cli("presentation", "render", identity, "--workspace", str(workspace))
    assert view["freshness"] == "current" and Path(view["path"]).is_file()
    archive = directory / "backup.zip"
    cli("backup", str(archive), "--workspace", str(workspace))
    restored = directory / "restored"
    cli("restore", str(archive), str(restored))
    assert (
        cli("get-note", identity, "--workspace", str(restored))["observations"][0]["text"]
        == "Original observation"
    )
    cli("undo", result["id"], "undo-package-trial", "--workspace", str(workspace))
    assert cli("search", "package", "--workspace", str(workspace)) == []
    return {
        "schema": 4,
        "tools": 6,
        "installed_stdio": "passed",
        "connection_adapters": "passed",
        "backup_restore": "passed",
        "legacy_to_v4": "passed",
        "html": "passed",
        "actual_clients": "unverified",
    }
