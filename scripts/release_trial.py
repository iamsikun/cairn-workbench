"""Offline fresh-environment trial, run with synthetic files and executable scratch only."""

import json
import os
import subprocess
import sys
import sysconfig
from pathlib import Path

from cairn.records.models import canonical, digest
from cairn.storage.release import verify_bundle


def trial(bundle: Path) -> None:
    reviewed_hash = (bundle / "release.sha256").read_text().strip()
    manifest = verify_bundle(bundle, expected_sha256=reviewed_hash)
    root = Path("/runtime")
    runtime = root / "owner"
    env = dict(os.environ)
    env.update(
        UV_OFFLINE="1",
        UV_NO_CONFIG="1",
        UV_PYTHON_DOWNLOADS="never",
        UV_COMPILE_BYTECODE="0",
        PYTHONDONTWRITEBYTECODE="1",
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

    def cli(*args: str, status: int = 0) -> dict:
        completed = subprocess.run(
            [str(python), "-I", "-B", "-m", "cairn", *args],
            capture_output=True,
            env=env,
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
    assert verification["installation_verified"] and not verification["private_ready"]
    imported = (
        subprocess.run(
            [str(python), "-I", "-B", "-c", "import cairn; print(cairn.__file__)"],
            check=True,
            capture_output=True,
            env=env,
        )
        .stdout.decode()
        .strip()
    )
    assert Path(imported).is_relative_to(runtime)
    workspace = root / "synthetic-workspace"
    options = ("--workspace", str(workspace), "--json")
    cli("init", "--workspace", str(workspace), "--code-root", "/opt/cairn", "--synthetic")
    source_file = root / "synthetic-evidence.txt"
    source_file.write_text("Synthetic release evidence: exact value 42.\n")
    source = cli("capture", str(source_file), "--domain", "research", *options)
    proposal = cli("ingest", source["id"], "--scope", "research", "--inline-synthetic", *options)
    cli("validate", proposal["id"], *options)
    acknowledgements = [
        word for flag in proposal["review_flags"] for word in ("--acknowledge", flag)
    ]
    cli(
        "approve",
        proposal["id"],
        "--statement",
        "Reviewed this synthetic release trial.",
        *acknowledgements,
        *options,
    )
    cli("apply", proposal["id"], *options)
    answer = cli("query", "42", "--scope", "research", *options)
    assert "exact value 42" in answer["answer"]
    archive = root / "backup.zip"
    backed_up = cli("backup", str(archive), *options)
    restored = root / "restored"
    cli(
        "restore",
        str(archive),
        "--destination",
        str(restored),
        "--code-root",
        "/opt/cairn",
        "--expected-sha256",
        backed_up["sha256"],
        "--json",
    )
    assert (
        cli("query", "42", "--scope", "research", "--workspace", str(restored), "--json") == answer
    )

    # Actual installed files are tested, never package mocks or PYTHONPATH substitutions.
    site = runtime / "lib" / f"python{sysconfig.get_python_version()}" / "site-packages"
    module = site / "cairn/__init__.py"
    original = module.read_bytes()
    module.write_bytes(original + b"\n# synthetic modified installation\n")
    assert cli(*check_args, status=4)["error"] == "conflict"
    module.write_bytes(original)
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
    print(
        canonical(
            {
                "offline_installed_trial": "passed",
                "manifest_sha256": reviewed_hash,
                "code_revision": manifest.code_revision,
                "import_origin": imported,
                "distributions": verification["distributions"],
                "verified_files": verification["verified_files"],
                "synthetic_capture_approval_apply_query_restore": "passed",
                "modified_package_rejected": True,
                "unreviewed_pth_rejected": True,
                "editable_installation_rejected": True,
                "private_activation": "not_attempted",
                "model": "fake-v1",
            }
        ).decode(),
        end="",
    )


if __name__ == "__main__":
    trial(Path(sys.argv[1]))
