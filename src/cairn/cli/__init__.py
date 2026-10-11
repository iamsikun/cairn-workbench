from __future__ import annotations

import json
import shlex
from pathlib import Path
from typing import Annotated

import typer

from cairn import __version__
from cairn.cli.agent import register as register_agent
from cairn.cli.code_source import register as register_code_source
from cairn.cli.commands import guarded, register
from cairn.cli.domains import register as register_domains
from cairn.cli.library import register as register_library
from cairn.cli.policy import register as register_policy
from cairn.cli.presentation import register as register_presentation
from cairn.cli.release import register as register_release
from cairn.cli.research import register as register_research
from cairn.cli.schema import register as register_schema
from cairn.cli.update import register as register_update
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
register_update(app)
register_agent(app)
register_code_source(app)


@app.command()
def version() -> None:
    """Print the installed software version."""
    typer.echo(__version__)


@app.command()
@guarded
def init(
    workspace: Annotated[Path, typer.Option()],
    code_root: Annotated[
        Path | None, typer.Option(help="A local Cairn checkout to keep disjoint (optional).")
    ] = None,
    repository: Annotated[
        str | None,
        typer.Option(help="Cairn's code repository; managed installs default to the updater's."),
    ] = None,
    synthetic: Annotated[bool, typer.Option()] = False,
    worker_image: Annotated[str | None, typer.Option()] = None,
    release: Annotated[Path | None, typer.Option()] = None,
    release_sha256: Annotated[str | None, typer.Option()] = None,
    statement: Annotated[str | None, typer.Option()] = None,
    acknowledge: Annotated[list[ReviewAcknowledgement] | None, typer.Option()] = None,
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
        if worker_image or auto_update:
            from cairn.adapters.legacy import retired

            retired("Legacy worker configuration/automatic updates")
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
        updater = home.config()
        if repository is None and updater is not None:
            repository = updater.repository
        ws = Workspace.init(
            workspace,
            code_roots=[code_root] if code_root else [],
            code_repository=repository,
            synthetic=synthetic,
            release=release,
            release_sha256=release_sha256,
            statement=statement,
            acknowledgements=set(acknowledge) if acknowledge else None,
        )
        result: dict[str, object] = {
            "workspace_id": ws.config.id,
            "synthetic": ws.config.synthetic,
            "connect": f"cairn mcp --print-config --workspace {shlex.quote(str(ws.root))} "
            "--provider AGENT --destination DESTINATION",
        }
        if auto_update and statement:
            from cairn.cli.update import ENABLE_STATEMENT, enable_workspace

            result["auto_update"] = enable_workspace(home, ws, f"{statement} {ENABLE_STATEMENT}")
        typer.echo(json.dumps(result))
    except CairnError as exc:
        typer.echo(json.dumps({"error": exc.code, "message": str(exc)}), err=True)
        raise typer.Exit(exc.exit_status) from exc
