from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from cairn.cli.commands import JsonOption, WorkspaceOption, emit, guarded
from cairn.ingest.service import read_source_file
from cairn.policies.audit import (
    RouteRequest,
    check_route,
    inspect_changes,
    revoke_grant,
    set_grant,
    set_scope,
)
from cairn.policies.models import RouteGrant, Scope
from cairn.records.json import read_json
from cairn.storage.workspace import Workspace


def _owner(workspace: Path) -> Workspace:
    from cairn.cli.commands import owner_confirm

    ws = Workspace(workspace)
    owner_confirm(ws, "policy", "Change this knowledge base's processing policy.")
    return ws


def register(app: typer.Typer) -> None:
    policy = typer.Typer(help="Owner-controlled scopes, processing consent, and route audits.")
    app.add_typer(policy, name="policy")

    @policy.command("show")
    @guarded
    def show(workspace: WorkspaceOption, json_output: JsonOption = False) -> None:
        ws = Workspace(workspace)
        with ws.lock():
            emit(
                {"sha256": ws.policy_hash, "policy": ws.policy, "cloud_execution_available": False},
                json_output,
            )

    @policy.command("set-scope")
    @guarded
    def change_scope(
        file: Path,
        workspace: WorkspaceOption,
        base_hash: Annotated[str, typer.Option()],
        statement: Annotated[str, typer.Option()],
        json_output: JsonOption = False,
    ) -> None:
        """Replace one scope; revoke grants tied to its previous definition."""
        scope = Scope.model_validate(read_json(read_source_file(file)))
        emit(
            set_scope(_owner(workspace), scope, base_hash=base_hash, statement=statement),
            json_output,
        )

    @policy.command("set-grant")
    @guarded
    def change_grant(
        file: Path,
        workspace: WorkspaceOption,
        base_hash: Annotated[str, typer.Option()],
        statement: Annotated[str, typer.Option()],
        json_output: JsonOption = False,
    ) -> None:
        """Record explicit consent for a scope, agent provider/destination and operations."""
        grant = RouteGrant.model_validate(read_json(read_source_file(file)))
        emit(
            set_grant(_owner(workspace), grant, base_hash=base_hash, statement=statement),
            json_output,
        )

    @policy.command("revoke-grant")
    @guarded
    def remove_grant(
        grant_id: str,
        workspace: WorkspaceOption,
        base_hash: Annotated[str, typer.Option()],
        statement: Annotated[str, typer.Option()],
        json_output: JsonOption = False,
    ) -> None:
        emit(
            revoke_grant(_owner(workspace), grant_id, base_hash=base_hash, statement=statement),
            json_output,
        )

    @policy.command("history")
    @guarded
    def history(workspace: WorkspaceOption, json_output: JsonOption = False) -> None:
        emit(inspect_changes(Workspace(workspace)), json_output)

    @policy.command("check-route")
    @guarded
    def check(file: Path, workspace: WorkspaceOption, json_output: JsonOption = False) -> None:
        """Audit a complete hypothetical request without executing or transmitting it."""
        request = RouteRequest.model_validate(read_json(read_source_file(file)))
        result = check_route(Workspace(workspace), request)
        emit(result, json_output)
        if result.decision != "allowed":
            raise typer.Exit(3 if result.decision == "denied" else 5)
