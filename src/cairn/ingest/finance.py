from __future__ import annotations

from decimal import Decimal, DecimalException, Inexact, localcontext
from pathlib import Path
from typing import Literal

from cairn.adapters.protocol import Candidate, Result
from cairn.errors import CairnError, Denied
from cairn.ingest.service import capture_bytes, extract, load_extraction, read_source_file
from cairn.proposals.models import Proposal
from cairn.proposals.service import prepare_job, stage_result
from cairn.records.domains import Calculation, FinancialSnapshot, ObservedValue
from cairn.records.json import read_json
from cairn.records.models import (
    Assertion,
    EvidenceRef,
    Money,
    Period,
    Record,
    canonical,
    digest,
)
from cairn.storage.workspace import Workspace


def value_text(value: ObservedValue) -> str:
    return f"{value.label}: {value.value} {value.unit}" + (
        f" ({value.currency})" if value.currency else ""
    )


def observed_money(ws: Workspace, source_id: str, key: str, *, scope_name: str) -> Money:
    _, source, _ = ws.record(source_id, ws.policy.scope(scope_name))
    if not source.source or source.source.source_type != "finance_snapshot":
        raise Denied("calculations require preserved structured financial source values")
    extraction, evidence_hash = load_extraction(ws, source)
    snapshot = FinancialSnapshot.model_validate(read_json(ws.fs.read(source.source.blob)))
    matches = [value for value in snapshot.values if value.key == key]
    if len(matches) != 1:
        raise CairnError("financial value key unavailable")
    value = matches[0]
    locator = f"value {key}"
    if not any(segment.locator == locator for segment in extraction.segments):
        raise CairnError("financial value lacks an extracted locator")
    return Money(
        value=value.value,
        unit=value.unit,
        currency=value.currency,
        as_of=snapshot.as_of,
        owner_alias=snapshot.owner_alias,
        account_alias=snapshot.account_alias,
        sources=[
            EvidenceRef(
                id=source.id,
                source_hash=extraction.source_hash,
                evidence_hash=evidence_hash,
                locator=locator,
            )
        ],
    )


def check_observed_money(ws: Workspace, amount: Money, *, scope_name: str) -> None:
    for ref in amount.sources:
        if not ref.locator.startswith("value "):
            continue
        expected = observed_money(
            ws, ref.id, ref.locator.removeprefix("value "), scope_name=scope_name
        )
        if (
            amount.value == expected.value
            and amount.unit == expected.unit
            and amount.currency == expected.currency
            and amount.as_of == expected.as_of
            and amount.owner_alias == expected.owner_alias
            and amount.account_alias == expected.account_alias
            and ref.source_hash == expected.sources[0].source_hash
            and ref.evidence_hash == expected.sources[0].evidence_hash
        ):
            return
    raise CairnError("structured amount is not an exact preserved financial observation")


def calculate(operands: list[Money], operation: Literal["sum", "difference"]) -> Calculation:
    if not operands or len(operands) > 10000 or (operation == "difference" and len(operands) != 2):
        raise CairnError("sum needs values; difference needs exactly two values")
    if operation not in ("sum", "difference"):
        raise CairnError("unsupported deterministic calculation")
    first = operands[0]
    if not first.owner_alias or not first.account_alias:
        raise CairnError("financial calculations require explicit owner and account aliases")
    if any(
        (item.unit, item.currency, item.as_of, item.owner_alias, item.account_alias)
        != (first.unit, first.currency, first.as_of, first.owner_alias, first.account_alias)
        for item in operands
    ):
        raise Denied("calculation cannot mix owners, accounts, dates, units, or currencies")
    refs = [ref for operand in operands for ref in operand.sources]
    if len({(r.id, r.locator) for r in refs}) != len(refs):
        raise CairnError("calculation contains duplicate source values")
    try:
        with localcontext() as context:
            context.prec = 80
            context.traps[Inexact] = True
            value = (
                sum((item.value for item in operands), Decimal("0"))
                if operation == "sum"
                else operands[0].value - operands[1].value
            )
    except DecimalException as exc:
        raise CairnError("calculation exceeds supported exact precision") from exc
    result = Money(
        value=value,
        unit=first.unit,
        currency=first.currency,
        as_of=first.as_of,
        owner_alias=first.owner_alias,
        account_alias=first.account_alias,
        sources=refs,
    )
    return Calculation(operation=operation, operands=operands, result=result)


def calculate_source(
    ws: Workspace,
    source_id: str,
    keys: list[str],
    *,
    scope_name: str,
    operation: Literal["sum", "difference"],
) -> Calculation:
    with ws.lock():
        operands = [observed_money(ws, source_id, key, scope_name=scope_name) for key in keys]
        return calculate(operands, operation)


def import_snapshot(
    ws: Workspace, file: Path, *, scope_name: str, inline_synthetic: bool = False
) -> Proposal | None:
    data = read_source_file(file)
    snapshot = FinancialSnapshot.model_validate(read_json(data))
    period = Period(
        as_of=snapshot.as_of,
        statement_period=snapshot.statement_period,
        owner_alias=snapshot.owner_alias,
        account_alias=snapshot.account_alias,
    )
    title = f"Snapshot: {snapshot.owner_alias} / {snapshot.account_alias} / {snapshot.as_of}"
    source = capture_bytes(
        ws,
        data,
        origin=file.name,
        domain="finance",
        title=title,
        identity=f"financial-snapshot:{snapshot.owner_alias}:{snapshot.account_alias}:{snapshot.snapshot_id}",
        source_type="finance_snapshot",
        version="1",
        source_date=snapshot.as_of,
        period=period,
        scope_name=scope_name,
    )
    extract(ws, source.id, scope_name=scope_name, inline_synthetic=inline_synthetic)
    envelope = prepare_job(
        ws, source.id, scope_name=scope_name, related_ids=[], provider="financial-snapshot-v1"
    )
    job = envelope.job
    amounts = [
        observed_money(ws, source.id, value.key, scope_name=scope_name) for value in snapshot.values
    ]
    record = Record(
        id="entity_snapshot_" + source.id.removeprefix("source_"),
        type="entity",
        title=title,
        domain="finance",
        finance_category="account_snapshot",
        period=period,
        created_at=source.created_at,
        updated_at=source.created_at,
        sources=[ref for amount in amounts for ref in amount.sources],
        assertions=[
            Assertion(
                id="assert_" + digest(f"{source.id}:{value.key}".encode())[:32],
                text=value_text(value),
                kind="reported_result",
                sources=amount.sources,
                amounts=[amount],
                period=period,
            )
            for value, amount in zip(snapshot.values, amounts, strict=True)
        ],
    )
    return stage_result(
        ws,
        Result(
            job_id=job.id,
            input_hash=digest(canonical(job)),
            provider=job.provider,
            candidates=[
                Candidate(
                    record=record,
                    body="",
                    rationale="Copy exact source observations; no inferred balance or holding.",
                )
            ],
        ),
    )


def validate_snapshot_record(ws: Workspace, record: Record, body: str, *, scope_name: str) -> None:
    if body.strip() or record.sections:
        raise CairnError(
            "account snapshot commentary belongs in a separate sourced concept or decision"
        )
    if not record.assertions:
        raise CairnError("account snapshot requires source-grounded amounts")
    if (
        record.type != "entity"
        or record.period is None
        or record.title
        != (
            f"Snapshot: {record.period.owner_alias} / "
            f"{record.period.account_alias} / {record.period.as_of}"
        )
    ):
        raise CairnError("account snapshot identity must match its dated owner/account")
    for assertion in record.assertions:
        if assertion.kind != "reported_result" or len(assertion.amounts) != 1:
            raise CairnError("account snapshots contain exact observations only")
        amount = assertion.amounts[0]
        check_observed_money(ws, amount, scope_name=scope_name)
        if not record.period or (
            record.period.as_of,
            record.period.owner_alias,
            record.period.account_alias,
        ) != (amount.as_of, amount.owner_alias, amount.account_alias):
            raise CairnError("snapshot period/owner/account differs from source observation")
        ref = amount.sources[0]
        _, source, _ = ws.record(ref.id, ws.policy.scope(scope_name))
        assert source.source
        snapshot = FinancialSnapshot.model_validate(read_json(ws.fs.read(source.source.blob)))
        expected_period = Period(
            as_of=snapshot.as_of,
            statement_period=snapshot.statement_period,
            owner_alias=snapshot.owner_alias,
            account_alias=snapshot.account_alias,
        )
        if record.period != expected_period or assertion.period != expected_period:
            raise CairnError("snapshot period metadata differs from source")
        values = [value for value in snapshot.values if f"value {value.key}" == ref.locator]
        if len(values) != 1 or assertion.text != value_text(values[0]):
            raise CairnError("snapshot assertion differs from source observation")
