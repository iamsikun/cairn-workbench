from pathlib import Path
from typing import Annotated

import typer

from cairn.adapters.legacy import retired
from cairn.cli.commands import JsonOption, WorkspaceOption, emit, guarded
from cairn.errors import Denied
from cairn.storage import upgrade
from cairn.storage.workspace import Workspace
from cairn.updater import schedule
from cairn.updater.home import DEFAULT_REF, DEFAULT_REPOSITORY, Home, UpdaterConfig, bound_release

ENABLE_STATEMENT = (
    "I authorize this knowledge base to adopt future Cairn releases from the configured "
    "channel, with automatic backups and schema migrations."
)


def configured(home: Home) -> UpdaterConfig:
    config = home.config()
    if config is None:
        raise Denied("no historical managed update configuration was found")
    return config


def register_workspace(home: Home, root: Path, *, add: bool) -> None:
    config = configured(home)
    path = str(root.absolute())
    workspaces = [item for item in config.workspaces if item != path]
    config.workspaces = [*workspaces, path] if add else workspaces
    home.save_config(config)


def enable_workspace(home: Home, ws: Workspace, statement: str) -> dict[str, object]:
    retired("Managed automatic updates")


def register(app: typer.Typer) -> None:
    update = typer.Typer(
        help="Historical update status and removal; installation and updates are retired."
    )
    app.add_typer(update, name="update")

    @update.command("setup")
    @guarded
    def setup(
        repository: str = DEFAULT_REPOSITORY,
        ref: str = DEFAULT_REF,
        bin_dir: Annotated[Path | None, typer.Option(help="Where to put `cairn`.")] = None,
        schedule_updates: Annotated[bool, typer.Option("--schedule/--no-schedule")] = True,
        interval_hours: int = 24,
    ) -> None:
        retired("Managed automatic updates")

    @update.command("run")
    @guarded
    def run(
        if_due: Annotated[bool, typer.Option("--if-due")] = False,
        quiet: Annotated[bool, typer.Option("--quiet")] = False,
    ) -> None:
        retired("Managed automatic updates")

    @update.command("status")
    @guarded
    def status(json_output: JsonOption = True) -> None:
        home = Home.from_env()
        config = home.config()
        current = home.current_runtime()
        current_sha = current.release_sha256 if current else None
        state = home.state()
        emit(
            {
                "configured": config is not None,
                "enabled": bool(config and config.enabled),
                "repository": config.repository if config else None,
                "ref": config.ref if config else None,
                "current": current,
                "running": home.running_runtime(),
                "last_check": state.last_check,
                "last_result": state.last_result,
                "errors": state.errors,
                "workspaces": {
                    path: {
                        "bound_release": bound_release(Path(path)),
                        "on_current": current_sha is not None
                        and bound_release(Path(path)) == current_sha,
                    }
                    for path in (config.workspaces if config else [])
                },
            },
            json_output,
        )

    @update.command("enable")
    @guarded
    def enable(workspace: WorkspaceOption, statement: str = ENABLE_STATEMENT) -> None:
        retired("Managed automatic updates")

    @update.command("disable")
    @guarded
    def disable(
        workspace: WorkspaceOption,
        statement: str = "I stop automatic updates for this knowledge base.",
    ) -> None:
        """Stop automatic updates; the current release binding remains valid."""
        from cairn.cli.commands import owner_confirm

        home = Home.from_env()
        ws = Workspace(workspace)
        owner_confirm(ws, "disable", "Stop automatic Cairn updates for this knowledge base.")
        revocation = upgrade.disable(ws, statement=statement)
        if home.config() is not None:
            register_workspace(home, workspace, add=False)
        emit({"disabled": True, "revocation": revocation}, True)

    @update.command("schedule")
    @guarded
    def schedule_command(off: Annotated[bool, typer.Option("--off")] = False) -> None:
        """Remove a historical periodic update job with --off; creation is retired."""
        if not off:
            retired("Managed update scheduling")
        emit(schedule.remove(user_home=Path.home()), True)

    @update.command("rebind", hidden=True)
    @guarded
    def rebind(
        workspace: WorkspaceOption,
        release: Annotated[Path, typer.Option()],
        release_sha256: Annotated[str, typer.Option()],
        mirror: Annotated[Path, typer.Option()],
        tag: Annotated[str, typer.Option()],
        backup_dir: Annotated[Path, typer.Option()],
    ) -> None:
        retired("Managed automatic updates")
