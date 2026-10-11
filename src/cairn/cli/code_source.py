from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from cairn.cli.commands import JsonOption, WorkspaceOption, emit, guarded
from cairn.storage.code_source import set_code_source, show
from cairn.storage.workspace import Workspace


def register(app: typer.Typer) -> None:
    code = typer.Typer(help="Where this knowledge base's Cairn code lives (owner-controlled).")
    app.add_typer(code, name="code-source")

    @code.command("show")
    @guarded
    def show_command(workspace: WorkspaceOption, json_output: JsonOption = False) -> None:
        emit(show(Workspace(workspace)), json_output)

    @code.command("set")
    @guarded
    def set_command(
        workspace: WorkspaceOption,
        statement: Annotated[str, typer.Option()],
        code_root: Annotated[
            list[Path] | None,
            typer.Option(help="Replace the local checkout paths kept disjoint (repeatable)."),
        ] = None,
        no_code_root: Annotated[
            bool, typer.Option(help="Remove every local checkout path.")
        ] = False,
        repository: Annotated[str | None, typer.Option(help="Replace the repository.")] = None,
        no_repository: Annotated[bool, typer.Option(help="Remove the repository.")] = False,
        json_output: JsonOption = False,
    ) -> None:
        """Change the code root or repository; options left out keep their current value."""
        from cairn.cli.commands import owner_confirm
        from cairn.errors import Denied

        if no_code_root and code_root:
            raise Denied("choose either --code-root or --no-code-root")
        roots = [] if no_code_root else code_root
        ws = Workspace(workspace)
        owner_confirm(ws, "code-source", "Change where this knowledge base's Cairn code lives.")
        emit(
            set_code_source(
                ws,
                code_roots=roots,
                repository=repository,
                clear_repository=no_repository,
                statement=statement,
            ),
            json_output,
        )
