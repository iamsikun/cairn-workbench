from __future__ import annotations

import functools
import json
import sqlite3
import unicodedata
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any

import typer
from pydantic import ValidationError

from cairn.errors import CairnError
from cairn.ingest.service import capture as capture_source
from cairn.proposals.service import approve as approve_proposal
from cairn.proposals.service import ingest as ingest_source
from cairn.proposals.service import load_proposal
from cairn.proposals.service import validate as validate_proposal
from cairn.records.models import canonical
from cairn.retrieval.search import query as run_query
from cairn.retrieval.search import rebuild_index as rebuild
from cairn.retrieval.search import search as run_search
from cairn.storage.workspace import Workspace
from cairn.transactions.apply import apply as apply_proposal
from cairn.transactions.apply import recover as recover_workspace

WorkspaceOption = Annotated[Path, typer.Option("--workspace", "-w", envvar="CAIRN_WORKSPACE")]
JsonOption = Annotated[bool, typer.Option("--json", help="Emit structured JSON.")]


def guarded[**P, R](function: Callable[P, R]) -> Callable[P, R]:
    @functools.wraps(function)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return function(*args, **kwargs)
        except CairnError as exc:
            typer.echo(json.dumps({"error": exc.code, "message": str(exc)}), err=True)
            raise typer.Exit(exc.exit_status) from exc
        except (ValidationError, OSError, ValueError) as exc:
            # Validation errors can contain source text, secrets, and full paths.
            typer.echo(
                json.dumps({"error": "invalid", "message": "Invalid data or inaccessible file."}),
                err=True,
            )
            raise typer.Exit(2) from exc

    return wrapper


def emit(value: Any, as_json: bool, text: str | None = None) -> None:
    if as_json or text is None:
        typer.echo(json.dumps(json.loads(canonical(value)), ensure_ascii=True, sort_keys=True))
    else:
        typer.echo(
            "".join(
                character
                if character in "\n\t" or unicodedata.category(character) != "Cc"
                else f"\\u{ord(character):04x}"
                for character in text
            )
        )


def register(app: typer.Typer) -> None:
    proposals = typer.Typer(help="Inspect sealed proposals.")
    app.add_typer(proposals, name="proposal")
    clients = typer.Typer(help="Run a scoped packet through a pinned local client image.")
    app.add_typer(clients, name="client")

    @clients.command("run")
    @guarded
    def client_run(
        source_id: str,
        workspace: WorkspaceOption,
        image: Annotated[str, typer.Option()],
        scope: str = "owner",
        provider: str = "fake-v1",
        inline_synthetic: bool = False,
        json_output: JsonOption = False,
    ) -> None:
        from cairn.adapters.isolation import ClientPacketProvider
        from cairn.ingest.service import extract
        from cairn.proposals.service import prepare_job, stage_result

        ws = Workspace(workspace)
        extract(ws, source_id, scope_name=scope, inline_synthetic=inline_synthetic)
        envelope = prepare_job(
            ws, source_id, scope_name=scope, provider=provider, execution_image=image
        )
        result = ClientPacketProvider(image).generate(envelope.job)
        staged = stage_result(ws, result)
        emit(staged or {"status": "unchanged"}, json_output)

    @app.command("edit")
    @guarded
    def edit_command(
        record_id: str,
        workspace: WorkspaceOption,
        from_file: Annotated[Path | None, typer.Option()] = None,
        base_hash: str | None = None,
        inline_synthetic: bool = False,
        json_output: JsonOption = False,
    ) -> None:
        """Stage an owner revision from an editor or a file with an explicit base hash."""
        import os
        import shlex
        import subprocess

        from cairn.errors import Blocked
        from cairn.records.models import digest, new_id
        from cairn.transactions.edit import edit_from_file

        ws = Workspace(workspace)
        if from_file is None:
            editor = os.environ.get("EDITOR")
            if not editor:
                raise Blocked("set EDITOR or supply --from-file and --base-hash")
            with ws.lock(write=True):
                path, _, _ = ws.record(record_id)
                original = ws.fs.read(path)
                base_hash = digest(original)
                staged_path = f"cache/edit/{new_id('edit')}.md"
                ws.fs.write(staged_path, original, exclusive=True)
            from_file = ws.root / staged_path
            completed = subprocess.run([*shlex.split(editor), str(from_file)], check=False)
            if completed.returncode:
                raise CairnError("editor exited without a successful staged revision")
        if base_hash is None:
            raise CairnError("--base-hash is required with --from-file")
        proposal = edit_from_file(
            ws, record_id, from_file, expected_hash=base_hash, inline_synthetic=inline_synthetic
        )
        emit(proposal or {"status": "unchanged"}, json_output)

    @app.command("backup")
    @guarded
    def backup_command(
        destination: Path, workspace: WorkspaceOption, json_output: JsonOption = False
    ) -> None:
        from cairn.storage.backup import backup

        emit(backup(Workspace(workspace), destination), json_output)

    @app.command("restore")
    @guarded
    def restore_command(
        archive: Path,
        destination: Annotated[Path, typer.Option()],
        code_root: Annotated[Path, typer.Option()],
        json_output: JsonOption = False,
    ) -> None:
        from cairn.storage.backup import restore

        ws = restore(archive, destination, code_roots=[code_root])
        emit({"workspace_id": ws.config.id, "restored": True}, json_output)

    @app.command()
    @guarded
    def capture(
        file: Path,
        workspace: WorkspaceOption,
        domain: Annotated[str, typer.Option()],
        title: str | None = None,
        identity: str | None = None,
        version: str | None = None,
        classification: str = "private",
        json_output: JsonOption = False,
    ) -> None:
        """Preserve a selected source and its provenance."""
        from cairn.records.models import Labels

        labels = Labels.model_validate({"domain": domain, "classification": classification})
        result = capture_source(
            Workspace(workspace),
            file,
            domain=labels.domain,
            title=title,
            identity=identity,
            version=version,
            classification=labels.classification,
        )
        emit(result, json_output, f"Captured {result.id}: {result.title}")

    @app.command()
    @guarded
    def ingest(
        source_id: str,
        workspace: WorkspaceOption,
        scope: str = "owner",
        related: Annotated[list[str] | None, typer.Option()] = None,
        inline_synthetic: bool = False,
        json_output: JsonOption = False,
    ) -> None:
        """Extract locally and stage a bounded proposal; never apply automatically."""
        result = ingest_source(
            Workspace(workspace),
            source_id,
            scope_name=scope,
            related_ids=related,
            inline_synthetic=inline_synthetic,
        )
        emit(
            result or {"status": "unchanged"},
            json_output,
            f"Proposed {result.id}; review and validate before approval."
            if result
            else "Unchanged; no proposal needed.",
        )

    @proposals.command("show")
    @guarded
    def proposal_show(
        proposal_id: str, workspace: WorkspaceOption, json_output: JsonOption = False
    ) -> None:
        """Show exact candidate diffs and required owner review."""
        ws = Workspace(workspace)
        with ws.lock():
            proposal = load_proposal(ws, proposal_id)
        text = (
            f"{proposal.id}\nProvider: {proposal.provider}; route: {proposal.route}\n"
            f"Required review: {', '.join(sorted(proposal.review_flags))}\n"
            "Quote matches establish presence, not entailment. Reviewed does not mean true.\n"
        )
        text += "\n".join(change.diff for change in proposal.changes)
        emit(proposal, json_output, text)

    @app.command("validate")
    @guarded
    def validate_command(
        proposal_id: str, workspace: WorkspaceOption, json_output: JsonOption = False
    ) -> None:
        result = validate_proposal(Workspace(workspace), proposal_id)
        emit(
            {"proposal_id": result.id, "status": "validated", "review_flags": result.review_flags},
            json_output,
            f"Validated {result.id}; owner review remains required.",
        )

    @app.command("approve")
    @guarded
    def approve_command(
        proposal_id: str,
        workspace: WorkspaceOption,
        acknowledge: Annotated[list[str], typer.Option()],
        statement: Annotated[str, typer.Option()],
        json_output: JsonOption = False,
    ) -> None:
        """Owner-only approval, bound to the exact proposal and policy."""
        result = approve_proposal(
            Workspace(workspace),
            proposal_id,
            acknowledgements=set(acknowledge),
            statement=statement,
        )
        emit(result, json_output, f"Owner approval recorded for {proposal_id}.")

    @app.command("apply")
    @guarded
    def apply_command(
        proposal_id: str, workspace: WorkspaceOption, json_output: JsonOption = False
    ) -> None:
        """Apply a sealed owner approval through the recoverable single writer."""
        result = apply_proposal(Workspace(workspace), proposal_id)
        emit(result, json_output, f"Applied {proposal_id}; receipt {result.id}.")

    @app.command("recover")
    @guarded
    def recover_command(workspace: WorkspaceOption, json_output: JsonOption = False) -> None:
        result = recover_workspace(Workspace(workspace))
        emit(result, json_output, f"Recovered {len(result)} incomplete transaction(s).")

    @app.command("search")
    @guarded
    def search_command(
        query: str,
        workspace: WorkspaceOption,
        scope: Annotated[str, typer.Option()],
        limit: int = 10,
        json_output: JsonOption = False,
    ) -> None:
        hits = run_search(Workspace(workspace), query, scope_name=scope, limit=limit)
        text = (
            "\n\n".join(
                f"[{hit.kind}] {hit.title}\n{hit.id}; {hit.locator}\n{hit.text}" for hit in hits
            )
            or "No matching authorized evidence or synthesis."
        )
        emit(hits, json_output, text)

    @app.command("query")
    @guarded
    def query_command(
        question: str,
        workspace: WorkspaceOption,
        scope: Annotated[str, typer.Option()],
        json_output: JsonOption = False,
    ) -> None:
        result = run_query(Workspace(workspace), question, scope_name=scope)
        text = result["answer"] or "Insufficient evidence in this scope."
        emit(
            result,
            json_output,
            f"{text}\n\nExtractive result; review the evidence and its coverage.",
        )

    @app.command("rebuild-index")
    @guarded
    def rebuild_command(
        workspace: WorkspaceOption, scope: str = "owner", json_output: JsonOption = False
    ) -> None:
        count = rebuild(Workspace(workspace), scope)
        emit(
            {"indexed_rows": count, "scope": scope},
            json_output,
            f"Rebuilt {scope} index with {count} authorized rows.",
        )

    @app.command("doctor")
    @guarded
    def doctor(workspace: WorkspaceOption, json_output: JsonOption = False) -> None:
        ws = Workspace(workspace)
        with ws.lock():
            db = sqlite3.connect(":memory:")
            try:
                db.execute("CREATE VIRTUAL TABLE check_fts USING fts5(text, tokenize='trigram')")
                fts = True
            except sqlite3.OperationalError:
                fts = False
            finally:
                db.close()
        report = {
            "synthetic": ws.config.synthetic,
            "fts5": fts,
            "worker_image": ws.config.worker_image,
            "private_ready": False,
            "limitations": [
                "Private release activation is not implemented yet.",
                "A configured image is not proof of isolation or model capability.",
            ],
        }
        emit(report, json_output)

    @app.command("lint")
    @guarded
    def lint(
        workspace: WorkspaceOption, scope: str = "owner", json_output: JsonOption = False
    ) -> None:
        from cairn.proposals.service import all_refs, check_reference

        ws = Workspace(workspace)
        with ws.lock():
            records = ws.records(ws.policy.scope(scope))
            for _, record, _ in records:
                for ref in all_refs(record):
                    check_reference(ws, ref, scope)
        emit(
            {"status": "valid", "records": len(records)},
            json_output,
            f"Validated {len(records)} scoped records and their evidence references.",
        )
