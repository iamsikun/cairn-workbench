from pathlib import Path
from typing import Annotated

import typer

from cairn.cli.commands import JsonOption, WorkspaceOption, emit, guarded
from cairn.library import catalog
from cairn.library.index import papers, render_catalog
from cairn.library.models import Journal, LibraryConfig, ReadingState
from cairn.records.json import read_json
from cairn.storage.workspace import Workspace


def register(app: typer.Typer) -> None:
    library = typer.Typer(help="Journal inventory, reading progress, and paper jobs.")
    app.add_typer(library, name="library")

    @library.command("discover")
    @guarded
    def discover(
        workspace: WorkspaceOption, journal: str | None = None, page_budget: int = 100
    ) -> None:
        from cairn.library.discovery import discover as run

        emit(run(Workspace(workspace), journal_id=journal, page_budget=page_budget), True)

    @library.command("configure")
    @guarded
    def configure(root: Path, workspace: WorkspaceOption, scope: str = "research") -> None:
        emit(
            catalog.configure(Workspace(workspace), LibraryConfig(root=str(root), scope=scope)),
            True,
        )

    @library.command("route")
    @guarded
    def route(workspace: WorkspaceOption) -> None:
        ws = Workspace(workspace)
        with ws.lock():
            emit(catalog.config_unlocked(ws), True)

    @library.command("scan")
    @guarded
    def scan(
        workspace: WorkspaceOption,
        metadata: bool = True,
        rehash: bool = False,
        json_output: JsonOption = False,
    ) -> None:
        result = catalog.scan(Workspace(workspace), extract_metadata=metadata, rehash=rehash)
        emit(
            result,
            json_output,
            f"{len(result.added)} added; {len(result.changed)} changed; "
            f"{len(result.moved)} moved; {len(result.issues)} issues. Complete: {result.complete}",
        )

    @library.command("journal")
    @guarded
    def journal(title: str, file: Path, workspace: WorkspaceOption) -> None:
        from cairn.ingest.service import read_source_file

        emit(
            catalog.register_journal(
                Workspace(workspace),
                title,
                Journal.model_validate(read_json(read_source_file(file))),
            ),
            True,
        )

    @library.command("journals")
    @guarded
    def journals(workspace: WorkspaceOption, scope: str = "research") -> None:
        emit(catalog.list_entities(Workspace(workspace), scope, "journal"), True)

    @library.command("papers")
    @guarded
    def list_papers(
        workspace: WorkspaceOption,
        scope: str = "research",
        query: str = "",
        journal: str | None = None,
        year: int | None = None,
        reading: str | None = None,
        available: bool | None = None,
        json_output: JsonOption = False,
    ) -> None:
        rows = papers(
            Workspace(workspace),
            scope=scope,
            query=query,
            journal=journal,
            year=year,
            reading=reading,
            available=available,
        )
        emit(rows, json_output, "\n".join(f"{r['id']}  {r['title']}" for r in rows))

    @library.command("show")
    @guarded
    def show(paper_id: str, workspace: WorkspaceOption, scope: str = "research") -> None:
        ws = Workspace(workspace)
        with ws.lock():
            record, value = catalog.get_paper(ws, paper_id, scope)
            emit({"record": record, "paper": value}, True)

    @library.command("mark")
    @guarded
    def mark(
        paper_id: str,
        reading: str,
        workspace: WorkspaceOption,
        scope: str = "research",
    ) -> None:
        from pydantic import TypeAdapter

        value: ReadingState = TypeAdapter(ReadingState).validate_python(reading)
        emit(catalog.mark(Workspace(workspace), paper_id, value, scope=scope), True)

    @library.command("correct")
    @guarded
    def correct(
        paper_id: str, file: Path, workspace: WorkspaceOption, scope: str = "research"
    ) -> None:
        from cairn.ingest.service import read_source_file

        emit(
            catalog.correct(
                Workspace(workspace), paper_id, read_json(read_source_file(file)), scope=scope
            ),
            True,
        )

    @library.command("export")
    @guarded
    def export(
        workspace: WorkspaceOption,
        output: Annotated[Path, typer.Option()],
        scope: str = "research",
        format: str = "html",
    ) -> None:
        from cairn.records.models import canonical

        rows = papers(Workspace(workspace), scope=scope)
        if format not in ("html", "json"):
            raise ValueError("unsupported format")
        output.write_bytes(render_catalog(rows).encode() if format == "html" else canonical(rows))
        emit({"path": str(output), "papers": len(rows)}, True)
