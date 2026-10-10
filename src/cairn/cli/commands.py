from __future__ import annotations

import functools
import json
import os
import sqlite3
import sys
import unicodedata
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any

import typer
from pydantic import ValidationError

from cairn.errors import CairnError, Conflict, Denied
from cairn.ingest.notes import write_note
from cairn.ingest.service import capture as capture_source
from cairn.ingest.service import capture_bytes
from cairn.proposals.accept import DEFAULT_STATEMENT
from cairn.proposals.accept import accept as accept_items
from cairn.proposals.accept import plan as accept_plan
from cairn.proposals.inbox import inbox as build_inbox
from cairn.proposals.service import approve as approve_proposal
from cairn.proposals.service import ingest as ingest_source
from cairn.proposals.service import load_proposal
from cairn.proposals.service import validate as validate_proposal
from cairn.records.models import canonical
from cairn.records.runtime import ReviewAcknowledgement
from cairn.retrieval.search import query as run_query
from cairn.retrieval.search import rebuild_index as rebuild
from cairn.retrieval.search import search as run_search
from cairn.storage.files import MAX_FILE_BYTES
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


SYNTHETIC_OWNER = "CAIRN_SYNTHETIC_OWNER"


def _terminal() -> int:
    return os.open("/dev/tty", os.O_RDWR)


def owner_confirm(ws: Workspace, action: str, detail: str) -> None:
    """Owner commands are confirmed at the owner's own terminal, never by an agent's shell.

    Agent shells (Claude Code's, for one) run without a controlling terminal, so they
    cannot answer. A determined agent could allocate one; confining the agent with its
    sandbox is the real boundary (see `cairn mcp --print-config`). Synthetic workspaces
    accept `CAIRN_SYNTHETIC_OWNER=1` so tests and trials can run unattended.
    """
    if ws.config.synthetic and os.environ.get(SYNTHETIC_OWNER) == "1":
        return
    try:
        fd = _terminal()
    except OSError:
        raise Denied(
            f"`cairn {action}` is an owner command; run it yourself in a terminal"
        ) from None
    try:
        os.write(fd, f"{detail}\nType '{action}' to confirm: ".encode())
        typed = b""
        while not typed.endswith(b"\n") and len(typed) < 200:
            chunk = os.read(fd, 200)
            if not chunk:
                break
            typed += chunk
    finally:
        os.close(fd)
    answer = typed.decode(errors="replace").strip()
    if answer != action:
        raise Denied("owner declined")


def read_stdin() -> bytes:
    data = sys.stdin.buffer.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        raise CairnError("stdin exceeds capture limit")
    return data


def emit(value: Any, as_json: bool, text: str | None = None) -> None:
    if as_json or text is None:
        typer.echo(json.dumps(json.loads(canonical(value)), ensure_ascii=True, sort_keys=True))
    else:
        typer.echo(
            "".join(
                character
                if character in "\n\t" or unicodedata.category(character) not in ("Cc", "Cf")
                else f"\\u{ord(character):04x}"
                for character in text
            )
        )


def register(app: typer.Typer) -> None:
    proposals = typer.Typer(help="Inspect sealed proposals.")
    app.add_typer(proposals, name="proposal")

    @app.command("evidence")
    @guarded
    def evidence(
        source_id: str,
        workspace: WorkspaceOption,
        scope: Annotated[str, typer.Option()],
        locator: str | None = None,
        json_output: JsonOption = False,
        format: str | None = None,
        output: Path | None = None,
        save_view: bool = False,
        feedback: bool = False,
        inline_synthetic: bool = False,
    ) -> None:
        from cairn.presentation.cli_support import html_output

        if html_output(
            Workspace(workspace),
            "evidence",
            format=format,
            output=output,
            scope=scope,
            object_id=source_id,
            question=locator or "",
            save=save_view,
            feedback=feedback,
            inline_synthetic=inline_synthetic,
            conflicting=json_output,
        ):
            return
        from cairn.ingest.service import evidence_report

        ws = Workspace(workspace)
        path, report = evidence_report(ws, source_id, scope_name=scope, locator=locator)
        source, extraction = report["source"], report
        assert source.source
        text = (
            f"{source.title}\n{source.id}\nManifest: {ws.root / path}\n"
            f"Version: {source.source.version or 'unknown'}; "
            f"date: {source.source.source_date or 'unknown'}; coverage: {extraction['coverage']}\n"
            f"Source hash: {source.source.content_hash}\n"
            f"Evidence hash: {report['evidence_hash']}\n"
            + "\n\n".join(f"[{s.locator}] {s.text}" for s in report["segments"])
        )
        emit(report, json_output, text)

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
        destination: Path,
        workspace: WorkspaceOption,
        include_pending: bool = False,
        json_output: JsonOption = False,
    ) -> None:
        from cairn.storage.streaming_backup import backup

        emit(
            backup(Workspace(workspace), destination, include_pending=include_pending), json_output
        )

    @app.command("restore")
    @guarded
    def restore_command(
        archive: Path,
        destination: Annotated[Path, typer.Option()],
        code_root: Annotated[Path, typer.Option()],
        expected_sha256: str | None = None,
        synthetic: bool = False,
        release: Path | None = None,
        release_sha256: str | None = None,
        statement: str | None = None,
        acknowledge: Annotated[list[ReviewAcknowledgement] | None, typer.Option()] = None,
        json_output: JsonOption = False,
    ) -> None:
        """Restore a backup into a new workspace."""
        from cairn.storage.streaming_backup import restore

        ws = restore(
            archive,
            destination,
            code_roots=[code_root],
            expected_sha256=expected_sha256,
            synthetic=synthetic,
            release=release,
            release_sha256=release_sha256,
            statement=statement,
            acknowledgements=set(acknowledge) if acknowledge else None,
        )
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
        """Preserve a selected source and its provenance; FILE '-' reads stdin as text."""
        from cairn.records.models import Labels, digest

        labels = Labels.model_validate({"domain": domain, "classification": classification})
        if str(file) == "-":
            data = read_stdin()
            result = capture_bytes(
                Workspace(workspace),
                data,
                origin="stdin",
                domain=labels.domain,
                title=title or "Captured text",
                identity=identity or f"stdin:{digest(data)[:32]}",
                source_type="text",
                version=version,
                classification=labels.classification,
            )
        else:
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
    def note(
        text: str,
        workspace: WorkspaceOption,
        title: str | None = None,
        domain: str = "shared",
        classification: str = "private",
        json_output: JsonOption = False,
    ) -> None:
        """Write your own note to the inbox; TEXT '-' reads stdin. Searchable immediately."""
        from cairn.records.models import Labels

        labels = Labels.model_validate({"domain": domain, "classification": classification})
        body = read_stdin().decode("utf-8") if text == "-" else text
        result = write_note(
            Workspace(workspace),
            body,
            title=title,
            domain=labels.domain,
            classification=labels.classification,
        )
        emit(
            {"path": result.path, "title": result.title, "sha256": result.sha256},
            json_output,
            f"Noted {result.path}",
        )

    @app.command("inbox")
    @guarded
    def inbox_command(workspace: WorkspaceOption, json_output: JsonOption = False) -> None:
        """Read-only triage of inbox notes and proposals awaiting acceptance."""
        result = build_inbox(Workspace(workspace))
        lines = [f"Notes ({len(result.notes)})"]
        lines += [
            f"  {n.path}: {n.title} [{n.domain}/{n.classification}]"
            + (f" captured as {n.captured_as}" if n.captured_as else "")
            for n in result.notes
        ]
        lines.append(f"Proposals awaiting owner acceptance ({len(result.proposals)})")
        lines += [
            f"  {p.proposal_id} [{p.origin}] {', '.join(p.paths)}\n"
            f"    review: {', '.join(p.review_flags)}\n    next: {p.next}"
            for p in result.proposals
        ]
        emit(result, json_output, "\n".join(lines))

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
        proposal_id: str,
        workspace: WorkspaceOption,
        json_output: JsonOption = False,
        markdown: bool = False,
        format: str | None = None,
        output: Path | None = None,
        save_view: bool = False,
        feedback: bool = False,
        inline_synthetic: bool = False,
    ) -> None:
        """Show current diffs, source provenance and required owner review; optionally Markdown."""
        from cairn.presentation.cli_support import html_output

        if html_output(
            Workspace(workspace),
            "proposal",
            format=format,
            output=output,
            scope="owner",
            object_id=proposal_id,
            save=save_view,
            feedback=feedback,
            inline_synthetic=inline_synthetic,
            conflicting=json_output or markdown,
        ):
            return
        from cairn.proposals.review import render_review

        if json_output and markdown:
            raise CairnError("choose either --json or --markdown")
        ws = Workspace(workspace)
        with ws.lock():
            proposal = load_proposal(ws, proposal_id)
            text = render_review(ws, proposal, markdown=markdown)
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
        ws = Workspace(workspace)
        owner_confirm(ws, "approve", f"Approve {proposal_id}.")
        result = approve_proposal(
            ws,
            proposal_id,
            acknowledgements=set(acknowledge),
            statement=statement,
        )
        emit(result, json_output, f"Owner approval recorded for {proposal_id}.")

    @app.command("accept")
    @guarded
    def accept_command(
        workspace: WorkspaceOption,
        proposal_ids: Annotated[list[str] | None, typer.Argument()] = None,
        all_pending: Annotated[bool, typer.Option("--all")] = False,
        statement: str = DEFAULT_STATEMENT,
        json_output: JsonOption = False,
    ) -> None:
        """Owner-only: validate, approve and apply proposals in one confirmed step."""
        if bool(proposal_ids) == all_pending:
            raise CairnError("name proposal IDs or use --all")
        ws = Workspace(workspace)
        items = accept_plan(ws, None if all_pending else proposal_ids)
        ready = [item for item in items if item.status == "ready"]
        if not json_output:
            for item in items:
                emit(
                    item,
                    False,
                    f"[{item.status}] {item.proposal_id}: {'; '.join(item.titles)}\n"
                    f"    paths: {', '.join(item.paths)}\n"
                    f"    review: {', '.join(item.review_flags)}"
                    + (f"\n    reason: {item.reason}" if item.reason else ""),
                )
        if ready:
            from cairn.proposals.review import review_model
            from cairn.proposals.service import load_proposal

            for item in ready:
                report = review_model(ws, load_proposal(ws, item.proposal_id))
                for change in report.changes:
                    # Keep the actual diff available even with structured command output.
                    typer.echo(change.diff, err=json_output)
                typer.echo(
                    f"Evidence references: {len(report.references)}; "
                    f"review: {', '.join(report.review_flags)}",
                    err=json_output,
                )
            owner_confirm(
                ws,
                "accept",
                f"Accept {len(ready)} proposal(s), acknowledging the review flags shown.",
            )
        results = accept_items(ws, items, statement=statement)
        applied = sum(item.receipt_id is not None for item in results)
        emit(results, json_output, f"Applied {applied} of {len(ready)} ready proposal(s).")
        if any(item.status == "failed" for item in results):
            raise typer.Exit(Conflict.exit_status)

    @app.command("apply")
    @guarded
    def apply_command(
        proposal_id: str, workspace: WorkspaceOption, json_output: JsonOption = False
    ) -> None:
        """Apply a sealed owner approval through the recoverable single writer."""
        ws = Workspace(workspace)
        owner_confirm(ws, "apply", f"Apply {proposal_id}.")
        result = apply_proposal(ws, proposal_id)
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
        no_notes: Annotated[bool, typer.Option("--no-notes")] = False,
        json_output: JsonOption = False,
    ) -> None:
        """Search authorized evidence, synthesis and your own notes."""
        hits = run_search(
            Workspace(workspace), query, scope_name=scope, limit=limit, include_notes=not no_notes
        )
        text = (
            "\n\n".join(
                f"[{hit.kind}] {hit.title}\n{hit.id}; {hit.locator}\n"
                f"Date: {hit.source_date or 'unknown'}; "
                f"version: {hit.source_version or 'unknown'}; "
                f"coverage: {hit.coverage or hit.kind}; status: {hit.status}\n"
                f"Verification: {', '.join(hit.verification) or 'unreviewed'}\n"
                f"Applicability: {canonical(hit.period).decode().strip()}\n"
                f"Supersedes: {', '.join(hit.supersedes) or 'none recorded'}; "
                f"disputes: {', '.join(hit.disputes) or 'none recorded'}\n{hit.text}"
                for hit in hits
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
        question_labels: Path | None = None,
        format: str | None = None,
        output: Path | None = None,
        save_view: bool = False,
        feedback: bool = False,
        inline_synthetic: bool = False,
    ) -> None:
        from cairn.presentation.cli_support import html_output

        if html_output(
            Workspace(workspace),
            "query",
            format=format,
            output=output,
            scope=scope,
            question=question,
            save=save_view,
            feedback=feedback,
            inline_synthetic=inline_synthetic,
            conflicting=json_output,
            question_labels=question_labels,
        ):
            return
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
    def doctor(
        workspace: WorkspaceOption, json_output: JsonOption = False, probe_worker: bool = False
    ) -> None:
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
        from cairn.storage.activation import check_worker

        profile = None
        blocked = None
        if probe_worker:
            if ws.config.worker_image:
                try:
                    profile = check_worker(ws.config.worker_image)
                except (CairnError, ValueError, OSError) as exc:
                    blocked = str(exc) if isinstance(exc, CairnError) else "invalid_probe_result"
            else:
                blocked = "worker_image_unconfigured"
        report = {
            "synthetic": ws.config.synthetic,
            "fts5": fts,
            "worker_image": ws.config.worker_image,
            "runtime_verified": not ws.config.synthetic,
            "release_hash": ws.config.runtime_release_hash,
            "worker_profile": profile,
            "worker_probe_status": "passed" if profile else (blocked or "not_checked"),
            "private_ready": bool(not ws.config.synthetic and fts and profile),
            "model_capability": "worker extracts and renders; the owner's agent drafts",
            "limitations": [
                "Synthetic mode is not private-runtime activation.",
                "Readiness covers the checked runtime/profile, not model quality "
                "or universal security.",
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
