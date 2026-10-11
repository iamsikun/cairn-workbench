"""Historical approval/backup validation uses explicitly constructed synthetic fixtures."""

from pathlib import Path

import pytest
from test_release import manifest

from cairn.adapters.legacy import historical_worker_profile
from cairn.errors import Blocked, Conflict, Denied
from cairn.ingest.service import capture, extract
from cairn.records.models import canonical, digest, now
from cairn.records.release import ReleaseManifest
from cairn.records.runtime import PROBE_CHECKS, REQUIRED_REVIEWS, ProbeResult, WorkerProfile
from cairn.storage import activation
from cairn.storage.backup import backup, restore
from cairn.storage.files import RootFS
from cairn.storage.workspace import Workspace


def passing_profile(image: str) -> WorkerProfile:
    return WorkerProfile(
        id="profile_synthetic", at=now(), image=image,
        profile_hash=digest(canonical(historical_worker_profile(image))),
        result=ProbeResult(nonce="0" * 32, checks=dict.fromkeys(PROBE_CHECKS, True)),
    )


@pytest.fixture
def reviewed_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    """Construct old-format synthetic bytes; never enables production activation."""
    release = tmp_path / "release.json"
    release.write_bytes(canonical(manifest()))
    monkeypatch.setattr(activation, "verify_runtime", lambda _: {"synthetic_test_double": True})

    def prepared(file, *, expected_sha256, statement, acknowledgements):
        raw = file.read_bytes()
        assert digest(raw) == expected_sha256
        value = ReleaseManifest.model_validate_json(raw)
        return activation.PreparedActivation(
            raw, value, statement, acknowledgements, passing_profile(value.worker_image)
        )

    monkeypatch.setattr(activation, "prepare_activation", prepared)
    monkeypatch.setattr("cairn.storage.backup.prepare_activation", prepared)
    monkeypatch.setattr("cairn.storage.streaming_backup.prepare_activation", prepared)
    return {
        "release": release,
        "release_sha256": digest(release.read_bytes()),
        "statement": "Synthetic historical fixture; not a real activation.",
        "acknowledgements": REQUIRED_REVIEWS.copy(),
    }


def test_activated_workspace_binds_runtime_and_rechecks_before_operations(
    reviewed_fixture: dict,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ws = Workspace.init(
        tmp_path / "private-mode-fixture", code_roots=[tmp_path / "code"], **reviewed_fixture
    )
    assert not ws.config.synthetic and ws.config.runtime_approval_id
    assert ws.config.worker_image == manifest().worker_image
    assert len(ws.fs.files("receipts/runtime")) == 1
    file = tmp_path / "synthetic.txt"
    file.write_text("Synthetic activation evidence only.")
    source = capture(ws, file, domain="research")

    # Historical private-mode records never take the synthetic inline branch.
    with pytest.raises(Blocked, match="retired"):
        extract(ws, source.id, inline_synthetic=True)
    config = ws.config.model_copy(deep=True)
    config.worker_image = "sha256:" + "9" * 64
    ws.fs.write("workspace.json", canonical(config))
    with pytest.raises(Conflict, match="configuration changed"):
        with ws.lock():
            pass
    with pytest.raises(Denied, match="does not bind"):
        Workspace(ws.root)
    ws.fs.write("workspace.json", canonical(ws.config))
    ws.fs.write("policy/runtime-release.json", canonical(manifest()) + b"\n")
    with pytest.raises(Conflict, match="checksum"):
        Workspace(ws.root)


def test_private_mode_restore_preserves_data_and_requires_fresh_bound_review(
    reviewed_fixture: dict,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    code = tmp_path / "code"
    ws = Workspace.init(tmp_path / "private-mode-fixture", code_roots=[code], **reviewed_fixture)
    file = tmp_path / "synthetic.txt"
    file.write_text("Synthetic preserved original.")
    source = capture(ws, file, domain="research")
    archive = tmp_path / "fixture.zip"
    report = backup(ws, archive)
    old_approval = ws.config.runtime_approval_id
    old_policy = ws.policy_hash
    with pytest.raises(Denied, match="mode"):
        restore(archive, tmp_path / "wrong-mode", code_roots=[code], synthetic=True)
    changed_release = manifest()
    changed_release.source_hash = "9" * 64
    changed_file = tmp_path / "changed-release.json"
    changed_file.write_bytes(canonical(changed_release))
    with pytest.raises(Denied, match="original reviewed release"):
        restore(
            archive,
            tmp_path / "wrong-release",
            code_roots=[code],
            expected_sha256=str(report["sha256"]),
            **{
                **reviewed_fixture,
                "release": changed_file,
                "release_sha256": digest(changed_file.read_bytes()),
            },
        )
    restored = restore(
        archive,
        tmp_path / "restored",
        code_roots=[code],
        expected_sha256=str(report["sha256"]),
        **reviewed_fixture,
    )
    assert restored.config.id == ws.config.id and restored.policy_hash == old_policy
    assert restored.config.runtime_approval_id != old_approval
    assert len(restored.fs.files("receipts/runtime")) == 2
    assert restored.record(source.id)[1] == source
    assert source.source
    assert restored.fs.read(source.source.blob) == file.read_bytes()

    def drift(_: object) -> None:
        raise Denied("synthetic installation drift")

    monkeypatch.setattr(activation, "verify_runtime", drift)
    with pytest.raises(Denied, match="installation drift"):
        Workspace(restored.root)


def test_initialization_write_failure_does_not_publish_partial_workspace(
    reviewed_fixture: dict,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = RootFS.write

    def fail(self: RootFS, path: str, raw: bytes, **kwargs: object) -> None:
        if path.startswith("receipts/runtime/"):
            raise OSError("synthetic disk failure")
        original(self, path, raw, **kwargs)

    monkeypatch.setattr(RootFS, "write", fail)
    target = tmp_path / "private-mode-fixture"
    with pytest.raises(OSError):
        Workspace.init(target, code_roots=[tmp_path / "code"], **reviewed_fixture)
    assert not target.exists() and not list(tmp_path.glob(".cairn-init-*"))
