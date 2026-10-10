import json
from pathlib import Path
from typing import Annotated

import typer

from cairn.cli.commands import WorkspaceOption, emit, guarded
from cairn.errors import CairnError
from cairn.ingest.service import read_source_file
from cairn.presentation import quill
from cairn.presentation.writing import explanation_html, export_packet, import_explanation, prepare
from cairn.presentation.writing_models import NewTarget
from cairn.records.models import Labels
from cairn.storage.workspace import Workspace


def register(app: typer.Typer) -> None:
    write = typer.Typer(help="Tell the owner's agent what to write and where; stage its draft.")
    app.add_typer(write, name="write")

    @write.command("begin")
    @guarded
    def begin_command(
        workspace: WorkspaceOption,
        instructions: Annotated[str, typer.Option()],
        provider: Annotated[str, typer.Option()],
        destination: Annotated[str, typer.Option()],
        output: Annotated[Path, typer.Option()],
        target: Annotated[str | None, typer.Option(help="Existing page to revise.")] = None,
        new: Annotated[str | None, typer.Option(help="New record type to create.")] = None,
        domain: str = "research",
        title: str | None = None,
        from_ids: Annotated[list[str] | None, typer.Option("--from")] = None,
        feedback: str | None = None,
        view: Annotated[str | None, typer.Option(help="Explain a saved view instead.")] = None,
        scope: str = "research",
        shareable: Annotated[
            bool, typer.Option(help="Instructions may leave the device with the packet.")
        ] = False,
        request_labels: Path | None = None,
    ) -> None:
        """Seal one writing packet for Quill: instructions, target and scoped evidence."""
        ws = Workspace(workspace)
        labels = (
            Labels.model_validate_json(read_source_file(request_labels))
            if request_labels
            else Labels(domain=domain, classification="private", processing="cloud_eligible")  # type: ignore[arg-type]
            if shareable
            else None
        )
        if view is not None:
            if target or new or from_ids or feedback:
                raise CairnError("--view explains a saved view; it takes no target or evidence")
            job = prepare(
                ws,
                view,
                provider=provider,
                route="cloud",
                destination=destination,
                request=instructions,
                request_labels=labels,
            )
            emit(export_packet(ws, job.id, output) | {"next": "cairn write finish FILE"}, True)
            return
        if new is not None and target is not None:
            raise CairnError("choose --target or --new, not both")
        if new is None and target is None and feedback is None:
            raise CairnError("name a --target page or a --new record type")
        emit(
            quill.begin(
                ws,
                output,
                instructions=instructions,
                provider=provider,
                destination=destination,
                scope_name=scope,
                target_id=target,
                new=NewTarget.model_validate(
                    {"type": new, "domain": domain, "title": title or instructions[:120]}
                )
                if new
                else None,
                from_ids=from_ids,
                feedback_id=feedback,
                request_labels=labels,
            ),
            True,
        )

    @write.command("finish")
    @guarded
    def finish_command(
        file: Path,
        workspace: WorkspaceOption,
        output: Annotated[Path | None, typer.Option(help="HTML for an explanation.")] = None,
        inline_synthetic: bool = False,
    ) -> None:
        """Check and format Quill's response; stage a validated proposal (never applied)."""
        ws = Workspace(workspace)
        value = json.loads(read_source_file(file))
        if isinstance(value, dict) and "job_id" in value:
            response = import_explanation(ws, file)
            emit(
                explanation_html(ws, response, output, inline_synthetic=inline_synthetic)
                if output
                else {"job_id": response.job_id, "status": "generated_unreviewed"},
                True,
            )
            return
        receipt = quill.finish(ws, file, inline_synthetic=inline_synthetic)
        emit(
            receipt.model_dump(mode="json") | {"next": f"cairn accept {receipt.proposal_id}"}, True
        )
