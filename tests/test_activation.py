import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from test_release import manifest
from typer.testing import CliRunner

from cairn.cli import app
from cairn.errors import Blocked, Conflict, Denied
from cairn.ingest.service import capture, extract
from cairn.proposals.service import prepare_job
from cairn.records.models import canonical, digest
from cairn.records.runtime import PROBE_CHECKS, REQUIRED_REVIEWS, ProbeRequest, ProbeResult
from cairn.storage import activation
from cairn.storage.backup import backup, restore
from cairn.storage.files import RootFS
from cairn.storage.workspace import Workspace


def passing_probe(image: str, raw: bytes) -> bytes:
    request = ProbeRequest.model_validate_json(raw)
    assert image == manifest().worker_image
    return canonical(ProbeResult(nonce=request.nonce, checks=dict.fromkeys(PROBE_CHECKS, True)))


@pytest.fixture
def reviewed_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    """Model private-mode lifecycle using synthetic data; not isolation/install evidence."""
    release = tmp_path / "release.json"
    release.write_bytes(canonical(manifest()))
    monkeypatch.setattr(activation, "verify_runtime", lambda _: {"synthetic_test_double": True})
    monkeypatch.setattr(activation, "invoke_worker", passing_probe)
    return {
        "release": release,
        "release_sha256": digest(release.read_bytes()),
        "statement": "Synthetic fixture owner review; not a real activation.",
        "acknowledgements": REQUIRED_REVIEWS.copy(),
    }


def test_activation_consent_and_installation_gate_precede_destination(tmp_path: Path) -> None:
    release = tmp_path / "release.json"
    release.write_bytes(canonical(manifest()))
    target = tmp_path / "private-mode-fixture"
    code = tmp_path / "code"
    for acks in (None, set(), REQUIRED_REVIEWS - {next(iter(REQUIRED_REVIEWS))}):
        with pytest.raises(Denied, match="review acknowledgements"):
            Workspace.init(
                target,
                code_roots=[code],
                release=release,
                release_sha256=digest(release.read_bytes()),
                statement="Synthetic review",
                acknowledgements=acks,
            )
        assert not target.exists()
    with pytest.raises(Denied, match="python -I -B"):
        Workspace.init(
            target,
            code_roots=[code],
            release=release,
            release_sha256=digest(release.read_bytes()),
            statement="Synthetic review",
            acknowledgements=REQUIRED_REVIEWS,
        )
    assert not target.exists()
    with pytest.raises(Denied, match="independently recorded archive"):
        restore(tmp_path / "absent.zip", target, code_roots=[code])
    with pytest.raises(Denied, match="reviewed release"):
        restore(tmp_path / "absent.zip", target, code_roots=[code], expected_sha256="0" * 64)


@pytest.mark.parametrize("mode", ["missing", "false", "replayed", "canary_changed", "unavailable"])
def test_activation_probe_fails_closed_before_workspace_creation(
    reviewed_fixture: dict,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    def probe(image: str, raw: bytes) -> bytes:
        request = ProbeRequest.model_validate_json(raw)
        if mode == "unavailable":
            raise Blocked("isolation_unavailable")
        response = json.loads(passing_probe(image, raw))
        if mode == "missing":
            response["checks"].pop("no_dns")
        if mode == "false":
            response["checks"]["no_dns"] = False
        if mode == "replayed":
            response["nonce"] = "0" * 32
        if mode == "canary_changed":
            Path(request.canary_path).write_text("synthetic corruption")
        return canonical(response)

    monkeypatch.setattr(activation, "invoke_worker", probe)
    destination = tmp_path / "private-mode-fixture"
    with pytest.raises((Blocked, ValidationError)):
        Workspace.init(destination, code_roots=[tmp_path / "code"], **reviewed_fixture)
    assert not destination.exists() and not list(tmp_path.glob(".cairn-init-*"))


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

    # A private-mode workspace must never take the synthetic inline extraction branch.
    def no_engine(*_: object, **__: object) -> bytes:
        raise Blocked("synthetic test intentionally disables engine")

    monkeypatch.setattr("cairn.ingest.service.invoke_worker", no_engine)
    with pytest.raises(Blocked, match="disables engine"):
        extract(ws, source.id, inline_synthetic=True)
    with pytest.raises(Denied, match="client image"):
        prepare_job(ws, source.id, scope_name="research", execution_image="sha256:" + "9" * 64)
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


def test_owner_activation_cli_and_doctor_distinguish_missing_probe(
    reviewed_fixture: dict,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "private-mode-fixture"
    runner = CliRunner()
    args = [
        "init",
        "--workspace",
        str(target),
        "--code-root",
        str(tmp_path / "code"),
        "--release",
        str(reviewed_fixture["release"]),
        "--release-sha256",
        reviewed_fixture["release_sha256"],
        "--statement",
        reviewed_fixture["statement"],
    ]
    for flag in sorted(REQUIRED_REVIEWS):
        args += ["--acknowledge", flag]
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    doctor = ["doctor", "--workspace", str(target), "--json"]
    report = json.loads(runner.invoke(app, doctor).stdout)
    assert report["runtime_verified"] and not report["private_ready"]
    assert report["worker_probe_status"] == "not_checked"
    result = runner.invoke(app, [*doctor, "--probe-worker"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["private_ready"]

    def unavailable(*_: object) -> bytes:
        raise Blocked("isolation_unavailable")

    monkeypatch.setattr(activation, "invoke_worker", unavailable)
    report = json.loads(runner.invoke(app, [*doctor, "--probe-worker"]).stdout)
    assert not report["private_ready"] and report["worker_probe_status"] == "isolation_unavailable"
