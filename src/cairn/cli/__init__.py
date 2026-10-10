from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from cairn import __version__
from cairn.cli.commands import guarded, register
from cairn.cli.domains import register as register_domains
from cairn.cli.finch import register as register_finch
from cairn.cli.library import register as register_library
from cairn.cli.policy import register as register_policy
from cairn.cli.presentation import register as register_presentation
from cairn.cli.release import register as register_release
from cairn.cli.research import register as register_research
from cairn.cli.schema import register as register_schema
from cairn.cli.write import register as register_write
from cairn.errors import CairnError
from cairn.records.runtime import ReviewAcknowledgement
from cairn.storage.workspace import Workspace

app = typer.Typer(no_args_is_help=True, help="Preserved evidence and owner-reviewed knowledge.")
register(app)
register_research(app)
register_domains(app)
register_policy(app)
register_release(app)
register_schema(app)
register_library(app)
register_presentation(app)
register_finch(app)
register_write(app)


@app.command()
def version() -> None:
    """Print the installed software version."""
    typer.echo(__version__)


@app.command()
@guarded
def init(
    workspace: Annotated[Path, typer.Option()],
    code_root: Annotated[Path, typer.Option()],
    synthetic: Annotated[bool, typer.Option()] = False,
    worker_image: Annotated[str | None, typer.Option()] = None,
    release: Annotated[Path | None, typer.Option()] = None,
    release_sha256: Annotated[str | None, typer.Option()] = None,
    statement: Annotated[str | None, typer.Option()] = None,
    acknowledge: Annotated[list[ReviewAcknowledgement] | None, typer.Option()] = None,
    quill_skills_dir: Annotated[
        Path | None, typer.Option(help="Where to install Quill if not machine-wide.")
    ] = None,
    no_quill: Annotated[bool, typer.Option("--no-quill")] = False,
    finch: Annotated[
        bool | None,
        typer.Option(
            "--finch/--no-finch",
            help="Install Finch for detected agents if missing (default for private workspaces).",
        ),
    ] = None,
    finch_auto_update: Annotated[
        bool, typer.Option(help="Let Finch schedule its own daily update.")
    ] = True,
) -> None:
    """Initialize an empty, separate workspace (synthetic during development).

    Quill, the writing skill, is installed for this knowledge base unless it is
    already available machine-wide.
    """
    try:
        if not synthetic and worker_image:
            from cairn.errors import Denied

            raise Denied("private worker image is selected by the reviewed release manifest")
        ws = Workspace.init(
            workspace,
            code_roots=[code_root],
            synthetic=synthetic,
            release=release,
            release_sha256=release_sha256,
            statement=statement,
            acknowledgements=set(acknowledge) if acknowledge else None,
        )
        if worker_image:
            from cairn.adapters.isolation import container_command
            from cairn.records.models import canonical

            container_command(worker_image)
            ws.config.worker_image = worker_image
            ws.fs.write("workspace.json", canonical(ws.config))
        result: dict[str, object] = {
            "workspace_id": ws.config.id,
            "synthetic": ws.config.synthetic,
        }
        if not no_quill:
            from cairn.presentation.quill import ensure_for_workspace

            result["quill"] = ensure_for_workspace(ws.root, skills_dir=quill_skills_dir)
        if (not synthetic) if finch is None else finch:
            from cairn.reading.skill import install

            # A missing or offline Finch install never blocks the workspace; it stays pending.
            try:
                result["finch"] = install(auto_update=finch_auto_update)
            except CairnError as exc:
                result["finch"] = {"skill": "finch", "state": "pending", "reason": exc.code}
        typer.echo(json.dumps(result))
    except CairnError as exc:
        typer.echo(json.dumps({"error": exc.code, "message": str(exc)}), err=True)
        raise typer.Exit(exc.exit_status) from exc
