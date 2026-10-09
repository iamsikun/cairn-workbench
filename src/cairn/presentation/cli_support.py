from pathlib import Path

from cairn.errors import CairnError
from cairn.presentation.service import assemble, export_view
from cairn.storage.workspace import Workspace


def html_output(
    ws: Workspace,
    kind: str,
    *,
    format: str | None,
    output: Path | None,
    scope: str,
    object_id: str | None = None,
    question: str = "",
    budget: int = 8000,
    repository_root: Path | None = None,
    save: bool = False,
    feedback: bool = False,
    inline_synthetic: bool = False,
    conflicting: bool = False,
    question_labels: Path | None = None,
) -> bool:
    if format is None:
        if output is not None or feedback:
            raise CairnError("HTML destination and feedback require --format html")
        return False
    if format != "html" or output is None or conflicting:
        raise CairnError("use --format html --output PATH without --json or --markdown")
    from cairn.ingest.service import read_source_file
    from cairn.records.models import Labels

    labels = (
        Labels.model_validate_json(read_source_file(question_labels)) if question_labels else None
    )
    from cairn.cli.commands import emit

    bundle = assemble(
        ws,
        kind,
        scope=scope,
        object_id=object_id,
        question=question,
        budget=budget,
        repository_root=repository_root,
        question_labels=labels,
    )
    emit(
        export_view(
            ws, bundle, output, save=save, feedback=feedback, inline_synthetic=inline_synthetic
        ),
        True,
    )
    return True
