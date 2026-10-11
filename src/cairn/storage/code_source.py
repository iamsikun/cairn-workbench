"""Owner change of where a knowledge base's Cairn code lives.

A repository URL only names the code. A local checkout path is also a guard: the
workspace, backups, HTML outputs and the library root must stay disjoint from it.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator

from cairn.errors import CairnError, Conflict, Denied
from cairn.records.models import ID, Digest, Model, canonical, digest, new_id, now
from cairn.storage.files import disjoint
from cairn.storage.workspace import (
    CURRENT_SCHEMA,
    Repository,
    Workspace,
    check_roots,
    with_code_source,
)

CHANGES = "receipts/code-source"


class CodeSourceChange(Model):
    """Owner receipt for one replacement of the workspace's code source."""

    schema_version: Literal[1] = 1
    id: ID
    workspace_id: ID
    at: datetime
    before_code_roots: list[str]
    before_code_repository: Repository | None
    after_code_roots: list[str]
    after_code_repository: Repository | None
    before_hash: Digest
    after_hash: Digest
    owner_statement: str = Field(min_length=1, max_length=4000)

    @field_validator("owner_statement")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("owner statement is required")
        return value


def show(ws: Workspace) -> dict[str, object]:
    with ws.lock():
        return {
            "workspace_id": ws.config.id,
            "workspace_schema": ws.config.schema_version,
            "code_roots": ws.config.code_roots,
            "code_repository": getattr(ws.config, "code_repository", None),
        }


def _check_outputs(ws: Workspace, code_roots: list[Path]) -> None:
    """Configured outputs outside the workspace must stay outside a new checkout."""
    from cairn.library.catalog import CONFIG_PATH
    from cairn.library.models import LibraryConfig
    from cairn.presentation.live import registrations

    outputs = [Path(rendering.output) for rendering in registrations(ws)]
    if ws.fs.exists(CONFIG_PATH):
        outputs.append(Path(LibraryConfig.model_validate_json(ws.fs.read(CONFIG_PATH)).root))
    if any(not disjoint(output, code) for output in outputs for code in code_roots):
        raise Denied("a configured library or HTML output lies inside the new code root")


def set_code_source(
    ws: Workspace,
    *,
    code_roots: list[Path] | None,
    repository: str | None,
    clear_repository: bool = False,
    statement: str,
) -> CodeSourceChange:
    """Replace the given parts of the code source; unspecified parts are kept."""
    if not statement.strip() or len(statement) > 4000:
        raise CairnError(
            "a code source change requires an owner statement of at most 4000 characters"
        )
    with ws.lock(write=True):
        config = ws.config
        if config.schema_version != CURRENT_SCHEMA:
            raise Denied(
                "changing the code source needs workspace schema 3; "
                "run `cairn schema preview` and `cairn schema apply` first"
            )
        if clear_repository:
            if repository is not None:
                raise Denied("choose either a repository or no repository")
            # Validated together with the rest of the change below.
            config = type(config).model_construct(**{**dict(config), "code_repository": None})
        updated = with_code_source(config, code_roots, repository)
        roots = [Path(root) for root in updated.code_roots]
        check_roots(ws.root, roots)
        _check_outputs(ws, roots)
        if updated == ws.config:
            raise Conflict("the code source is unchanged")
        before, after = ws.fs.read("workspace.json"), canonical(updated)
        change = CodeSourceChange(
            id=new_id("codesource"),
            workspace_id=ws.config.id,
            at=now(),
            before_code_roots=ws.config.code_roots,
            before_code_repository=getattr(ws.config, "code_repository", None),
            after_code_roots=updated.code_roots,
            after_code_repository=getattr(updated, "code_repository", None),
            before_hash=digest(before),
            after_hash=digest(after),
            owner_statement=statement,
        )
        # The receipt is an intent until the configuration replacement commits it; a
        # receipt whose after_hash differs from workspace.json records no change.
        ws.fs.write(f"{CHANGES}/{change.id}.json", canonical(change), exclusive=True)
        ws.fs.write("workspace.json", after)
        ws.config = updated
    return change
