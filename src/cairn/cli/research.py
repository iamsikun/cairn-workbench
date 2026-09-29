from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from cairn.cli.commands import JsonOption, WorkspaceOption, emit, guarded
from cairn.ingest.bibliography import import_bibliography
from cairn.ingest.projects import create_project
from cairn.ingest.receipts import adopt_decision, import_receipt
from cairn.records.models import canonical
from cairn.retrieval.context import context_pack
from cairn.retrieval.repository import inspect_repository
from cairn.storage.workspace import Workspace


def register(app: typer.Typer) -> None:
    bibliography = typer.Typer(help="Read-only import of a selected CSL-JSON bibliography export.")
    app.add_typer(bibliography, name="bibliography")
    receipts = typer.Typer(help="Stage attributed session receipts for owner review.")
    app.add_typer(receipts, name="receipt")
    decisions = typer.Typer(help="Propose explicit owner adoption of an existing draft decision.")
    app.add_typer(decisions, name="decision")
    projects = typer.Typer(help="Stage owner project framing.")
    app.add_typer(projects, name="project")
    repositories = typer.Typer(
        help="Inspect an explicitly selected repository without running code."
    )
    app.add_typer(repositories, name="repository")

    @bibliography.command("import")
    @guarded
    def bibliography_import(
        file: Path,
        workspace: WorkspaceOption,
        library_alias: Annotated[str, typer.Option()],
        scope: Annotated[str, typer.Option()],
        project: str | None = None,
        json_output: JsonOption = False,
    ) -> None:
        emit(
            import_bibliography(
                Workspace(workspace),
                file,
                library_alias=library_alias,
                scope_name=scope,
                project_id=project,
            ),
            json_output,
        )

    @receipts.command("import")
    @guarded
    def receipt_import(
        file: Path,
        workspace: WorkspaceOption,
        scope: Annotated[str, typer.Option()],
        inline_synthetic: bool = False,
        json_output: JsonOption = False,
    ) -> None:
        result = import_receipt(
            Workspace(workspace), file, scope_name=scope, inline_synthetic=inline_synthetic
        )
        emit(result or {"status": "unchanged"}, json_output)

    @decisions.command("adopt")
    @guarded
    def decision_adopt(
        decision_id: str,
        workspace: WorkspaceOption,
        scope: Annotated[str, typer.Option()],
        statement: Annotated[str, typer.Option()],
        json_output: JsonOption = False,
    ) -> None:
        result = adopt_decision(
            Workspace(workspace), decision_id, scope_name=scope, statement=statement
        )
        emit(result or {"status": "unchanged"}, json_output)

    @projects.command("create")
    @guarded
    def project_create(
        title: str,
        workspace: WorkspaceOption,
        question: Annotated[str, typer.Option()],
        objective: Annotated[str, typer.Option()],
        constraints: Annotated[str, typer.Option()],
        scope: Annotated[str, typer.Option()],
        inline_synthetic: bool = False,
        json_output: JsonOption = False,
    ) -> None:
        emit(
            create_project(
                Workspace(workspace),
                title=title,
                question=question,
                objective=objective,
                constraints=constraints,
                scope_name=scope,
                inline_synthetic=inline_synthetic,
            ),
            json_output,
        )

    @repositories.command("inspect")
    @guarded
    def repository_inspect(
        root: Path,
        workspace: WorkspaceOption,
        alias: Annotated[str, typer.Option()],
        run_id: Annotated[list[str] | None, typer.Option()] = None,
        json_output: JsonOption = False,
    ) -> None:
        ws = Workspace(workspace)
        emit(
            inspect_repository(root, alias=alias, workspace_root=ws.root, run_ids=run_id),
            json_output,
        )

    @app.command("context")
    @guarded
    def context(
        project_id: str,
        workspace: WorkspaceOption,
        question: Annotated[str, typer.Option()],
        scope: Annotated[str, typer.Option()],
        budget: int = 8000,
        repository_root: Path | None = None,
        save: bool = False,
        json_output: JsonOption = False,
    ) -> None:
        ws = Workspace(workspace)
        result = context_pack(
            ws,
            project_id,
            question=question,
            budget=budget,
            scope_name=scope,
            repository_root=repository_root,
        )
        if save:
            with ws.lock(write=True):
                # Check that generation and saving refer to the same owner inputs.
                from cairn.errors import Conflict
                from cairn.records.models import digest

                if ws.policy_hash != result.policy_hash:
                    raise Conflict("policy changed while preparing context")
                for record_id, checksum in result.input_hashes.items():
                    path, _, _ = ws.record(record_id, ws.policy.scope(scope))
                    if digest(ws.fs.read(path)) != checksum:
                        raise Conflict("context input changed")
                ws.fs.write(f"receipts/context/{result.id}.json", canonical(result), exclusive=True)
        emit(result, json_output)
