from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Annotated, Literal

import typer

from cairn.cli.commands import JsonOption, WorkspaceOption, emit, guarded
from cairn.ingest.finance import calculate_source, import_snapshot
from cairn.ingest.life import import_dossier
from cairn.records.models import Period, canonical, digest
from cairn.storage.workspace import Workspace


def register(app: typer.Typer) -> None:
    finance = typer.Typer(help="Source-grounded snapshots and deterministic decimal calculations.")
    app.add_typer(finance, name="finance")
    life = typer.Typer(help="Dated entity documents and service history; no calendar actions.")
    app.add_typer(life, name="life")

    @finance.command("import")
    @guarded
    def finance_import(
        file: Path,
        workspace: WorkspaceOption,
        scope: Annotated[str, typer.Option()],
        inline_synthetic: bool = False,
        json_output: JsonOption = False,
    ) -> None:
        result = import_snapshot(
            Workspace(workspace), file, scope_name=scope, inline_synthetic=inline_synthetic
        )
        emit(result or {"status": "unchanged"}, json_output)

    @finance.command("calculate")
    @guarded
    def finance_calculate(
        source_id: str,
        workspace: WorkspaceOption,
        scope: Annotated[str, typer.Option()],
        key: Annotated[list[str], typer.Option()],
        operation: str = "sum",
        save: bool = False,
        json_output: JsonOption = False,
    ) -> None:
        from cairn.errors import CairnError

        if operation not in ("sum", "difference"):
            raise CairnError("supported calculations: sum, difference")
        selected: Literal["sum", "difference"] = "sum" if operation == "sum" else "difference"
        ws = Workspace(workspace)
        result = calculate_source(ws, source_id, key, scope_name=scope, operation=selected)
        if save:
            with ws.lock(write=True):
                from cairn.ingest.finance import check_observed_money

                for amount in result.operands:
                    check_observed_money(ws, amount, scope_name=scope)
                path = f"receipts/calculations/{digest(canonical(result))}.json"
                if not ws.fs.exists(path):
                    ws.fs.write(path, canonical(result), exclusive=True)
        emit(result, json_output)

    @finance.command("note")
    @guarded
    def finance_note(
        source_id: str,
        workspace: WorkspaceOption,
        scope: Annotated[str, typer.Option()],
        category: Annotated[str, typer.Option()],
        as_of: str | None = None,
        jurisdiction: str | None = None,
        tax_year: int | None = None,
        inline_synthetic: bool = False,
        json_output: JsonOption = False,
    ) -> None:
        from cairn.adapters.fake import FakeProvider
        from cairn.errors import CairnError, Denied
        from cairn.ingest.service import extract
        from cairn.proposals.service import prepare_job, stage_result

        if category not in ("educational", "official_rule"):
            raise CairnError("choose educational or official_rule; snapshots use finance import")
        period = Period(
            as_of=date.fromisoformat(as_of) if as_of else None,
            jurisdiction=jurisdiction,
            tax_year=tax_year,
        )
        if category == "official_rule" and not (period.as_of or period.tax_year):
            raise CairnError("official rules require --as-of or --tax-year")
        ws = Workspace(workspace)
        with ws.lock():
            _, source, _ = ws.record(source_id, ws.policy.scope(scope))
            if source.domain != "finance":
                raise Denied("financial notes require an explicitly finance-labeled source")
        extract(ws, source_id, scope_name=scope, inline_synthetic=inline_synthetic)
        envelope = prepare_job(ws, source_id, scope_name=scope, related_ids=[])
        # This deterministic rendering only copies exact source quotes. It is not a model call.
        result = FakeProvider().generate(envelope.job)
        for candidate in result.candidates:
            candidate.record.period = period
            candidate.record.finance_category = (
                "educational" if category == "educational" else "official_rule"
            )
        proposal = stage_result(ws, result)
        emit(proposal or {"status": "unchanged"}, json_output)

    @life.command("import")
    @guarded
    def life_import(
        file: Path,
        workspace: WorkspaceOption,
        scope: Annotated[str, typer.Option()],
        inline_synthetic: bool = False,
        json_output: JsonOption = False,
    ) -> None:
        result = import_dossier(
            Workspace(workspace), file, scope_name=scope, inline_synthetic=inline_synthetic
        )
        emit(result or {"status": "unchanged"}, json_output)
