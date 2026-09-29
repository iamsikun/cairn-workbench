from __future__ import annotations

import fcntl
import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Literal

from pydantic import Field

from cairn.errors import Conflict, Denied, RecoveryRequired
from cairn.policies.models import Policy, Scope
from cairn.records.models import Domain, Event, Model, Record, canonical, digest, new_id
from cairn.storage.files import RootFS, disjoint
from cairn.storage.markdown import decode

DIRECTORIES = (
    "vault/inbox",
    "vault/sources",
    "vault/notes",
    "vault/decisions",
    "vault/wiki/research",
    "vault/wiki/finance",
    "vault/wiki/life",
    "vault/wiki/shared",
    "blobs",
    "evidence",
    "policy",
    "proposals",
    "approvals",
    "receipts",
    "journal",
    "cache",
)


class WorkspaceConfig(Model):
    schema_version: Literal[1] = 1
    id: str
    synthetic: bool
    code_roots: list[str] = Field(min_length=1)
    worker_image: str | None = None


def check_roots(root: Path, code_roots: list[Path]) -> Path:
    resolved = root.resolve()
    if not code_roots or any(not disjoint(resolved, code) for code in code_roots):
        raise Denied("code and workspace roots must be disjoint")
    for ancestor in (resolved, *resolved.parents):
        if (ancestor / ".git").exists():
            raise Denied("workspace must not be inside a development checkout")
    return resolved


class Workspace:
    def __init__(self, root: Path):
        self.fs = RootFS(root)
        self.root = self.fs.root
        self.config = WorkspaceConfig.model_validate_json(self.fs.read("workspace.json"))
        check_roots(self.root, [Path(path) for path in self.config.code_roots])

    @classmethod
    def init(cls, root: Path, *, code_roots: list[Path], synthetic: bool = False) -> Workspace:
        root = check_roots(root, code_roots)
        if root.exists() and any(root.iterdir()):
            raise Conflict("initialization requires an empty workspace")
        if not synthetic:
            # The activation command will verify the reviewed release manifest and
            # isolation evidence. Never allow checkout code to activate private data.
            raise Denied("private activation requires the reviewed-release procedure")
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        fs = RootFS(root)
        for directory in DIRECTORIES:
            with fs.parent(f"{directory}/sentinel", create=True):
                pass
        config = WorkspaceConfig(
            id=new_id("workspace"),
            synthetic=synthetic,
            code_roots=[str(path.resolve()) for path in code_roots],
        )
        domains: tuple[Domain, ...] = ("research", "finance", "life", "shared")
        scopes: dict[str, Scope] = {
            domain: Scope(name=domain, domains={domain}, compartments={domain})
            for domain in domains
        }
        scopes["owner"] = Scope(
            name="owner",
            domains={"research", "finance", "life", "shared"},
            max_classification="restricted",
            compartments={"research", "finance", "life", "shared"},
        )
        fs.write("workspace.json", canonical(config), exclusive=True)
        fs.write("policy/workspace.json", canonical(Policy(scopes=scopes)), exclusive=True)
        fs.write("vault/index.md", b"# Private Cairn workspace\n\nOwner navigation only.\n")
        return cls(root)

    @property
    def policy(self) -> Policy:
        return Policy.model_validate_json(self.fs.read("policy/workspace.json"))

    @property
    def policy_hash(self) -> str:
        return digest(self.fs.read("policy/workspace.json"))

    @contextmanager
    def lock(self, *, write: bool = False, recovery: bool = False) -> Iterator[None]:
        with self.fs.parent("workspace.lock") as (directory, name):
            fd = os.open(name, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600, dir_fd=directory)
        try:
            self.fs._regular(os.fstat(fd))
            fcntl.flock(fd, fcntl.LOCK_EX if write else fcntl.LOCK_SH)
            if not recovery:
                for path in self.fs.files("journal"):
                    if path.endswith("/transaction.json"):
                        transaction = json.loads(self.fs.read(path))
                        if transaction["status"] not in ("committed", "rolled_back"):
                            raise RecoveryRequired("an incomplete transaction requires recovery")
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def records(self, scope: Scope | None = None) -> list[tuple[str, Record, str]]:
        result = []
        ids: set[str] = set()
        for prefix in ("vault/sources", "vault/wiki", "vault/decisions"):
            for path in self.fs.files(prefix):
                if not path.endswith(".md"):
                    continue
                record, body = decode(self.fs.read(path))
                if record.id in ids:
                    raise Conflict("duplicate durable record ID")
                ids.add(record.id)
                if scope is None or scope.allows(record):
                    result.append((path, record, body))
        return result

    def record(self, object_id: str, scope: Scope | None = None) -> tuple[str, Record, str]:
        for item in self.records(scope):
            if item[1].id == object_id:
                return item
        raise Denied("record unavailable in this scope")

    def protected_hashes(self) -> dict[str, str]:
        return {
            path: digest(self.fs.read(path))
            for prefix in ("vault/sources", "vault/notes", "vault/inbox")
            for path in self.fs.files(prefix)
        }

    def event(self, event: Event) -> None:
        self.fs.write(f"receipts/events/{event.id}.json", canonical(event), exclusive=True)
