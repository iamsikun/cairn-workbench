from pathlib import Path
from typing import Annotated, Any

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
    worker = typer.Typer(help="Explicitly enrolled owner-device inference routes.")
    library.add_typer(worker, name="worker")
    feeds = typer.Typer(help="Saved journal digests and bounded feed access.")
    app.add_typer(feeds, name="feed")

    @library.command("update")
    @guarded
    def update(
        workspace: WorkspaceOption,
        device: str | None = None,
        scope: str = "research",
        page_budget: int = 100,
        read_budget: int = 10,
    ) -> None:
        from cairn.library.update import update as run

        emit(
            run(
                Workspace(workspace),
                device_id=device,
                scope=scope,
                page_budget=page_budget,
                read_budget=read_budget,
            ),
            True,
        )

    @feeds.command("latest")
    @guarded
    def feed_latest(
        workspace: WorkspaceOption, scope: str = "research", json_output: JsonOption = False
    ) -> None:
        from cairn.library.feed import history, render

        values = history(Workspace(workspace), scope, 1)
        emit(
            values[0] if values else {"status": "no_digest"},
            json_output,
            render(values[0], "md") if values else "No digest yet.",
        )

    @feeds.command("history")
    @guarded
    def feed_history(workspace: WorkspaceOption, scope: str = "research", limit: int = 20) -> None:
        from cairn.library.feed import history

        emit(history(Workspace(workspace), scope, limit), True)

    @feeds.command("export")
    @guarded
    def feed_export(
        output: Path,
        workspace: WorkspaceOption,
        scope: str = "research",
        format: str = "atom",
        save_view: bool = False,
        feedback: bool = False,
        inline_synthetic: bool = False,
    ) -> None:
        from cairn.errors import Blocked
        from cairn.library.feed import history, render

        if format == "html":
            from cairn.presentation.cli_support import html_output

            html_output(
                Workspace(workspace),
                "feed",
                format=format,
                output=output,
                scope=scope,
                save=save_view,
                feedback=feedback,
                inline_synthetic=inline_synthetic,
            )
            return
        values = history(Workspace(workspace), scope, 1)
        if not values:
            raise Blocked("no_saved_digest")
        output.write_text(render(values[0], format))
        emit({"path": str(output), "digest": values[0].id}, True)

    @feeds.command("acknowledge")
    @guarded
    def feed_acknowledge(
        digest_id: str, workspace: WorkspaceOption, scope: str = "research"
    ) -> None:
        from cairn.library.feed import acknowledge

        acknowledge(Workspace(workspace), digest_id, scope)
        emit({"digest": digest_id, "notification": "acknowledged"}, True)

    @worker.command("enroll")
    @guarded
    def enroll(file: Path, workspace: WorkspaceOption) -> None:
        from cairn.ingest.service import read_source_file
        from cairn.library.device import enroll as run
        from cairn.library.reader_models import DeviceConfig

        emit(
            run(Workspace(workspace), DeviceConfig.model_validate_json(read_source_file(file))),
            True,
        )

    @worker.command("probe")
    @guarded
    def probe(device_id: str, workspace: WorkspaceOption) -> None:
        from cairn.library.device import enroll, load_device

        ws = Workspace(workspace)
        emit(enroll(ws, load_device(ws, device_id)), True)

    @worker.command("revoke")
    @guarded
    def revoke(device_id: str, workspace: WorkspaceOption) -> None:
        from cairn.library.device import revoke as run

        run(Workspace(workspace), device_id)
        emit({"device": device_id, "enrolled": False}, True)

    @library.command("capture")
    @guarded
    def capture(paper_id: str, workspace: WorkspaceOption, scope: str = "research") -> None:
        from cairn.library.reader import capture_paper

        emit(capture_paper(Workspace(workspace), paper_id, scope), True)

    @library.command("read")
    @guarded
    def read(
        paper_id: str,
        device: str,
        workspace: WorkspaceOption,
        scope: str = "research",
        queue_only: bool = False,
        revision: int = 1,
    ) -> None:
        from cairn.library.reader import enqueue, run

        ws = Workspace(workspace)
        state = enqueue(ws, paper_id, device, scope=scope, revision=revision)
        emit(state if queue_only else run(ws, state.job.id), True)

    @library.command("jobs")
    @guarded
    def jobs(workspace: WorkspaceOption, scope: str = "research") -> None:
        from cairn.library.reader import jobs as run

        emit(run(Workspace(workspace), scope), True)

    @library.command("retry")
    @guarded
    def retry(job_id: str, workspace: WorkspaceOption) -> None:
        from cairn.library.reader import run

        emit(run(Workspace(workspace), job_id, retry=True), True)

    @library.command("cancel")
    @guarded
    def cancel(job_id: str, workspace: WorkspaceOption) -> None:
        from cairn.library.reader import cancel as run

        emit(run(Workspace(workspace), job_id), True)

    @library.command("verification-configure")
    @guarded
    def verification_configure(file: Path, workspace: WorkspaceOption) -> None:
        from cairn.ingest.service import read_source_file
        from cairn.library.verification import configure
        from cairn.library.verification_models import VerificationConfig

        configure(
            Workspace(workspace), VerificationConfig.model_validate_json(read_source_file(file))
        )
        emit({"verification": "configured", "billing": "subscription_only"}, True)

    @library.command("verify")
    @guarded
    def verify(workspace: WorkspaceOption, scope: str = "research") -> None:
        from cairn.library.verification import verify as run

        emit(run(Workspace(workspace), scope), True)

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
    def journals(
        workspace: WorkspaceOption, scope: str = "research", json_output: JsonOption = False
    ) -> None:
        ws = Workspace(workspace)
        rows = papers(ws, scope=scope)
        values: list[dict[str, Any]] = []
        for journal in catalog.list_entities(ws, scope, "journal"):
            items = [row for row in rows if journal.id in row["metadata"]["journal_ids"]]
            with_pdf = sum(
                any(f["availability"] == "available" for f in row["metadata"]["files"])
                for row in items
            )
            values.append(
                {
                    "journal": journal,
                    "papers": len(items),
                    "with_pdf": with_pdf,
                    "metadata_only": len(items) - with_pdf,
                }
            )
        emit(
            values,
            json_output,
            "\n".join(
                f"{item['journal'].id}  {item['journal'].title}: {item['papers']} papers; "
                f"{item['with_pdf']} PDFs"
                for item in values
            ),
        )

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
        analysis: str | None = None,
        review: str | None = None,
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
            analysis=analysis,
            review=review,
        )
        emit(rows, json_output, "\n".join(f"{r['id']}  {r['title']}" for r in rows))

    @library.command("show")
    @guarded
    def show(
        paper_id: str,
        workspace: WorkspaceOption,
        scope: str = "research",
        format: str | None = None,
        output: Path | None = None,
        save_view: bool = False,
        feedback: bool = False,
        inline_synthetic: bool = False,
    ) -> None:
        from cairn.presentation.cli_support import html_output

        ws = Workspace(workspace)
        if html_output(
            ws,
            "paper",
            format=format,
            output=output,
            scope=scope,
            object_id=paper_id,
            save=save_view,
            feedback=feedback,
            inline_synthetic=inline_synthetic,
        ):
            return
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
        save_view: bool = False,
        feedback: bool = False,
        inline_synthetic: bool = False,
    ) -> None:
        from cairn.records.models import canonical

        if format == "html":
            from cairn.presentation.cli_support import html_output

            html_output(
                Workspace(workspace),
                "catalog",
                format=format,
                output=output,
                scope=scope,
                save=save_view,
                feedback=feedback,
                inline_synthetic=inline_synthetic,
            )
            return
        rows = papers(Workspace(workspace), scope=scope)
        if format not in ("html", "json"):
            raise ValueError("unsupported format")
        output.write_bytes(render_catalog(rows).encode() if format == "html" else canonical(rows))
        emit({"path": str(output), "papers": len(rows)}, True)
