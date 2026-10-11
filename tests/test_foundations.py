import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from cairn.errors import Blocked, CairnError, Denied
from cairn.policies.models import require_inheritance
from cairn.records.models import Labels, Money, Record, canonical
from cairn.storage.markdown import decode, encode
from cairn.storage.workspace import Workspace


def test_round_trip_and_stable_sets(record: Record) -> None:
    record.compartments = {"research", "project_alpha", "project_beta"}
    data = encode(record, "# Thinking\n\n证据 and uncertainty.\n")
    restored, body = decode(data)
    assert restored == record
    assert body.endswith("证据 and uncertainty.\n")
    assert encode(restored, body) == data
    assert canonical({"x": {"z", "a"}}) == b'{"x":["a","z"]}\n'


@pytest.mark.parametrize(
    "relative",
    ["../outside", "/etc/passwd", "a/../b", "a//b", "a/./b", "a\\b", "e\u0301", "a\x00b"],
)
def test_traversal_rejected(ws: Workspace, relative: str) -> None:
    with pytest.raises(Denied):
        ws.fs.write(relative, b"escape")


def test_links_special_files_and_collisions(ws: Workspace, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret").write_text("synthetic canary")
    (ws.root / "escape").symlink_to(outside, target_is_directory=True)
    with pytest.raises(Denied):
        ws.fs.read("escape/secret")
    with pytest.raises(Denied):
        ws.fs.write("escape/modified", b"no")
    (ws.root / "link").symlink_to(outside / "secret")
    with pytest.raises(Denied):
        ws.fs.read("link")
    os.link(outside / "secret", ws.root / "hardlink")
    with pytest.raises(Denied):
        ws.fs.write("hardlink", b"no")
    os.mkfifo(ws.root / "fifo")
    with pytest.raises(Denied):
        ws.fs.read("fifo")
    ws.fs.write("vault/notes/Title.md", b"owner text")
    with pytest.raises(Denied):
        ws.fs.write("vault/notes/title.md", b"collision")
    assert (outside / "secret").read_text() == "synthetic canary"


def test_roots_must_be_disjoint_and_not_git(tmp_path: Path) -> None:
    public = tmp_path / "public"
    public.mkdir()
    (public / ".git").mkdir()
    for private in (public, public / "private", tmp_path):
        with pytest.raises(Denied):
            Workspace.init(private, code_roots=[public], synthetic=True)
    alias = tmp_path / "alias"
    alias.symlink_to(public)
    with pytest.raises(Denied):
        Workspace.init(alias / "private", code_roots=[public], synthetic=True)
    with pytest.raises(Blocked, match="retired"):
        Workspace.init(tmp_path / "private", code_roots=[public])


def test_yaml_does_not_execute_or_accept_duplicate_keys(record: Record) -> None:
    for data in (
        b"---\nx: !!python/object/apply:os.system ['echo bad']\n---\n",
        b"---\nid: one\nid: two\n---\n",
        b"---\nx: &x [*x]\n---\n",
    ):
        with pytest.raises(CairnError):
            decode(data)
    with pytest.raises(ValidationError):
        Record.model_validate({**record.model_dump(), "approved": True})


def test_scope_cannot_widen_or_drop_labels(ws: Workspace, record: Record) -> None:
    scope = ws.policy.scope("research")
    assert scope.allows(record)
    with pytest.raises(Denied):
        scope.narrowed(ws.policy.scope("owner"))
    record.compartments = {"project_secret"}
    assert not scope.allows(record)
    with pytest.raises(Denied):
        require_inheritance(Labels(domain="shared"), [record])
    with pytest.raises(Denied):
        require_inheritance(Labels(domain="research", processing="cloud_eligible"), [record])


def test_public_evidence_does_not_authorize_private_question(ws: Workspace) -> None:
    evidence = Labels(domain="research", classification="public", processing="cloud_eligible")
    with pytest.raises(Denied):
        ws.policy.authorize_route(
            ws.policy.scope("research"),
            [evidence],
            route="cloud",
            provider="example",
            operation="query",
        )


def test_schema_rejects_unreferenced_numbers() -> None:
    with pytest.raises(ValidationError):
        Money(value=1.1, unit="balance", currency="USD", as_of="2026-01-01", sources=[])


def test_sync_uses_full_flush_where_available(monkeypatch: pytest.MonkeyPatch) -> None:
    import types

    import cairn.storage.files as files

    calls: list[str] = []

    def full(fd: int, op: int) -> int:
        calls.append("full")
        if fd == 2:
            raise OSError("synthetic unsupported filesystem")
        return 0

    monkeypatch.setattr(files, "fcntl", types.SimpleNamespace(F_FULLFSYNC=51, fcntl=full))
    monkeypatch.setattr(files.os, "fsync", lambda fd: calls.append("fsync"))
    files.sync(1)
    assert calls == ["full"]
    calls.clear()
    files.sync(2)
    assert calls == ["full", "fsync"]
    calls.clear()
    monkeypatch.setattr(files, "fcntl", types.SimpleNamespace(fcntl=full))
    files.sync(1)
    assert calls == ["fsync"]
