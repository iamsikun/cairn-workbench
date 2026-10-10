from pathlib import Path
from typing import Annotated, Literal

import typer

from cairn.cli.commands import WorkspaceOption, emit, guarded
from cairn.presentation.service import export_view, load_view, remember
from cairn.presentation.writing import import_feedback
from cairn.storage.workspace import Workspace


def register(app: typer.Typer) -> None:
    feedback = typer.Typer(help="Preserve view feedback; your agent revises pages from it.")
    views = typer.Typer(help="Inspect saved knowledge snapshots.")
    app.add_typer(feedback, name="feedback")
    app.add_typer(views, name="view")

    @views.command("page")
    @guarded
    def page(
        record_id: str,
        workspace: WorkspaceOption,
        output: Annotated[Path, typer.Option()],
        format: Annotated[Literal["html"], typer.Option()],
        scope: str = "research",
        inline_synthetic: bool = False,
    ) -> None:
        """Explicitly render a Markdown page and track its future accepted updates."""
        from cairn.presentation.live import render_page

        emit(
            render_page(
                Workspace(workspace), record_id, scope, output, inline_synthetic=inline_synthetic
            ),
            True,
        )

    @views.command("sync")
    @guarded
    def sync_views(workspace: WorkspaceOption) -> None:
        """Refresh registered HTML, including Markdown edits made in an editor."""
        from cairn.presentation.live import sync

        emit(sync(Workspace(workspace)), True)

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

    @views.command("explanation")
    @guarded
    def explanation(
        job_id: str,
        output: Path,
        workspace: WorkspaceOption,
        digest: str | None = None,
        inline_synthetic: bool = False,
    ) -> None:
        """Render an agent's kept explanation of a view as unreviewed HTML."""
        from cairn.presentation.writing import explanation_html, stored_explanation

        ws = Workspace(workspace)
        response = stored_explanation(ws, job_id, digest)
        emit(explanation_html(ws, response, output, inline_synthetic=inline_synthetic), True)

    @feedback.command("import")
    @guarded
    def feedback_import(
        file: Path, workspace: WorkspaceOption, inline_synthetic: bool = False
    ) -> None:
        emit(import_feedback(Workspace(workspace), file, inline_synthetic=inline_synthetic), True)
