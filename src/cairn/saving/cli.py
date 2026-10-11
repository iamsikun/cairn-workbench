"""Direct-save command line; legacy operations are explicitly separated."""

import base64
import json
from pathlib import Path
from typing import Annotated, Any, Literal, cast

import typer

from cairn.errors import CairnError
from cairn.records.models import Domain, canonical, digest
from cairn.saving.models import Capture, SaveNote, SaveReading, SourceInput
from cairn.saving.workspace import Book
from cairn.storage.files import RootFS

app = typer.Typer(no_args_is_help=True, help="Cairn: save readings and grow learning notebooks.")
presentation = typer.Typer(no_args_is_help=True)
app.add_typer(presentation, name="presentation")
WorkspacePath = Annotated[Path, typer.Option("--workspace", "-w")]


def output(value: Any) -> None:
    typer.echo(json.dumps(value, ensure_ascii=False, default=str))


def selected(value: str) -> Domain:
    if value not in ("research", "finance", "life", "shared"):
        raise CairnError("unknown collection")
    return cast(Domain, value)


@app.command()
def init(path: Path, synthetic: bool = False) -> None:
    book = Book.init(path, synthetic=synthetic)
    output({"workspace": str(book.root), "schema": 4, "collection": "research"})


@app.command()
def mcp(workspace: WorkspacePath, collection: str = "research") -> None:
    from cairn.saving.mcp import main

    main(Book(workspace), selected(collection))


@app.command("save-note")
def save_note(request: Path, workspace: WorkspacePath, collection: str = "research") -> None:
    from cairn.saving.service import save

    output(
        save(
            Book(workspace),
            selected(collection),
            SaveNote.model_validate_json(request.read_bytes()),
        )
    )


@app.command("save-reading")
def save_reading(request: Path, workspace: WorkspacePath, collection: str = "research") -> None:
    from cairn.saving.service import save

    output(
        save(
            Book(workspace),
            selected(collection),
            SaveReading.model_validate_json(request.read_bytes()),
        )
    )


@app.command()
def capture(
    material: str,
    workspace: WorkspacePath,
    collection: str = "research",
    operation_key: str | None = None,
    identity: str | None = None,
    title: str | None = None,
) -> None:
    from cairn.saving.service import save

    if material.startswith(("http://", "https://", "doi:", "10.")):
        source = SourceInput(
            identity=identity or material, title=title or material, origin=material
        )
        request = Capture(
            operation_key=operation_key or "capture-" + digest(canonical(source)), source=source
        )
    else:
        path = Path(material).absolute()
        raw = RootFS(path.parent).read(path.name, limit=16 * 1024 * 1024)
        if path.suffix.lower() == ".json":
            request = Capture.model_validate_json(raw)
        else:
            source = SourceInput(
                identity=identity or "sha256:" + digest(raw), title=title or path.name
            )
            if raw.startswith(b"%PDF-"):
                request = Capture(
                    operation_key=operation_key or "capture-" + digest(raw),
                    source=source,
                    pdf_base64=base64.b64encode(raw).decode(),
                )
            else:
                source.text = raw.decode()
                source.coverage = "full_text"
                request = Capture(
                    operation_key=operation_key or "capture-" + digest(canonical(source)),
                    source=source,
                )
    output(save(Book(workspace), selected(collection), request))


@app.command()
def search(
    query: str, workspace: WorkspacePath, collection: str = "research", limit: int = 20
) -> None:
    from cairn.saving.retrieval import search as find

    output(find(Book(workspace), selected(collection), query, limit))


@app.command("get-note")
def get_note(
    identity: str, workspace: WorkspacePath, collection: str = "research", html: bool = False
) -> None:
    from cairn.saving.retrieval import get_note as get

    book = Book(workspace)
    output(get(book, selected(collection), identity))
    if html:
        from cairn.saving.views import render

        output(render(book, selected(collection), identity))


@app.command("list-topics")
def list_topics(workspace: WorkspacePath, collection: str = "research") -> None:
    from cairn.saving.retrieval import list_topics as topics

    output(topics(Book(workspace), selected(collection)))


@app.command()
def recent(workspace: WorkspacePath, collection: str = "research", limit: int = 20) -> None:
    from cairn.saving.service import recent as history

    output(
        [r.model_dump(mode="json") for r in history(Book(workspace), selected(collection), limit)]
    )


@app.command()
def undo(
    revision: str, operation_key: str, workspace: WorkspacePath, collection: str = "research"
) -> None:
    from cairn.saving.service import undo as reverse

    output(reverse(Book(workspace), selected(collection), revision, operation_key))


@app.command()
def recover(workspace: WorkspacePath) -> None:
    from cairn.transactions.writer import recover as repair

    output(repair(Book(workspace)))


@app.command()
def connect(
    client: str,
    workspace: WorkspacePath,
    collection: str = "research",
    check: bool = False,
    repair: bool = False,
    disconnect: bool = False,
    settings_home: Path | None = None,
) -> None:
    from cairn.saving.connections import connection

    if client not in ("claude", "codex"):
        raise CairnError("client must be claude or codex")
    if sum((check, repair, disconnect)) > 1:
        raise CairnError("select one connection action")
    action: Literal["connect", "check", "repair", "disconnect"] = (
        "check" if check else "repair" if repair else "disconnect" if disconnect else "connect"
    )
    output(
        connection(
            settings_home or Path.home(),
            cast(Literal["claude", "codex"], client),
            Book(workspace),
            selected(collection),
            action,
        )
    )


@presentation.command()
def render(
    identity: str, workspace: WorkspacePath, collection: str = "research", snapshot: bool = False
) -> None:
    from cairn.saving.views import render as view

    output(view(Book(workspace), selected(collection), identity, snapshot=snapshot))


@presentation.command()
def feedback(request: Path, workspace: WorkspacePath, collection: str = "research") -> None:
    from cairn.saving.views import feedback as apply_feedback

    output(apply_feedback(Book(workspace), selected(collection), json.loads(request.read_bytes())))


@app.command()
def migrate(workspace: WorkspacePath, backup: Path, mapping: Path | None = None) -> None:
    from cairn.saving.migration import migrate as convert

    output(convert(workspace, backup, json.loads(mapping.read_bytes()) if mapping else None))


@app.command()
def backup(destination: Path, workspace: WorkspacePath) -> None:
    from cairn.saving.backup import backup as archive

    output(archive(Book(workspace), destination).model_dump(mode="json"))


@app.command()
def restore(archive: Path, destination: Path) -> None:
    from cairn.saving.backup import restore as unpack

    output(unpack(archive, destination))


@app.command("retire-installation")
def retire_installation(
    managed_home: Path, launcher: Path, python: Path, user_home: Path | None = None
) -> None:
    from cairn.saving.installation import retire

    output(retire(managed_home, user_home or Path.home(), launcher, python))
