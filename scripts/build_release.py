"""Build acquisition phase only: public source/locked artifacts, never private inputs.

Run in the development image with network only during this acquisition phase. The
separate release trial installs and exercises the resulting bundle with no network.
"""

import argparse
import io
import platform
import shutil
import subprocess
import sys
import tempfile
import tomllib
import urllib.parse
import urllib.request
import zipfile
from email.parser import BytesParser
from pathlib import Path

from packaging.markers import Marker
from packaging.tags import sys_tags
from packaging.utils import parse_wheel_filename

from cairn.records.models import canonical, digest
from cairn.records.release import ReleaseManifest, WheelArtifact
from cairn.storage.release import current_platform, normalized_name


def describe_wheel(file: Path) -> WheelArtifact:
    raw = file.read_bytes()
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        names = [item.filename for item in archive.infolist() if not item.is_dir()]
        if len(names) != len(set(names)):
            raise ValueError("duplicate wheel file")
        metadata_paths = [name for name in names if name.endswith(".dist-info/METADATA")]
        if len(metadata_paths) != 1:
            raise ValueError("wheel metadata unavailable")
        metadata = BytesParser().parsebytes(archive.read(metadata_paths[0]))
        return WheelArtifact(
            name=normalized_name(metadata["Name"]),
            version=metadata["Version"],
            filename=file.name,
            sha256=digest(raw),
            installed_files={
                name: digest(archive.read(name))
                for name in names
                if not name.endswith(".dist-info/RECORD")
            },
        )


def build(output: Path, revision: str, worker_image: str) -> None:
    if output.exists():
        raise ValueError("release output must be new")
    output.mkdir(parents=True)
    wheels = output / "wheels"
    wheels.mkdir()
    lock = Path("uv.lock").read_bytes()
    packages = {p["name"]: p for p in tomllib.loads(lock.decode())["package"]}
    required = {"cairn-workbench"}
    pending = ["cairn-workbench"]
    while pending:
        for dependency in packages[pending.pop()].get("dependencies", []):
            if "marker" in dependency and not Marker(dependency["marker"]).evaluate():
                continue
            name = dependency["name"]
            if name not in required:
                required.add(name)
                pending.append(name)
    tags = list(sys_tags())
    for name in sorted(required - {"cairn-workbench"}):
        choices = []
        for wheel in packages[name]["wheels"]:
            filename = urllib.parse.urlparse(wheel["url"]).path.rsplit("/", 1)[1]
            parsed_name, version, _, wheel_tags = parse_wheel_filename(filename)
            compatible = [tags.index(tag) for tag in wheel_tags if tag in tags]
            if compatible and parsed_name == name and str(version) == packages[name]["version"]:
                choices.append((min(compatible), filename, wheel))
        if not choices:
            raise ValueError(f"no locked wheel for target: {name}")
        _, filename, selected = min(choices, key=lambda item: item[0])
        url = urllib.parse.urlparse(selected["url"])
        if url.scheme != "https" or url.hostname != "files.pythonhosted.org":
            raise ValueError("unsupported acquisition host")
        with urllib.request.urlopen(selected["url"], timeout=60) as stream:
            raw = stream.read(selected["size"] + 1)
        if len(raw) != selected["size"] or f"sha256:{digest(raw)}" != selected["hash"]:
            raise ValueError("locked artifact hash/size mismatch")
        (wheels / filename).write_bytes(raw)
    with tempfile.TemporaryDirectory(prefix="cairn-wheel-build-") as temporary:
        subprocess.run(["uv", "build", "--wheel", "--out-dir", temporary], check=True)
        built = list(Path(temporary).glob("*.whl"))
        if len(built) != 1:
            raise ValueError("project build did not produce exactly one wheel")
        shutil.copyfile(built[0], wheels / built[0].name)
    artifacts = [describe_wheel(file) for file in sorted(wheels.iterdir())]
    if {item.name for item in artifacts} != required:
        raise ValueError("release artifacts differ from production dependency closure")
    with tempfile.TemporaryDirectory(prefix="cairn-release-bootstrap-") as temporary:
        bootstrap = Path(temporary) / "runtime"
        subprocess.run(
            [
                "uv",
                "venv",
                "--no-managed-python",
                "--no-python-downloads",
                "--python",
                sys.executable,
                str(bootstrap),
            ],
            check=True,
        )
        sites = list(bootstrap.glob("lib/python*/site-packages"))
        if len(sites) != 1:
            raise ValueError("unsupported bootstrap layout")
        bootstrap_files = {file.name: digest(file.read_bytes()) for file in sites[0].iterdir()}
    source_files = [
        Path("pyproject.toml"),
        Path("uv.lock"),
        *sorted(p for p in Path("src").rglob("*") if p.is_file() and "__pycache__" not in p.parts),
    ]
    manifest = ReleaseManifest(
        code_revision=revision,
        source_hash=digest(
            canonical({str(path): digest(path.read_bytes()) for path in source_files})
        ),
        lock_hash=digest(lock),
        python_version=platform.python_version(),
        python_implementation=platform.python_implementation(),
        python_executable_hash=digest(Path(sys.executable).resolve().read_bytes()),
        platform=current_platform(),
        worker_image=worker_image,
        artifacts=artifacts,
        bootstrap_files=bootstrap_files,
        adapters={
            "extraction": "1",
            "fake_provider": "fake-v1",
            "client_packet": "1",
            "library_catalog": "1",
            "weekly_feed": "1",
            "html_views": "cairn-view-v1",
            "quill_writing": "d6bc7de15d1779c58286cbdec1a54eec52bdef22",
            "finch_reading": "0.3.0",
            "html_renderer": digest(
                Path("src/cairn/presentation/resources/application.mjs").read_bytes()
            ),
            "streaming_backup": "zip64-v1",
        },
    )
    raw = canonical(manifest)
    (output / "release.json").write_bytes(raw)
    (output / "release.sha256").write_text(digest(raw) + "\n")
    (output / "requirements.txt").write_text(
        "".join(f"{item.name}=={item.version} --hash=sha256:{item.sha256}\n" for item in artifacts)
    )
    shutil.copyfile("uv.lock", output / "uv.lock")
    print(
        canonical(
            {"release_sha256": digest(raw), "wheels": len(artifacts), "platform": manifest.platform}
        ).decode(),
        end="",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--worker-image", required=True)
    args = parser.parse_args()
    build(args.output, args.revision, args.worker_image)
