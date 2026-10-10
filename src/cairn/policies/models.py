from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator, model_validator

from cairn.errors import Denied
from cairn.records.models import ID, Classification, Domain, Labels, Model, Record, now

LEVEL = {"public": 0, "private": 1, "restricted": 2}
Operation = Literal["generation", "extraction", "query", "context", "client_export"]


class Scope(Model):
    name: ID
    domains: set[Domain] = Field(min_length=1)
    max_classification: Classification = "private"
    compartments: set[ID] = Field(default_factory=set)
    record_ids: set[ID] | None = None
    project_ids: set[ID] | None = None

    def allows_labels(self, labels: Labels) -> bool:
        return (
            labels.domain in self.domains
            and LEVEL[labels.classification] <= LEVEL[self.max_classification]
            and labels.compartments <= self.compartments
        )

    def allows(self, record: Record) -> bool:
        return (
            self.allows_labels(record)
            and (self.record_ids is None or record.id in self.record_ids)
            and (
                self.project_ids is None
                or record.id in self.project_ids
                or bool(set(record.project_ids) & self.project_ids)
            )
        )

    def require(self, record: Record) -> None:
        if not self.allows(record):
            raise Denied("record unavailable in this scope")

    def narrowed(self, other: Scope) -> Scope:
        if (
            not other.domains <= self.domains
            or LEVEL[other.max_classification] > LEVEL[self.max_classification]
            or not other.compartments <= self.compartments
            or (
                self.record_ids is not None
                and (other.record_ids is None or not other.record_ids <= self.record_ids)
            )
            or (
                self.project_ids is not None
                and (other.project_ids is None or not other.project_ids <= self.project_ids)
            )
        ):
            raise Denied("session scope cannot be widened")
        return other


class RouteGrant(Model):
    id: ID
    scope: ID
    provider: str = Field(min_length=1, max_length=200)
    destination: str = Field(min_length=1, max_length=2000)
    operations: set[Operation] = Field(min_length=1)
    valid_until: datetime
    owner_consent: str = Field(min_length=1, max_length=4000)

    @field_validator("valid_until")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("grant expiry requires a timezone")
        return value

    @field_validator("owner_consent", "provider", "destination")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("grant fields cannot be blank")
        return value


class Policy(Model):
    schema_version: Literal[1] = 1
    revision: int = Field(default=1, ge=1)
    last_change: ID | None = None
    scopes: dict[ID, Scope]
    cloud_grants: list[RouteGrant] = Field(default_factory=list)
    max_changes: int = Field(default=4, ge=1, le=20)

    @model_validator(mode="after")
    def consistent(self) -> Policy:
        if any(key != scope.name for key, scope in self.scopes.items()):
            raise ValueError("scope keys must match names")
        if len({grant.id for grant in self.cloud_grants}) != len(self.cloud_grants):
            raise ValueError("duplicate grant ID")
        if any(grant.scope not in self.scopes for grant in self.cloud_grants):
            raise ValueError("grant scope unavailable")
        return self

    def scope(self, name: str) -> Scope:
        if name not in self.scopes:
            raise Denied("scope unavailable")
        return self.scopes[name]

    def authorize_route(
        self,
        scope: Scope,
        inputs: Sequence[Labels],
        *,
        route: Literal["local", "cloud"],
        provider: str,
        operation: Operation,
        destination: str = "local",
        question: Labels | None = None,
        extra_parts: Sequence[Labels] = (),
    ) -> None:
        self.scope(scope.name).narrowed(scope)
        for item in inputs:
            if isinstance(item, Record):
                scope.require(item)
            elif (
                item.domain not in scope.domains
                or LEVEL[item.classification] > LEVEL[scope.max_classification]
                or not item.compartments <= scope.compartments
            ):
                raise Denied("request input unavailable in this scope")
        if route == "local":
            if destination != "local":
                raise Denied("local routes cannot name a remote destination")
            return
        # Missing question labels never become permission to export a question.
        all_inputs = [
            *inputs,
            question or Labels(domain="shared", classification="restricted"),
            *extra_parts,
        ]
        if any(item.processing != "cloud_eligible" for item in all_inputs):
            raise Denied("request requires local-only processing")
        if any(
            item.domain not in scope.domains
            or LEVEL[item.classification] > LEVEL[scope.max_classification]
            or not item.compartments <= scope.compartments
            for item in all_inputs
        ):
            raise Denied("complete request exceeds grant scope")
        for grant in self.cloud_grants:
            if (
                grant.scope == scope.name
                and grant.provider == provider
                and grant.destination == destination
                and operation in grant.operations
                and grant.valid_until.tzinfo is not None
                and grant.valid_until > now()
            ):
                return
        raise Denied("no applicable cloud processing grant")


def require_inheritance(output: Labels, inputs: Sequence[Labels]) -> None:
    if any(LEVEL[output.classification] < LEVEL[item.classification] for item in inputs):
        raise Denied("derived record weakens confidentiality")
    if (
        any(item.processing == "local_only" for item in inputs)
        and output.processing != "local_only"
    ):
        raise Denied("derived record weakens processing restrictions")
    required = set().union(*(item.compartments | {item.domain} for item in inputs))
    if not required <= (output.compartments | {output.domain}):
        raise Denied("derived record drops access compartments")
