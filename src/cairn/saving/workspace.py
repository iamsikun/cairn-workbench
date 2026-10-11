from __future__ import annotations

import fcntl
import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import yaml

from cairn.errors import Conflict, Denied, RecoveryRequired
from cairn.records.models import Domain, canonical, digest, new_id
from cairn.saving.models import KnowledgeRecord, WorkspaceConfigV4
from cairn.storage.files import RootFS, sync
from cairn.storage.markdown import UniqueSafeLoader


def encode(record: KnowledgeRecord, body: str) -> bytes:
    header = yaml.safe_dump(json.loads(canonical(record)), sort_keys=True, allow_unicode=True)
    return f"---\n{header}---\n{body}".encode()


def decode(raw: bytes) -> tuple[KnowledgeRecord, str]:
    try:
        text = raw.decode()
        if not text.startswith("---\n"):
            raise ValueError("missing front matter")
        header, body = text[4:].split("\n---\n", 1)
        if len(header) > 2 * 1024 * 1024 or any(
            isinstance(t, (yaml.AliasToken, yaml.AnchorToken)) for t in yaml.scan(header)
        ):
            raise ValueError("invalid front matter")
        return KnowledgeRecord.model_validate(yaml.load(header, Loader=UniqueSafeLoader)), body
    except (ValueError, UnicodeError, yaml.YAMLError) as exc:
        raise Denied("invalid knowledge record") from exc


def check_root(root: Path) -> Path:
    root = root.resolve()
    if any((p / ".git").exists() for p in (root, *root.parents)):
        raise Denied("knowledge base must be outside a development checkout")
    return root


def is_current(root: Path) -> bool:
    return bool(json.loads(RootFS(root).read("workspace.json")).get("schema_version") == 4)


class Book:
    """New-format storage with no activation, policy, proposal, or provider dependencies."""

    def __init__(self, root: Path):
        self.root = check_root(root)
        self.fs = RootFS(self.root)
        if self.fs.exists("restore.pending"):
            raise RecoveryRequired("restore or initialization is incomplete")
        self.config = WorkspaceConfigV4.model_validate_json(self.fs.read("workspace.json"))

    @classmethod
    def init(cls, root: Path, *, synthetic: bool = False) -> Book:
        root = check_root(root)
        if root.exists() and any(root.iterdir()):
            raise Conflict("initialization requires an empty destination")
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        fs = RootFS(root)
        fs.write("restore.pending", b"initializing\n")
        fs.write(
            "workspace.json",
            canonical(
                WorkspaceConfigV4(
                    id=new_id("workspace"),
                    synthetic=synthetic,
                )
            ),
        )
        fs.remove("restore.pending")
        return cls(root)

    def collection(self, name: Domain) -> None:
        if name not in self.config.collections:
            raise Denied("collection unavailable")

    @contextmanager
    def lock(self, *, recovery: bool = False) -> Iterator[None]:
        with self.fs.parent("workspace.lock") as (parent, name):
            fd = os.open(name, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600, dir_fd=parent)
        try:
            self.fs._regular(os.fstat(fd))
            fcntl.flock(fd, fcntl.LOCK_EX)
            if WorkspaceConfigV4.model_validate_json(self.fs.read("workspace.json")) != self.config:
                raise Conflict("workspace configuration changed; reopen")
            if not recovery:
                for path in self.fs.files("journal/saves"):
                    if (
                        path.endswith(".json")
                        and json.loads(self.fs.read(path))["status"] != "committed"
                    ):
                        raise RecoveryRequired("incomplete save; run cairn recover")
                if self.fs.exists("migration.pending"):
                    raise RecoveryRequired("migration requires recovery")
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def records(self, collection: Domain) -> dict[str, tuple[str, KnowledgeRecord, str]]:
        self.collection(collection)
        result = {}
        for path in self.fs.files(f"vault/collections/{collection}"):
            if not path.endswith(".md"):
                continue
            record, body = decode(self.fs.read(path))
            if record.collection != collection or record.id in result:
                raise Conflict("inconsistent record collection or identity")
            result[record.id] = (path, record, body)
        return result

    def record(self, identity: str, collection: Domain) -> tuple[str, KnowledgeRecord, str]:
        item = self.records(collection).get(identity)
        if item is None or item[1].archived:
            raise Denied("record unavailable in this collection")
        return item

    def revision(self, path: str) -> str:
        return digest(self.fs.read(path))


def sync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        sync(fd)
    finally:
        os.close(fd)
