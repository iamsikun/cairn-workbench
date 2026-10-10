import shlex
import shutil
from pathlib import Path
from typing import Annotated

import typer

from cairn.cli.commands import WorkspaceOption, emit, guarded
from cairn.ingest.service import read_source_file
from cairn.records.models import Labels

OWNER_ONLY = ("approve", "accept", "apply")


def connect_config(arguments: list[str]) -> dict[str, object]:
    """Registration snippets for common agents; Cairn never edits agent configuration."""
    command = shutil.which("cairn") or "cairn"
    server = [command, "mcp", *arguments]
    return {
        "claude_code": shlex.join(["claude", "mcp", "add", "cairn", "--", *server]),
        "codex": shlex.join(["codex", "mcp", "add", "cairn", "--", *server]),
        "cursor_mcp_json": {"mcpServers": {"cairn": {"command": command, "args": server[1:]}}},
        "claude_code_deny_rules": [f"Bash(cairn {name}:*)" for name in OWNER_ONLY],
        "note": "Approval, accept and apply are not MCP tools. If the agent also has a shell, "
        "deny those commands in its settings; owner review stays your step.",
    }


def register(app: typer.Typer) -> None:
    @app.command("mcp")
    @guarded
    def mcp(
        workspace: WorkspaceOption,
        provider: Annotated[str, typer.Option(help="Agent provider named by your cloud grant.")],
        destination: Annotated[
            str, typer.Option(help="Agent destination named by your cloud grant.")
        ],
        packets_dir: Annotated[
            Path, typer.Option(help="Where packets and responses are written (outside the KB).")
        ],
        scope: str = "research",
        capture_root: Annotated[
            Path | None, typer.Option(help="Folder the agent may capture new sources from.")
        ] = None,
        capture_labels: Annotated[
            Path | None, typer.Option(help="JSON labels for sources captured from that folder.")
        ] = None,
        inline_synthetic: Annotated[bool, typer.Option(hidden=True)] = False,
        print_config: Annotated[
            bool, typer.Option(help="Print agent registration snippets and exit.")
        ] = False,
    ) -> None:
        """Serve Cairn's agent tools over stdio (MCP) for one scope and agent route."""
        from cairn.mcp import Session, check_session, main

        arguments = [
            "--workspace",
            str(workspace.absolute()),
            "--scope",
            scope,
            "--provider",
            provider,
            "--destination",
            destination,
            "--packets-dir",
            str(packets_dir.absolute()),
        ]
        if capture_root is not None:
            arguments += ["--capture-root", str(capture_root.absolute())]
        if capture_labels is not None:
            arguments += ["--capture-labels", str(capture_labels.absolute())]
        session = Session(
            workspace=workspace,
            scope=scope,
            provider=provider,
            destination=destination,
            packets_dir=packets_dir.absolute(),
            capture_root=capture_root.absolute() if capture_root else None,
            capture_labels=Labels.model_validate_json(read_source_file(capture_labels))
            if capture_labels
            else None,
            inline_synthetic=inline_synthetic,
        )
        check_session(session)
        if print_config:
            emit(connect_config(arguments), True)
            return
        main(session)
