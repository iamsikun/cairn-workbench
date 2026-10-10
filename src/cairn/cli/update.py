import os
from pathlib import Path
from typing import Annotated

import typer

from cairn.cli.commands import JsonOption, WorkspaceOption, emit, guarded
from cairn.errors import Blocked, Denied
from cairn.storage import upgrade
from cairn.storage.workspace import Workspace
from cairn.updater import schedule, service, skills
from cairn.updater.home import DEFAULT_REF, DEFAULT_REPOSITORY, Home, UpdaterConfig, bound_release

ENABLE_STATEMENT = (
    "I authorize this knowledge base to adopt future Cairn releases signed by the "
    "configured keys, with automatic backups and schema migrations."
)


def read_signers(file: Path) -> list[str]:
    lines = [line.strip() for line in file.read_text().splitlines()]
    signers = [line for line in lines if line and not line.startswith("#")]
    if not signers:
        raise Denied("allowed signers file lists no keys")
    return signers


def configured(home: Home) -> UpdaterConfig:
    config = home.config()
    if config is None:
        raise Denied("automatic updates are not set up; run `cairn update setup`")
    return config


def register_workspace(home: Home, root: Path, *, add: bool) -> None:
    config = configured(home)
    path = str(root.absolute())
    workspaces = [item for item in config.workspaces if item != path]
    config.workspaces = [*workspaces, path] if add else workspaces
    home.save_config(config)


def enable_workspace(home: Home, ws: Workspace, statement: str) -> dict[str, object]:
    config = configured(home)
    authorization = upgrade.enable(
        ws,
        repository=config.repository,
        ref=config.ref,
        allowed_signers=config.allowed_signers,
        statement=statement,
    )
    register_workspace(home, ws.root, add=True)
    return {
        "workspace_id": ws.config.id,
        "update_authorization_id": authorization.id,
        "repository": authorization.repository,
        "ref": authorization.ref,
        "signers": len(authorization.allowed_signers),
    }


def register(app: typer.Typer) -> None:
    update = typer.Typer(help="Automatic, signed Cairn updates and managed skills.")
    app.add_typer(update, name="update")

    @update.command("setup")
    @guarded
    def setup(
        signers: Annotated[
            Path, typer.Option(help="SSH allowed-signers file of keys that sign releases.")
        ],
        repository: str = DEFAULT_REPOSITORY,
        ref: str = DEFAULT_REF,
        bin_dir: Annotated[Path | None, typer.Option(help="Where to put `cairn`.")] = None,
        schedule_updates: Annotated[bool, typer.Option("--schedule/--no-schedule")] = True,
        interval_hours: int = 24,
    ) -> None:
        """Install the newest signed release as a managed runtime and keep it current."""
        home = Home.from_env()
        existing = home.config()
        config = UpdaterConfig(
            repository=repository,
            ref=ref,
            allowed_signers=read_signers(signers),
            workspaces=existing.workspaces if existing else [],
            interval_hours=interval_hours,
            path=os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        )
        home.save_config(config)
        result = service.run(home)
        if home.current_runtime() is None:
            raise Blocked(f"no signed release could be installed: {result.get('reason', '')}")
        user_home = Path.home()
        report: dict[str, object] = {"update": result, "home": str(home.root)}
        report["shim"] = str(schedule.write_shim(home, bin_dir or user_home / ".local" / "bin"))
        if schedule_updates:
            report["schedule"] = schedule.install(home, config, user_home=user_home)
        emit(report, True)

    @update.command("run")
    @guarded
    def run(
        if_due: Annotated[bool, typer.Option("--if-due")] = False,
        quiet: Annotated[bool, typer.Option("--quiet")] = False,
    ) -> None:
        """Check the channel now; install, verify and adopt a newer signed release."""
        result = service.run(Home.from_env(), if_due=if_due)
        if not quiet or result.get("status") in ("updated", "failed"):
            emit(result, True)

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
                "skills": skills.status(home),
            },
            json_output,
        )

    @update.command("enable")
    @guarded
    def enable(workspace: WorkspaceOption, statement: str = ENABLE_STATEMENT) -> None:
        """Record standing owner consent for automatic updates of this knowledge base."""
        emit(enable_workspace(Home.from_env(), Workspace(workspace), statement), True)

    @update.command("disable")
    @guarded
    def disable(
        workspace: WorkspaceOption,
        statement: str = "I stop automatic updates for this knowledge base.",
    ) -> None:
        """Stop automatic updates; the current release binding remains valid."""
        home = Home.from_env()
        revocation = upgrade.disable(Workspace(workspace), statement=statement)
        if home.config() is not None:
            register_workspace(home, workspace, add=False)
        emit({"disabled": True, "revocation": revocation}, True)

    @update.command("schedule")
    @guarded
    def schedule_command(off: Annotated[bool, typer.Option("--off")] = False) -> None:
        """Install (or remove) the periodic update job."""
        home = Home.from_env()
        if off:
            emit(schedule.remove(user_home=Path.home()), True)
        else:
            emit(schedule.install(home, configured(home), user_home=Path.home()), True)

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
        """Run by a newly installed runtime: adopt it for one knowledge base."""
        emit(
            upgrade.rebind(
                workspace,
                release=release,
                release_sha256=release_sha256,
                mirror=mirror,
                tag=tag,
                backup_dir=backup_dir,
            ),
            True,
        )
