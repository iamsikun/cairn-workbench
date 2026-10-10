import shlex
import shutil
from pathlib import Path
from typing import Annotated

import typer

from cairn.cli.commands import WorkspaceOption, emit, guarded
from cairn.ingest.service import read_source_file
from cairn.records.models import Labels

OWNER_COMMANDS = ("approve", "accept", "apply", "policy", "schema", "update", "recover")


def connect_config(arguments: list[str], protected: list[Path]) -> dict[str, object]:
    """Registration and confinement snippets; Cairn never edits agent configuration.

    MCP servers run outside Claude Code's shell sandbox, so `cairn mcp` can still write
    while the agent's own shell cannot touch the knowledge base or Cairn's data.
    """
    command = shutil.which("cairn") or "cairn"
    server = [command, "mcp", *arguments]
    paths = [str(path) for path in protected]
    return {
        "claude_code": shlex.join(["claude", "mcp", "add", "cairn", "--", *server]),
        "codex": shlex.join(["codex", "mcp", "add", "cairn", "--", *server]),
        "cursor_mcp_json": {"mcpServers": {"cairn": {"command": command, "args": server[1:]}}},
        "claude_code_settings": {
            "sandbox": {"enabled": True, "filesystem": {"denyWrite": paths}},
            "permissions": {
                "deny": [
                    *(f"Edit(/{path}/**)" for path in paths),
                    *(f"Bash(cairn {name} *)" for name in OWNER_COMMANDS),
                ]
            },
        },
        "codex_sandbox": 'sandbox_mode = "workspace-write"; keep these paths outside the '
        "workspace and out of [sandbox_workspace_write] writable_roots: " + ", ".join(paths),
        "note": "Put claude_code_settings in ~/.claude/settings.json. The sandbox is what "
        "stops an agent's shell from writing your knowledge base; deny rules are a second "
        "layer, and owner commands also require your own terminal.",
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
        scope: str = "research",
        capture_root: Annotated[
            Path | None, typer.Option(help="Folder the agent may capture new sources from.")
        ] = None,
        capture_labels: Annotated[
            Path | None, typer.Option(help="JSON labels for sources captured from that folder.")
        ] = None,
        html_root: Annotated[
            Path | None, typer.Option(help="Folder for explicitly requested, tracked HTML views.")
        ] = None,
        inline_synthetic: Annotated[bool, typer.Option(hidden=True)] = False,
        print_config: Annotated[
            bool, typer.Option(help="Print agent registration and sandbox settings and exit.")
        ] = False,
    ) -> None:
        """Serve Cairn's agent tools over stdio (MCP) for one scope and agent route."""
        from cairn.mcp import Session, check_session, main
        from cairn.updater.home import Home

        arguments = [
            "--workspace",
            str(workspace.absolute()),
            "--scope",
            scope,
            "--provider",
            provider,
            "--destination",
            destination,
        ]
        if capture_root is not None:
            arguments += ["--capture-root", str(capture_root.absolute())]
        if capture_labels is not None:
            arguments += ["--capture-labels", str(capture_labels.absolute())]
        if html_root is not None:
            arguments += ["--html-root", str(html_root.absolute())]
        session = Session(
            workspace=workspace,
            scope=scope,
            provider=provider,
            destination=destination,
            capture_root=capture_root.absolute() if capture_root else None,
            capture_labels=Labels.model_validate_json(read_source_file(capture_labels))
            if capture_labels
            else None,
            inline_synthetic=inline_synthetic,
            html_root=html_root.absolute() if html_root else None,
        )
        check_session(session)
        if print_config:
            protected = [workspace.absolute(), Home.from_env().root.absolute()]
            emit(connect_config(arguments, protected), True)
            return
        main(session)
