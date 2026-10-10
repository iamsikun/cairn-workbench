from __future__ import annotations

import difflib
import json
from pathlib import Path
from typing import Annotated

import typer

from cairn.cli.commands import JsonOption, WorkspaceOption, emit, guarded
from cairn.records.models import canonical, digest
from cairn.storage.migration import apply, inspect, preview, recover
from cairn.storage.workspace import Workspace


def register(app: typer.Typer) -> None:
    schema = typer.Typer(help="Inspect formats and explicitly migrate through the owner writer.")
    app.add_typer(schema, name="schema")

    @schema.command("inspect")
    @guarded
    def inspect_command(workspace: WorkspaceOption, json_output: JsonOption = False) -> None:
        emit(inspect(Workspace(workspace)), json_output)

    @schema.command("preview")
    @guarded
    def preview_command(workspace: WorkspaceOption, json_output: JsonOption = False) -> None:
        """Show exact before/after configuration and its hash; write nothing."""
        plan = preview(Workspace(workspace))
        checksum = digest(canonical(plan))
        lines = [
            "Workspace schema 1 -> 2; record schema remains 1.",
            "Sources, human notes, canonical records, and evidence remain unchanged.",
            "Policy revision advances; regenerate pending proposals and approvals.",
            f"Preview SHA256: {checksum}",
            "JSON field diff below; --json includes the exact before/after bytes.",
        ]
        for path, before, after in (
            ("workspace.json", plan.before_config, plan.after_config),
            ("policy/workspace.json", plan.before_policy, plan.after_policy),
        ):
            lines.extend(
                difflib.unified_diff(
                    json.dumps(json.loads(before), indent=2, sort_keys=True).splitlines(),
                    json.dumps(json.loads(after), indent=2, sort_keys=True).splitlines(),
                    fromfile=f"before/{path}",
                    tofile=f"after/{path}",
                    lineterm="",
                )
            )
        emit({"sha256": checksum, "plan": plan}, json_output, "\n".join(lines))

    @schema.command("apply")
    @guarded
    def apply_command(
        workspace: WorkspaceOption,
        plan_sha256: Annotated[str, typer.Option()],
        backup: Annotated[Path, typer.Option()],
        statement: Annotated[str, typer.Option()],
        json_output: JsonOption = False,
    ) -> None:
        from cairn.cli.commands import owner_confirm

        ws = Workspace(workspace)
        owner_confirm(ws, "migrate", f"Apply schema migration plan {plan_sha256}.")
        emit(
            apply(
                ws,
                plan_sha256=plan_sha256,
                backup_path=backup,
                statement=statement,
            ),
            json_output,
        )

    @schema.command("recover")
    @guarded
    def recover_command(workspace: WorkspaceOption, json_output: JsonOption = False) -> None:
        emit(recover(Workspace(workspace)), json_output)
