from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from cairn import __version__
from cairn.cli.commands import register
from cairn.cli.domains import register as register_domains
from cairn.cli.policy import register as register_policy
from cairn.cli.research import register as register_research
from cairn.errors import CairnError
from cairn.storage.workspace import Workspace

app = typer.Typer(no_args_is_help=True, help="Preserved evidence and owner-reviewed knowledge.")
register(app)
register_research(app)
register_domains(app)
register_policy(app)


@app.command()
def version() -> None:
    """Print the installed software version."""
    typer.echo(__version__)


@app.command()
def init(
    workspace: Annotated[Path, typer.Option()],
    code_root: Annotated[Path, typer.Option()],
    synthetic: Annotated[bool, typer.Option()] = False,
    worker_image: Annotated[str | None, typer.Option()] = None,
) -> None:
    """Initialize an empty, separate workspace (synthetic during development)."""
    try:
        ws = Workspace.init(workspace, code_roots=[code_root], synthetic=synthetic)
        if worker_image:
            from cairn.adapters.isolation import container_command
            from cairn.records.models import canonical

            container_command(worker_image)
            ws.config.worker_image = worker_image
            ws.fs.write("workspace.json", canonical(ws.config))
        typer.echo(json.dumps({"workspace_id": ws.config.id, "synthetic": ws.config.synthetic}))
    except CairnError as exc:
        typer.echo(json.dumps({"error": exc.code, "message": str(exc)}), err=True)
        raise typer.Exit(exc.exit_status) from exc
