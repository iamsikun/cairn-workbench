import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from cairn.adapters.protocol import Candidate, Result
from cairn.cli import app
from cairn.errors import CairnError, Denied
from cairn.ingest.finance import calculate, calculate_source, import_snapshot
from cairn.ingest.life import import_dossier
from cairn.ingest.service import capture, extract
from cairn.proposals.models import Proposal
from cairn.proposals.service import approve, load_job, stage_result, validate
from cairn.records.domains import FinancialSnapshot, LifeDossier, LifeEvent, LifeTerm
from cairn.records.models import EvidenceRef, Money, canonical, digest
from cairn.storage.markdown import decode
from cairn.storage.workspace import Workspace
from cairn.transactions.apply import apply


def snapshot_file(tmp_path: Path) -> Path:
    data = {
        "schema_version": 1,
        "snapshot_id": "statement_demo",
        "owner_alias": "owner_alpha",
        "account_alias": "account_cash",
        "as_of": "2026-01-02",
        "statement_period": "2026-01-01/2026-01-02",
        "values": [
            {
                "key": "cash_available",
                "label": "Available cash",
                "measure": "balance",
                "value": "0.10",
                "unit": "money",
                "currency": "USD",
            },
            {
                "key": "cash_pending",
                "label": "Pending cash",
                "measure": "balance",
                "value": "0.20",
                "unit": "money",
                "currency": "USD",
            },
        ],
    }
    file = tmp_path / "statement.json"
    file.write_text(json.dumps(data, indent=2))
    return file


def accept(ws: Workspace, proposal: Proposal) -> None:
    approve(
        ws,
        proposal.id,
        acknowledgements=proposal.review_flags,
        statement="Synthetic owner has checked the source values and dates.",
    )
    apply(ws, proposal.id)


def test_finance_snapshot_and_exact_decimal_calculations(ws: Workspace, tmp_path: Path) -> None:
    file = snapshot_file(tmp_path)
    original = file.read_bytes()
    proposal = import_snapshot(ws, file, scope_name="finance", inline_synthetic=True)
    assert proposal and "sensitive_record" in proposal.review_flags
    assert not [r for _, r, _ in ws.records() if r.type == "entity"]
    accept(ws, proposal)
    _, record, body = ws.record(proposal.changes[0].id)
    assert record.finance_category == "account_snapshot" and body == ""
    assert record.period.owner_alias == "owner_alpha"
    assert record.assertions[0].amounts[0].value == Decimal("0.10")
    source_id = record.sources[0].id
    source = ws.record(source_id)[1]
    assert source.period.as_of == date(2026, 1, 2)
    assert ws.fs.read(source.source.blob) == original == file.read_bytes()
    result = calculate_source(
        ws, source_id, ["cash_available", "cash_pending"], scope_name="finance", operation="sum"
    )
    assert result.result.value == Decimal("0.30")
    assert '"value":"0.30"' in canonical(result).decode()
    assert result.result.sources[0].locator == "value cash_available"
    difference = calculate_source(
        ws,
        source_id,
        ["cash_pending", "cash_available"],
        scope_name="finance",
        operation="difference",
    )
    assert difference.result.value == Decimal("0.10")
    assert import_snapshot(ws, file, scope_name="finance", inline_synthetic=True) is None
    with pytest.raises(Denied):
        calculate_source(ws, source_id, ["cash_available"], scope_name="research", operation="sum")
    with pytest.raises(Denied, match="preserved structured"):
        calculate_source(ws, record.id, ["cash_available"], scope_name="finance", operation="sum")
    with pytest.raises(CairnError, match="duplicate"):
        calculate_source(
            ws,
            source_id,
            ["cash_available", "cash_available"],
            scope_name="finance",
            operation="sum",
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("owner_alias", "owner_beta"),
        ("account_alias", "account_other"),
        ("as_of", date(2026, 1, 3)),
        ("currency", "EUR"),
        ("unit", "shares"),
    ],
)
def test_calculation_rejects_cross_owner_account_date_currency_or_unit(
    field: str, value: object
) -> None:
    first = Money(
        value="0.10",
        unit="money",
        currency="USD",
        as_of=date(2026, 1, 2),
        owner_alias="owner_alpha",
        account_alias="account_cash",
        sources=[
            EvidenceRef(
                id="source_demo",
                source_hash="0" * 64,
                evidence_hash="1" * 64,
                locator="value cash_available",
            )
        ],
    )
    second = first.model_copy(deep=True)
    second.sources[0].locator = "value cash_pending"
    setattr(second, field, value)
    with pytest.raises(Denied, match="cannot mix"):
        calculate([first, second], "sum")


def test_snapshot_rejects_floats_and_ambiguous_keys_before_capture(
    ws: Workspace, tmp_path: Path
) -> None:
    file = snapshot_file(tmp_path)
    data = json.loads(file.read_bytes())
    data["values"][0]["value"] = 0.1
    file.write_text(json.dumps(data))
    with pytest.raises(ValidationError):
        import_snapshot(ws, file, scope_name="finance", inline_synthetic=True)
    assert ws.records() == []
    data["values"][0]["value"] = "0.10"
    data["values"][1]["key"] = data["values"][0]["key"]
    with pytest.raises(ValidationError):
        FinancialSnapshot.model_validate(data)


@pytest.mark.parametrize("tamper", ["amount", "owner", "prose", "body", "title", "period"])
def test_fabricated_financial_snapshot_values_rejected(
    ws: Workspace, tmp_path: Path, tamper: str
) -> None:
    proposal = import_snapshot(
        ws, snapshot_file(tmp_path), scope_name="finance", inline_synthetic=True
    )
    assert proposal
    job = load_job(ws, proposal.job_id).job
    record, body = decode(proposal.changes[0].content.encode())
    if tamper == "amount":
        record.assertions[0].amounts[0].value = Decimal("999999")
    elif tamper == "owner":
        record.assertions[0].amounts[0].owner_alias = "owner_someone_else"
    elif tamper == "prose":
        record.assertions[0].text = "Available cash: 999999 USD"
    elif tamper == "title":
        record.title = "Balance is 999999 USD"
    elif tamper == "period":
        record.assertions[0].period.statement_period = "2099-01"
    else:
        body = "The owner's balance is actually 999999 USD."
    staged = stage_result(
        ws,
        Result(
            job_id=job.id,
            input_hash=digest(canonical(job)),
            provider=job.provider,
            candidates=[
                Candidate(record=record, body=body, rationale="Hostile synthetic mutation")
            ],
        ),
    )
    assert staged
    with pytest.raises(CairnError):
        validate(ws, staged.id)
    assert not [r for _, r, _ in ws.records() if r.type == "entity"]


def test_finance_cli_dated_rules_and_snapshot_calculation(ws: Workspace, tmp_path: Path) -> None:
    file = tmp_path / "official-rule.txt"
    file.write_text("Synthetic 2024 policy: the demonstration allowance is 12 units.")
    source = capture(ws, file, domain="finance")
    runner = CliRunner()
    options = ["--workspace", str(ws.root), "--scope", "finance", "--json"]
    args = [
        "finance",
        "note",
        source.id,
        "--category",
        "official_rule",
        "--inline-synthetic",
        *options,
    ]
    assert runner.invoke(app, args).exit_code == 2
    result = runner.invoke(app, [*args, "--tax-year", "2024", "--jurisdiction", "Synthetic"])
    assert result.exit_code == 0, result.output
    proposal = Proposal.model_validate_json(result.stdout)
    accept(ws, proposal)
    rule = ws.record(proposal.changes[0].id)[1]
    assert rule.period.tax_year == 2024 and rule.finance_category == "official_rule"
    snapshot = import_snapshot(
        ws, snapshot_file(tmp_path), scope_name="finance", inline_synthetic=True
    )
    assert snapshot
    source_id = decode(snapshot.changes[0].content.encode())[0].sources[0].id
    result = runner.invoke(
        app,
        [
            "finance",
            "calculate",
            source_id,
            "--key",
            "cash_available",
            "--key",
            "cash_pending",
            "--save",
            *options,
        ],
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["result"]["value"] == "0.30"
    assert ws.fs.files("receipts/calculations")


def test_life_hub_preserves_documents_history_terms_and_review_metadata(
    ws: Workspace,
    tmp_path: Path,
) -> None:
    file = tmp_path / "device-manual.txt"
    file.write_text("Synthetic device warranty ends 2027-02-01.\nService performed 2026-01-02.")
    source = capture(ws, file, domain="life")
    extraction, key = extract(ws, source.id, inline_synthetic=True)
    ref = EvidenceRef(
        id=source.id, source_hash=extraction.source_hash, evidence_hash=key, locator="line 1"
    )
    service_ref = ref.model_copy(update={"locator": "line 2"})
    dossier = LifeDossier(
        entity_alias="device_synthetic",
        entity_kind="device",
        title="Synthetic device",
        authoritative_documents=[ref],
        service_history=[
            LifeEvent(
                date=date(2026, 1, 2), description="Inspected the device.", sources=[service_ref]
            )
        ],
        terms=[
            LifeTerm(
                kind="warranty",
                date=date(2027, 2, 1),
                description="Limited warranty.",
                sources=[ref],
            )
        ],
        review_date=date(2026, 12, 1),
        procedures=[ref],
    )
    file = tmp_path / "life-dossier.json"
    file.write_bytes(canonical(dossier))
    first = import_dossier(ws, file, scope_name="life", inline_synthetic=True)
    assert first
    accept(ws, first)
    entity = ws.record(first.changes[0].id)[1]
    assert entity.review_date == date(2026, 12, 1)
    assert len(entity.assertions) == 2 and entity.sources[0] == ref
    assert "external calendar" in entity.sections["reminders"]
    assert import_dossier(ws, file, scope_name="life", inline_synthetic=True) is None
    old_assertions = entity.assertions
    dossier.service_history = []  # A later input cannot erase earlier service history.
    dossier.terms = []
    dossier.review_date = date(2027, 1, 1)
    file.write_bytes(canonical(dossier))
    revised = import_dossier(ws, file, scope_name="life", inline_synthetic=True)
    assert revised
    accept(ws, revised)
    current = ws.record(entity.id)[1]
    assert current.assertions == old_assertions
    assert current.review_date == date(2027, 1, 1)
    with pytest.raises(Denied):
        import_dossier(ws, file, scope_name="research", inline_synthetic=True)
