from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from cairn import __version__
from cairn.errors import CairnError
from cairn.storage.workspace import Workspace

app = typer.Typer(no_args_is_help=True, help="Preserved evidence and owner-reviewed knowledge.")


@app.command()
def version() -> None:
    """Print the installed software version."""
    typer.echo(__version__)


@app.command()
def init(
    workspace: Annotated[Path, typer.Option()],
    code_root: Annotated[Path, typer.Option()],
    synthetic: Annotated[bool, typer.Option()] = False,
) -> None:
    """Initialize an empty, separate workspace (synthetic during development)."""
    try:
        ws = Workspace.init(workspace, code_roots=[code_root], synthetic=synthetic)
        typer.echo(json.dumps({"workspace_id": ws.config.id, "synthetic": ws.config.synthetic}))
    except CairnError as exc:
        typer.echo(json.dumps({"error": exc.code, "message": str(exc)}), err=True)
        raise typer.Exit(exc.exit_status) from exc
