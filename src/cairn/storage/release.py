from __future__ import annotations

import importlib.metadata
import platform
import re
import sys
import sysconfig
from pathlib import Path

import cairn
from cairn.errors import Conflict, Denied
from cairn.ingest.service import read_source_file
from cairn.records.json import read_json
from cairn.records.models import digest
from cairn.records.release import NativeReleaseManifest, PackageManifest, ReleaseManifest
from cairn.storage.files import RootFS


def normalized_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def current_platform() -> str:
    return f"{sys.platform}-{platform.machine()}"


def requirements(manifest: PackageManifest) -> bytes:
    return "".join(
        f"{item.name}=={item.version} --hash=sha256:{item.sha256}\n" for item in manifest.artifacts
    ).encode()


def load_release(file: Path, *, expected_sha256: str) -> PackageManifest:
    raw = read_source_file(file)
    if digest(raw) != expected_sha256:
        raise Conflict("release manifest differs from the independently reviewed digest")
    value = read_json(raw)
    if isinstance(value, dict) and value.get("schema_version", 1) == 2:
        return NativeReleaseManifest.model_validate(value)
    return ReleaseManifest.model_validate(value)


def verify_bundle(directory: Path, *, expected_sha256: str) -> PackageManifest:
    fs = RootFS(directory)
    manifest = load_release(directory / "release.json", expected_sha256=expected_sha256)
    if digest(fs.read("uv.lock")) != manifest.lock_hash:
        raise Conflict("release dependency lock checksum mismatch")
    if fs.read("requirements.txt") != requirements(manifest):
        raise Conflict("release installation requirements differ from the manifest")
    expected = {f"wheels/{item.filename}" for item in manifest.artifacts}
    if set(fs.files("wheels")) != expected:
        raise Conflict("release wheelhouse inventory mismatch")
    for artifact in manifest.artifacts:
        if digest(fs.read(f"wheels/{artifact.filename}")) != artifact.sha256:
            raise Conflict("release wheel checksum mismatch")
    return manifest


def verify_runtime(manifest: PackageManifest) -> dict[str, str | int | bool]:
    """Check an owner-reviewed installation; this is not a host compromise detector."""
    if not sys.flags.isolated or not sys.dont_write_bytecode:
        raise Denied("reviewed runtime requires python -I -B -m cairn")
    if sys.prefix == sys.base_prefix:
        raise Denied("reviewed runtime requires a dedicated virtual environment")
    if (
        platform.python_version() != manifest.python_version
        or platform.python_implementation() != manifest.python_implementation
        or current_platform() != manifest.platform
        or digest(Path(sys.executable).resolve().read_bytes()) != manifest.python_executable_hash
    ):
        raise Denied("release interpreter or platform mismatch")
    site = Path(sysconfig.get_path("purelib")).resolve()
    if not site.is_relative_to(Path(sys.prefix).resolve()):
        raise Denied("site-packages lies outside the dedicated runtime")
    if cairn.__file__ is None or Path(cairn.__file__).resolve() != site / "cairn/__init__.py":
        raise Denied("Cairn was imported from a checkout or another environment")
    expected = {artifact.name: artifact for artifact in manifest.artifacts}
    files = dict(manifest.bootstrap_files)
    generated: set[str] = set()
    metadata_dirs: dict[str, str] = {}
    for name, artifact in expected.items():
        metadata = [
            path for path in artifact.installed_files if path.endswith(".dist-info/METADATA")
        ]
        if len(metadata) != 1:
            raise Denied("release distribution metadata unavailable")
        parent = metadata[0].rsplit("/", 1)[0]
        metadata_dirs[name] = parent
        generated.update(
            f"{parent}/{leaf}"
            for leaf in ("RECORD", "INSTALLER", "REQUESTED", "direct_url.json", "uv_cache.json")
        )
        files.update(artifact.installed_files)
    fs = RootFS(site)
    for path, checksum in files.items():
        if digest(fs.read(path)) != checksum:
            raise Conflict("installed package file differs from the reviewed wheel")
    installed = set()
    for child in site.iterdir():
        if child.is_dir() and not child.is_symlink():
            installed.update(fs.files(child.name))
        else:
            fs.read(child.name)  # Reject links and special files before inventory comparison.
            installed.add(child.name)
    if installed - set(files) - generated:
        raise Denied("unreviewed files or bytecode found in site-packages")
    # Only inspect distribution metadata after file/path preflight. In particular,
    # never follow an unreviewed metadata symlink using importlib's convenience API.
    distributions = list(importlib.metadata.distributions(path=[str(site)]))
    actual = {normalized_name(d.metadata["Name"]): d for d in distributions}
    if len(actual) != len(distributions) or set(actual) != set(expected):
        raise Denied("installed distribution inventory differs from the reviewed release")
    for name, artifact in expected.items():
        if actual[name].version != artifact.version:
            raise Denied("installed dependency version mismatch")
        path = f"{metadata_dirs[name]}/direct_url.json"
        if fs.exists(path):
            metadata_url = read_json(fs.read(path))
            if not isinstance(metadata_url, dict) or not isinstance(
                metadata_url.get("dir_info", {}), dict
            ):
                raise Denied("invalid installation origin metadata")
            if metadata_url.get("dir_info", {}).get("editable"):
                raise Denied("editable installations cannot process private data")
    result: dict[str, str | int | bool] = {
        "installation_verified": True,
        "code_revision": manifest.code_revision,
        "distributions": len(expected),
        "verified_files": len(files),
        "manifest_schema": manifest.schema_version,
    }
    if isinstance(manifest, ReleaseManifest):
        result.update(
            worker_image=manifest.worker_image,
            worker_profile_verified=False,
            private_ready=False,
        )
    return result
