from pathlib import Path
from typing import Annotated

import typer

from cairn.cli.commands import WorkspaceOption, emit, guarded
from cairn.errors import Denied
from cairn.ingest.service import capture, read_source_file
from cairn.reading.workflow import begin, finish
from cairn.records.models import Labels
from cairn.storage.workspace import Workspace


def register(app: typer.Typer) -> None:
    finch = typer.Typer(help="Sealed paper-reading packets for the owner's agent; proposals only.")
    app.add_typer(finch, name="finch")

    @finch.command("begin")
    @guarded
    def begin_command(
        source: str,
        output: Annotated[Path, typer.Option()],
        workspace: WorkspaceOption,
        provider: Annotated[str, typer.Option()],
        destination: Annotated[str, typer.Option()],
        scope: str = "research",
        request: str = "Read and explain the selected paper using Finch.",
        request_labels: Path | None = None,
        source_labels: Path | None = None,
        related: Annotated[list[str] | None, typer.Option()] = None,
        title: str | None = None,
        version: str | None = None,
        inline_synthetic: bool = False,
    ) -> None:
        ws = Workspace(workspace)
        if source.startswith("source_"):
            source_id = source
        else:
            labels = (
                Labels.model_validate_json(read_source_file(source_labels))
                if source_labels
                else Labels(domain="research")
            )
            if labels.domain != "research":
                raise Denied("paper source labels must use the research domain")
            source_id = capture(
                ws,
                Path(source),
                domain="research",
                title=title,
                version=version,
                classification=labels.classification,
                processing=labels.processing,
                compartments=labels.compartments,
                scope_name=scope,
            ).id
        question_labels = (
            Labels.model_validate_json(read_source_file(request_labels)) if request_labels else None
        )
        emit(
            begin(
                ws,
                source_id,
                output,
                scope_name=scope,
                request=request,
                request_labels=question_labels,
                provider=provider,
                destination=destination,
                related_ids=related,
                inline_synthetic=inline_synthetic,
            ),
            True,
        )

    @finch.command("finish")
    @guarded
    def finish_command(
        file: Path, workspace: WorkspaceOption, inline_synthetic: bool = False
    ) -> None:
        emit(finish(Workspace(workspace), file, inline_synthetic=inline_synthetic), True)
