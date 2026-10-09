from pathlib import Path
from typing import Annotated

import typer

from cairn.cli.commands import WorkspaceOption, emit, guarded
from cairn.presentation.service import export_view, load_view, remember
from cairn.presentation.writing import (
    explanation_html,
    export_packet,
    import_explanation,
    import_feedback,
    prepare,
    prepare_feedback,
    stage_feedback,
)
from cairn.records.models import Labels
from cairn.storage.files import RootFS
from cairn.storage.workspace import Workspace


def register(app: typer.Typer) -> None:
    explanations = typer.Typer(help="Bounded Quill writing packets; no implicit model calls.")
    feedback = typer.Typer(help="Preserve view feedback and stage bounded revisions.")
    views = typer.Typer(help="Inspect saved knowledge snapshots.")
    app.add_typer(explanations, name="explanation")
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

    @explanations.command("prepare")
    @guarded
    def prepare_command(
        view_id: str,
        workspace: WorkspaceOption,
        provider: Annotated[str, typer.Option()],
        route: str = "local",
        destination: str = "local",
        request: str = "",
        request_labels: Path | None = None,
        technical: bool = True,
    ) -> None:
        labels = (
            Labels.model_validate_json(RootFS(request_labels.parent).read(request_labels.name))
            if request_labels
            else None
        )
        job = prepare(
            Workspace(workspace),
            view_id,
            provider=provider,
            route=route,
            destination=destination,
            request=request,
            request_labels=labels,
            technical=technical,
        )
        emit({"job_id": job.id, "route": job.route, "status": "prepared; not exported"}, True)

    @explanations.command("export")
    @guarded
    def export(job_id: str, output: Path, workspace: WorkspaceOption) -> None:
        emit(export_packet(Workspace(workspace), job_id, output), True)

    @explanations.command("import")
    @guarded
    def import_command(
        file: Path,
        workspace: WorkspaceOption,
        output: Path | None = None,
        inline_synthetic: bool = False,
    ) -> None:
        ws = Workspace(workspace)
        response = import_explanation(ws, file)
        emit(
            explanation_html(ws, response, output, inline_synthetic=inline_synthetic)
            if output
            else {"job_id": response.job_id, "status": "generated_unreviewed"},
            True,
        )

    @feedback.command("import")
    @guarded
    def feedback_import(
        file: Path, workspace: WorkspaceOption, inline_synthetic: bool = False
    ) -> None:
        emit(import_feedback(Workspace(workspace), file, inline_synthetic=inline_synthetic), True)

    @feedback.command("prepare")
    @guarded
    def feedback_prepare(
        feedback_id: str,
        workspace: WorkspaceOption,
        provider: Annotated[str, typer.Option()],
        route: str = "local",
        destination: str = "local",
    ) -> None:
        job = prepare_feedback(
            Workspace(workspace),
            feedback_id,
            provider=provider,
            route=route,
            destination=destination,
        )
        emit({"job_id": job.id, "status": "prepared; export with cairn explanation export"}, True)

    @feedback.command("stage")
    @guarded
    def feedback_stage(file: Path, workspace: WorkspaceOption) -> None:
        value = stage_feedback(Workspace(workspace), file)
        emit(value or {"status": "unchanged"}, True)
