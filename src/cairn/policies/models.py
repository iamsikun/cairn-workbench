from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from cairn.errors import Denied
from cairn.records.models import ID, Classification, Domain, Labels, Model, Record, now

LEVEL = {"public": 0, "private": 1, "restricted": 2}


class Scope(Model):
    name: ID
    domains: set[Domain]
    max_classification: Classification = "private"
    compartments: set[ID] = Field(default_factory=set)
    record_ids: set[ID] | None = None
    project_ids: set[ID] | None = None

    def allows(self, record: Record) -> bool:
        return (
            record.domain in self.domains
            and LEVEL[record.classification] <= LEVEL[self.max_classification]
            and record.compartments <= self.compartments
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
    provider: str
    destination: str
    operations: set[Literal["generation", "extraction", "query", "context", "client_export"]]
    valid_until: datetime
    owner_consent: str = Field(min_length=1)


class Policy(Model):
    schema_version: Literal[1] = 1
    revision: int = Field(default=1, ge=1)
    scopes: dict[ID, Scope]
    cloud_grants: list[RouteGrant] = Field(default_factory=list)
    max_changes: int = Field(default=4, ge=1, le=20)

    def scope(self, name: str) -> Scope:
        if name not in self.scopes:
            raise Denied("scope unavailable")
        return self.scopes[name]

    def authorize_route(
        self,
        scope: Scope,
        inputs: list[Labels],
        *,
        route: Literal["local", "cloud"],
        provider: str,
        operation: str,
        destination: str = "local",
        question: Labels | None = None,
    ) -> None:
        if route == "local":
            return
        # Missing question labels never become permission to export a question.
        all_inputs = [*inputs, question or Labels(domain="shared", classification="restricted")]
        if any(item.processing != "cloud_eligible" for item in all_inputs):
            raise Denied("request requires local-only processing")
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


def require_inheritance(output: Labels, inputs: list[Labels]) -> None:
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
