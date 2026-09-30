import platform
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from cairn.errors import Conflict, Denied
from cairn.records.models import canonical, digest
from cairn.records.release import ReleaseManifest, WheelArtifact
from cairn.storage.release import current_platform, requirements, verify_bundle, verify_runtime


def manifest() -> ReleaseManifest:
    return ReleaseManifest(
        code_revision="a" * 40,
        source_hash="1" * 64,
        lock_hash=digest(b"synthetic lock"),
        python_version=platform.python_version(),
        python_implementation=platform.python_implementation(),
        python_executable_hash=digest(Path(sys.executable).resolve().read_bytes()),
        platform=current_platform(),
        worker_image="sha256:" + "2" * 64,
        artifacts=[
            WheelArtifact(
                name="cairn-workbench",
                version="0.1.0",
                filename="cairn_workbench-0.1.0-py3-none-any.whl",
                sha256=digest(b"synthetic wheel"),
                installed_files={"cairn/__init__.py": "3" * 64},
            )
        ],
        bootstrap_files={},
        adapters={"fake_provider": "fake-v1"},
    )


def test_release_bundle_inventory_and_independent_hash(tmp_path: Path) -> None:
    release = manifest()
    (tmp_path / "wheels").mkdir()
    wheel = tmp_path / "wheels" / release.artifacts[0].filename
    wheel.write_bytes(b"synthetic wheel")
    (tmp_path / "uv.lock").write_bytes(b"synthetic lock")
    (tmp_path / "requirements.txt").write_bytes(requirements(release))
    raw = canonical(release)
    (tmp_path / "release.json").write_bytes(raw)
    assert verify_bundle(tmp_path, expected_sha256=digest(raw)) == release
    with pytest.raises(Conflict, match="independently reviewed"):
        verify_bundle(tmp_path, expected_sha256="0" * 64)
    wheel.write_bytes(b"changed wheel")
    with pytest.raises(Conflict, match="wheel checksum"):
        verify_bundle(tmp_path, expected_sha256=digest(raw))
    wheel.write_bytes(b"synthetic wheel")
    (tmp_path / "wheels/extra.whl").write_bytes(b"unexpected")
    with pytest.raises(Conflict, match="inventory"):
        verify_bundle(tmp_path, expected_sha256=digest(raw))
    (tmp_path / "wheels/extra.whl").unlink()
    (tmp_path / "requirements.txt").write_text("unreviewed-package\n")
    with pytest.raises(Conflict, match="requirements"):
        verify_bundle(tmp_path, expected_sha256=digest(raw))


def test_release_manifest_rejects_ambiguous_or_unsafe_artifacts() -> None:
    release = manifest()
    for changes in (
        {"filename": "../escape.whl"},
        {"name": "package\n--extra-index-url bad"},
        {"installed_files": {"../escape": "0" * 64}},
        {"installed_files": {"package.data/payload": "0" * 64}},
    ):
        with pytest.raises((ValidationError, Denied)):
            WheelArtifact.model_validate({**release.artifacts[0].model_dump(), **changes})
    with pytest.raises(ValidationError, match="duplicate release"):
        ReleaseManifest.model_validate({**release.model_dump(), "artifacts": release.artifacts * 2})


def test_checkout_invocation_cannot_claim_reviewed_runtime() -> None:
    with pytest.raises(Denied, match="python -I -B"):
        verify_runtime(manifest())
