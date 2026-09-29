from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from cairn.records.models import ID, EvidenceRef, Model, Money


class ObservedValue(Model):
    key: ID
    label: str = Field(min_length=1, max_length=300)
    measure: Literal["balance", "holding_quantity", "price", "transaction", "other"]
    value: Decimal = Field(allow_inf_nan=False, max_digits=30, decimal_places=12)
    unit: str = Field(min_length=1, max_length=40)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")

    @field_validator("value", mode="before")
    @classmethod
    def decimal_input(cls, value: Any) -> Any:
        if isinstance(value, (float, bool)):
            raise ValueError("financial values require exact decimal strings")
        return value


class FinancialSnapshot(Model):
    schema_version: Literal[1] = 1
    snapshot_id: ID
    owner_alias: ID
    account_alias: ID
    as_of: date
    statement_period: str | None = None
    values: list[ObservedValue] = Field(min_length=1, max_length=10000)

    @model_validator(mode="after")
    def unique(self) -> FinancialSnapshot:
        if len({value.key for value in self.values}) != len(self.values):
            raise ValueError("duplicate financial value key")
        return self


class Calculation(Model):
    schema_version: Literal[1] = 1
    operation: Literal["sum", "difference"]
    algorithm: Literal["decimal-v1"] = "decimal-v1"
    operands: list[Money] = Field(min_length=1, max_length=10000)
    result: Money


class LifeEvent(Model):
    date: date
    description: str = Field(min_length=1, max_length=3000)
    sources: list[EvidenceRef] = Field(min_length=1, max_length=20)


class LifeTerm(Model):
    kind: Literal["warranty", "renewal"]
    date: date
    description: str = Field(min_length=1, max_length=3000)
    sources: list[EvidenceRef] = Field(min_length=1, max_length=20)


class LifeDossier(Model):
    schema_version: Literal[1] = 1
    entity_alias: ID
    entity_kind: Literal["home", "vehicle", "pet", "device", "other"]
    title: str = Field(min_length=1, max_length=500)
    authoritative_documents: list[EvidenceRef] = Field(min_length=1, max_length=100)
    service_history: list[LifeEvent] = Field(default_factory=list, max_length=1000)
    terms: list[LifeTerm] = Field(default_factory=list, max_length=100)
    procedures: list[EvidenceRef] = Field(default_factory=list, max_length=100)
    review_date: date | None = None
