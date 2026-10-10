from pathlib import Path

import typer

from cairn.cli.commands import WorkspaceOption, emit, guarded
from cairn.presentation.service import export_view, load_view, remember
from cairn.presentation.writing import import_feedback
from cairn.storage.workspace import Workspace


def register(app: typer.Typer) -> None:
    feedback = typer.Typer(help="Preserve view feedback; revise with `cairn write --feedback`.")
    views = typer.Typer(help="Inspect saved knowledge snapshots.")
    app.add_typer(feedback, name="feedback")
    app.add_typer(views, name="view")

    @views.command("show")
    @guarded
    def show(view_id: str, workspace: WorkspaceOption, historical: bool = False) -> None:
        emit(load_view(Workspace(workspace), view_id, historical=historical), True)

    @views.command("save")
    @guarded
    def save(view_id: str, workspace: WorkspaceOption) -> None:
        ws = Workspace(workspace)
        remember(ws, load_view(ws, view_id), save=True)
        emit({"bundle_id": view_id, "saved": True}, True)

    @views.command("render")
    @guarded
    def rerender(
        view_id: str,
        output: Path,
        workspace: WorkspaceOption,
        feedback: bool = False,
        inline_synthetic: bool = False,
    ) -> None:
        ws = Workspace(workspace)
        emit(
            export_view(
                ws,
                load_view(ws, view_id),
                output,
                feedback=feedback,
                inline_synthetic=inline_synthetic,
            ),
            True,
        )

    @feedback.command("import")
    @guarded
    def feedback_import(
        file: Path, workspace: WorkspaceOption, inline_synthetic: bool = False
    ) -> None:
        emit(import_feedback(Workspace(workspace), file, inline_synthetic=inline_synthetic), True)
