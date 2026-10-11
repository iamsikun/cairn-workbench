"""Install a native release offline into disposable scratch and verify synthetic behavior."""

import json
import os
import subprocess
import sys
import sysconfig
import tempfile
from pathlib import Path

from cairn.records.models import canonical, digest
from cairn.storage.release import verify_bundle


def run_trial(bundle: Path, root: Path) -> None:
    reviewed_hash = (bundle / "release.sha256").read_text().strip()
    manifest = verify_bundle(bundle, expected_sha256=reviewed_hash)
    runtime = root / "owner"
    env = dict(os.environ)
    env.update(
        UV_OFFLINE="1",
        UV_NO_CONFIG="1",
        UV_PYTHON_DOWNLOADS="never",
        UV_COMPILE_BYTECODE="0",
        PYTHONDONTWRITEBYTECODE="1",
        # Synthetic workspaces only: owner commands run unattended in this trial.
        CAIRN_SYNTHETIC_OWNER="1",
    )
    env.pop("PYTHONPATH", None)
    subprocess.run(
        [
            "uv",
            "venv",
            "--offline",
            "--no-cache",
            "--no-managed-python",
            "--python",
            sys.executable,
            str(runtime),
        ],
        check=True,
        env=env,
    )
    python = runtime / "bin/python"
    subprocess.run(
        [
            "uv",
            "pip",
            "install",
            "--offline",
            "--no-cache",
            "--no-index",
            "--link-mode=copy",
            "--python",
            str(python),
            "--find-links",
            str(bundle / "wheels"),
            "--only-binary",
            ":all:",
            "--require-hashes",
            "-r",
            str(bundle / "requirements.txt"),
        ],
        check=True,
        env=env,
    )

    def cli(*args: str, status: int = 0, overrides: dict[str, str] | None = None) -> dict:
        completed = subprocess.run(
            [str(python), "-I", "-B", "-m", "cairn", "legacy", *args],
            capture_output=True,
            env={**env, **(overrides or {})},
            check=False,
        )
        if completed.returncode != status:
            raise AssertionError(completed.stderr.decode() or completed.stdout.decode())
        return json.loads(completed.stdout if status == 0 else completed.stderr)

    check_args = (
        "release",
        "check-runtime",
        str(bundle / "release.json"),
        "--sha256",
        reviewed_hash,
        "--json",
    )
    verification = cli(*check_args)
    assert verification["installation_verified"] and verification["manifest_schema"] == 2
    imported = subprocess.run(
        [str(python), "-I", "-B", "-c", "import cairn; print(cairn.__file__)"],
        check=True, capture_output=True, env=env,
    ).stdout.decode().strip()
    assert Path(imported).is_relative_to(runtime)
    from direct_trial import trial as direct_trial

    direct_report = direct_trial(python, env, root)
    # Retired execution reports an actionable error without creating a destination.
    denied_root = root / "activation-must-not-exist"
    denied = cli(
        "init", "--workspace", str(denied_root), "--code-root", str(root / "code"), status=5
    )
    assert denied["error"] == "blocked" and "retired" in denied["message"]
    assert not denied_root.exists()
    # Actual installed files are tested, never package mocks or PYTHONPATH substitutions.
    site = runtime / "lib" / f"python{sysconfig.get_python_version()}" / "site-packages"
    module = site / "cairn/__init__.py"
    original = module.read_bytes()
    module.write_bytes(original + b"\n# synthetic modified installation\n")
    assert cli(*check_args, status=4)["error"] == "conflict"
    module.write_bytes(original)
    renderer = site / "cairn/presentation/resources/application.mjs"
    saved_renderer = renderer.read_bytes()
    renderer.write_bytes(saved_renderer + b"\n// synthetic modification\n")
    assert cli(*check_args, status=4)["error"] == "conflict"
    renderer.write_bytes(saved_renderer)
    contract = site / "cairn/reading/contract.md"
    saved_contract = contract.read_bytes()
    contract.write_bytes(saved_contract + b"\nSynthetic changed reading contract\n")
    assert cli(*check_args, status=4)["error"] == "conflict"
    contract.write_bytes(saved_contract)
    extra = site / "synthetic-unreviewed.pth"
    extra.write_text("# synthetic inventory mismatch, no executable content\n")
    assert cli(*check_args, status=3)["error"] == "denied"
    extra.unlink()
    package = next(item for item in manifest.artifacts if item.name == manifest.product)
    metadata = next(
        path for path in package.installed_files if path.endswith(".dist-info/METADATA")
    )
    direct = site / metadata.rsplit("/", 1)[0] / "direct_url.json"
    saved = direct.read_bytes() if direct.exists() else None
    direct.write_bytes(canonical({"url": "file:///synthetic", "dir_info": {"editable": True}}))
    assert cli(*check_args, status=3)["error"] == "denied"
    if saved is None:
        direct.unlink()
    else:
        direct.write_bytes(saved)
    assert cli(*check_args)["installation_verified"]
    assert digest((bundle / "release.json").read_bytes()) == reviewed_hash
    print(canonical({
        "offline_installed_trial": "passed",
        "direct_save_installed_trial": direct_report,
        "manifest_schema": manifest.schema_version,
        "manifest_sha256": reviewed_hash,
        "code_revision": manifest.code_revision,
        "import_origin": imported,
        "distributions": verification["distributions"],
        "verified_files": verification["verified_files"],
        "modified_reading_contract_rejected": True,
        "modified_renderer_rejected": True,
        "modified_package_rejected": True,
        "unreviewed_pth_rejected": True,
        "editable_installation_rejected": True,
        "legacy_activation_retired": True,
        "network_isolation": "not_claimed; installation uses offline/no-index flags",
        "actual_clients": "unverified",
    }).decode(), end="")


def trial(bundle: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="cairn-native-release-") as temporary:
        run_trial(bundle.resolve(), Path(temporary).resolve())


if __name__ == "__main__":
    trial(Path(sys.argv[1]))
