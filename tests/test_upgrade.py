"""Owner-authorized runtime upgrade against synthetic workspaces and a local channel.

Runtime verification and the worker probe are test doubles here; these tests cover the
authorization, channel/version, binding and recovery logic, not installation or isolation.
"""

import json
import subprocess
from pathlib import Path

import pytest
from pydantic import ValidationError
from synthetic_channel import Channel, channel, version_files
from test_activation import passing_probe
from test_release import manifest

from cairn.errors import Blocked, CairnError, Conflict, Denied
from cairn.records.models import canonical, digest, now
from cairn.records.runtime import (
    PROBE_CHECKS,
    REQUIRED_REVIEWS,
    ProbeResult,
    RuntimeApproval,
    WorkerProfile,
)
from cairn.storage import activation, upgrade
from cairn.storage.backup import validate_payloads
from cairn.storage.files import RootFS
from cairn.storage.streaming_backup import durable_contents, restore
from cairn.storage.workspace import Workspace
from cairn.updater.source import fetch, git, source_hash

STATEMENT = "Synthetic owner consent to automatic updates."


@pytest.fixture
def private(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    monkeypatch.setattr(activation, "verify_runtime", lambda _: {"synthetic_test_double": True})
    monkeypatch.setattr(upgrade, "verify_runtime", lambda _: {"synthetic_test_double": True})
    monkeypatch.setattr(activation, "invoke_worker", passing_probe)
    release = tmp_path / "release-a.json"
    release.write_bytes(canonical(manifest()))
    ws = Workspace.init(
        tmp_path / "private-mode-fixture",
        code_roots=[tmp_path / "code"],
        release=release,
        release_sha256=digest(release.read_bytes()),
        statement="Synthetic fixture owner review; not a real activation.",
        acknowledgements=REQUIRED_REVIEWS.copy(),
    )
    source = channel(tmp_path)
    return {
        "ws": ws,
        "channel": source,
        "mirror": tmp_path / "mirror.git",
        "tmp": tmp_path,
        "released": {},
    }


def release_for(
    fixture: dict, tag: str, commit: str | None = None, **changes: object
) -> tuple[Path, str]:
    """Publish a release on stable (once per tag) and the manifest its build would produce."""
    source: Channel = fixture["channel"]
    if commit is None:
        if tag not in fixture["released"]:
            fixture["released"][tag] = source.release(tag.removeprefix("v"))
        commit = fixture["released"][tag]
    fetch(fixture["mirror"], str(source.work), "stable")
    fields = {"code_revision": commit, "source_hash": source_hash(fixture["mirror"], commit)}
    built = manifest().model_copy(update=fields | changes)
    path = fixture["tmp"] / f"release-{tag}-{commit[:8]}-{len(changes)}.json"
    path.write_bytes(canonical(built))
    return path, digest(path.read_bytes())


def rebind(fixture: dict, tag: str, release: Path, sha: str) -> dict[str, object]:
    return upgrade.rebind(
        fixture["ws"].root,
        release=release,
        release_sha256=sha,
        mirror=fixture["mirror"],
        tag=tag,
        backup_dir=fixture["tmp"] / "update-backups",
    )


def enable(fixture: dict) -> None:
    upgrade.enable(
        fixture["ws"],
        repository=str(fixture["channel"].work),
        ref="stable",
        statement=STATEMENT,
    )


def test_channel_release_rebinds_with_backup_chain_and_history(private: dict) -> None:
    enable(private)
    before = private["ws"].config
    release, sha = release_for(private, "v0.2.0")
    result = rebind(private, "v0.2.0", release, sha)
    assert result["status"] == "upgraded" and result["migrations"] == []
    ws = Workspace(private["ws"].root)
    assert ws.config.runtime_release_hash == sha != before.runtime_release_hash
    approval = RuntimeApproval.model_validate_json(
        ws.fs.read(f"receipts/runtime/{ws.config.runtime_approval_id}.json")
    )
    assert approval.operation == "upgrade" and approval.release_tag == "v0.2.0"
    assert approval.previous_approval_id == before.runtime_approval_id
    assert ws.fs.read(f"policy/runtime-releases/{sha}.json") == release.read_bytes()
    backups = list((private["tmp"] / "update-backups" / ws.config.id).glob("*.zip"))
    assert len(backups) == 1 and digest(backups[0].read_bytes()) == approval.backup_sha256
    # The pre-upgrade archive still binds the release it was taken under.
    assert validate_payloads(durable_contents(ws)).runtime_release_hash == sha
    assert rebind(private, "v0.2.0", release, sha)["status"] == "current"

    # A later release chains onto the upgrade, and an upgraded archive restores.
    private["channel"].commit({"src/cairn/later.py": b"VALUE = 3\n"})
    later, later_sha = release_for(private, "v0.3.0")
    assert rebind(private, "v0.3.0", later, later_sha)["status"] == "upgraded"
    archive = private["tmp"] / "upgraded.zip"
    from cairn.storage.streaming_backup import backup

    checksum = backup(Workspace(private["ws"].root), archive)["sha256"]
    restored = restore(
        archive,
        private["tmp"] / "restored",
        code_roots=[private["tmp"] / "code"],
        expected_sha256=str(checksum),
        release=later,
        release_sha256=later_sha,
        statement="Synthetic restore review.",
        acknowledgements=REQUIRED_REVIEWS.copy(),
    )
    assert restored.config.runtime_release_hash == later_sha


def unchanged(private: dict, action) -> None:
    root = private["ws"].root
    config = (root / "workspace.json").read_bytes()
    with pytest.raises((Denied, Conflict, Blocked)):
        action()
    assert (root / "workspace.json").read_bytes() == config
    Workspace(root)


def test_rebind_requires_active_owner_authorization(private: dict) -> None:
    release, sha = release_for(private, "v0.2.0")
    unchanged(private, lambda: rebind(private, "v0.2.0", release, sha))
    enable(private)
    with pytest.raises(Conflict, match="already enabled"):
        enable(private)
    assert upgrade.disable(private["ws"], statement="Synthetic stop.") is not None
    unchanged(private, lambda: rebind(private, "v0.2.0", release, sha))
    assert not (private["tmp"] / "update-backups").exists()
    enable(private)  # A fresh authorization after revocation is allowed.
    assert rebind(private, "v0.2.0", release, sha)["status"] == "upgraded"


def test_rebind_requires_a_channel_commit_declaring_the_release(private: dict) -> None:
    enable(private)
    source: Channel = private["channel"]
    # A commit that declares another version than the requested release.
    head = source.commit({"src/cairn/a.py": b"A = 1\n"})
    release, sha = release_for(private, "v0.2.0", commit=head)
    unchanged(private, lambda: rebind(private, "v0.2.0", release, sha))

    # Disagreeing version declarations are not a release.
    mismatch = source.commit(version_files("0.2.0", package="0.1.9"))
    release, sha = release_for(private, "v0.2.0", commit=mismatch)
    unchanged(private, lambda: rebind(private, "v0.2.0", release, sha))

    # A versioned commit that is not on stable.
    source.git("checkout", "-qb", "experimental")
    side = source.release("0.5.0")
    source.git("checkout", "-q", "stable")
    fetch(private["mirror"], str(source.work), "stable")
    git(private["mirror"], "fetch", "--quiet", str(source.work), "experimental")
    release, sha = release_for(private, "v0.5.0", commit=side)
    unchanged(private, lambda: rebind(private, "v0.5.0", release, sha))
    assert not (private["tmp"] / "update-backups").exists()


def test_rebind_binds_manifest_to_channel_source_and_never_downgrades(private: dict) -> None:
    enable(private)
    release, sha = release_for(private, "v0.2.0", source_hash="9" * 64)
    unchanged(private, lambda: rebind(private, "v0.2.0", release, sha))
    release, sha = release_for(private, "v0.2.0", code_revision="b" * 40)
    unchanged(private, lambda: rebind(private, "v0.2.0", release, sha))
    with pytest.raises(Conflict, match="verified build"):
        rebind(private, "v0.2.0", release, "0" * 64)

    newer, newer_sha = release_for(private, "v0.3.0")
    assert rebind(private, "v0.3.0", newer, newer_sha)["status"] == "upgraded"
    older, older_sha = release_for(private, "v0.2.0")
    unchanged(private, lambda: rebind(private, "v0.2.0", older, older_sha))


def test_failed_worker_probe_blocks_before_backup(
    private: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    enable(private)
    release, sha = release_for(private, "v0.2.0")

    def failing(image: str, raw: bytes) -> bytes:
        response = json.loads(passing_probe(image, raw))
        response["checks"]["no_dns"] = False
        return canonical(response)

    monkeypatch.setattr(activation, "invoke_worker", failing)
    unchanged(private, lambda: rebind(private, "v0.2.0", release, sha))
    assert not (private["tmp"] / "update-backups").exists()


def test_interrupted_rebind_leaves_previous_binding_valid(
    private: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    enable(private)
    release, sha = release_for(private, "v0.2.0")
    original = RootFS.write

    def interrupt(self: RootFS, relative: str, data: bytes, **kwargs: object) -> None:
        if relative == "workspace.json":
            raise OSError("synthetic interruption before commit")
        original(self, relative, data, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(RootFS, "write", interrupt)
    with pytest.raises(OSError):
        rebind(private, "v0.2.0", release, sha)
    monkeypatch.setattr(RootFS, "write", original)
    ws = Workspace(private["ws"].root)
    assert ws.config.runtime_release_hash != sha
    # Orphaned manifest/approval receipts do not invalidate the archive or a retry.
    validate_payloads(durable_contents(ws))
    assert rebind(private, "v0.2.0", release, sha)["status"] == "upgraded"


def test_upgrade_chain_is_checked_on_every_open(private: dict) -> None:
    enable(private)
    release, sha = release_for(private, "v0.2.0")
    rebind(private, "v0.2.0", release, sha)
    ws = Workspace(private["ws"].root)
    path = f"receipts/runtime/{ws.config.runtime_approval_id}.json"
    approval = RuntimeApproval.model_validate_json(ws.fs.read(path))
    forged = approval.model_copy(update={"update_authorization_id": "update_forged"})
    ws.fs.write(path, canonical(forged))
    with pytest.raises((Denied, FileNotFoundError)):
        Workspace(ws.root)


def test_upgrade_approval_shape_is_enforced() -> None:
    worker = WorkerProfile(
        id="profile_synthetic",
        at=now(),
        image="sha256:" + "2" * 64,
        profile_hash="3" * 64,
        result=ProbeResult(nonce="0" * 32, checks=dict.fromkeys(PROBE_CHECKS, True)),
    )
    base = {
        "id": "runtime_synthetic",
        "workspace_id": "workspace_synthetic",
        "at": now(),
        "release_hash": "4" * 64,
        "owner_statement": "Synthetic.",
        "worker": worker,
    }
    with pytest.raises(ValidationError):
        RuntimeApproval(operation="upgrade", acknowledgements=set(), **base)
    with pytest.raises(ValidationError):
        RuntimeApproval(
            operation="init",
            acknowledgements=REQUIRED_REVIEWS,
            release_tag="v1.0.0",
            **base,
        )
    with pytest.raises(ValidationError):
        RuntimeApproval(
            operation="upgrade",
            acknowledgements=REQUIRED_REVIEWS,
            previous_approval_id="runtime_previous",
            update_authorization_id="update_synthetic",
            release_tag="v1.0.0",
            backup_sha256="5" * 64,
            **base,
        )


def test_synthetic_workspaces_cannot_enable_updates(ws: Workspace) -> None:
    with pytest.raises(Denied):
        upgrade.enable(ws, repository="/synthetic", ref="stable", statement="s")


def test_git_failures_are_reported_as_blocked(tmp_path: Path) -> None:
    with pytest.raises(CairnError):
        fetch(tmp_path / "mirror.git", str(tmp_path / "absent-remote"), "stable")
    assert subprocess.run(["git", "--version"], capture_output=True).returncode == 0


def test_upgrade_migrates_legacy_format_automatically_with_backup(private: dict) -> None:
    from test_migration import legacy

    enable(private)
    private["ws"] = legacy(private["ws"])
    assert private["ws"].config.schema_version == 1
    release, sha = release_for(private, "v0.2.0")
    result = rebind(private, "v0.2.0", release, sha)
    # Schema 1 -> 2 -> 3, one step at a time, each with its own backup.
    assert isinstance(result["migrations"], list) and len(result["migrations"]) == 2
    ws = Workspace(private["ws"].root)
    assert ws.config.schema_version == 3 and ws.config.runtime_release_hash == sha
    assert ws.config.code_roots == private["ws"].config.code_roots
    assert len(list((private["tmp"] / "update-backups" / ws.config.id).glob("*.zip"))) == 3
