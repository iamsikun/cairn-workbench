from __future__ import annotations

import json
import shlex
from pathlib import Path
from typing import Annotated

import typer

from cairn import __version__
from cairn.cli.agent import register as register_agent
from cairn.cli.commands import guarded, register
from cairn.cli.domains import register as register_domains
from cairn.cli.finch import register as register_finch
from cairn.cli.library import register as register_library
from cairn.cli.policy import register as register_policy
from cairn.cli.presentation import register as register_presentation
from cairn.cli.release import register as register_release
from cairn.cli.research import register as register_research
from cairn.cli.schema import register as register_schema
from cairn.cli.update import register as register_update
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
register_update(app)
register_agent(app)


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
    # Accepted and ignored: an older updater smoke-tests new runtimes with these flags.
    _no_quill: Annotated[bool, typer.Option("--no-quill", hidden=True)] = False,
    _no_finch: Annotated[bool, typer.Option("--no-finch", hidden=True)] = False,
    auto_update: Annotated[
        bool,
        typer.Option(
            "--auto-update/--no-auto-update",
            help="Adopt future stable Cairn releases automatically (managed runtime only).",
        ),
    ] = False,
) -> None:
    """Initialize an empty, separate workspace (synthetic during development)."""
    try:
        if not synthetic and worker_image:
            from cairn.errors import Denied

            raise Denied("private worker image is selected by the reviewed release manifest")
        from cairn.updater.home import Home

        home = Home.from_env()
        running = home.running_runtime()
        if not synthetic and release is None and release_sha256 is None and running:
            # A managed runtime carries the bundle it was verified and installed from.
            release = home.runtime(running.release_sha256) / "bundle" / "release.json"
            release_sha256 = running.release_sha256
        if auto_update and (synthetic or home.config() is None):
            from cairn.errors import Denied

            raise Denied("automatic updates need a private workspace and `cairn update setup`")
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
            "connect": f"cairn mcp --print-config --workspace {shlex.quote(str(ws.root))} "
            "--provider AGENT --destination DESTINATION --packets-dir DIR",
        }
        if auto_update and statement:
            from cairn.cli.update import ENABLE_STATEMENT, enable_workspace

            result["auto_update"] = enable_workspace(home, ws, f"{statement} {ENABLE_STATEMENT}")
        typer.echo(json.dumps(result))
    except CairnError as exc:
        typer.echo(json.dumps({"error": exc.code, "message": str(exc)}), err=True)
        raise typer.Exit(exc.exit_status) from exc
