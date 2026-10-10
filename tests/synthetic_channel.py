"""A local synthetic update channel shaped like Cairn's: versioned commits on `stable`.

No real remotes or homes are involved; every repository lives under tmp_path.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

IDENTITY = ("-c", "user.name=Synthetic", "-c", "user.email=synthetic@example.invalid")


def env(tmp_path: Path) -> dict[str, str]:
    return {
        "HOME": str(tmp_path),
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
    }


def version_files(version: str, package: str | None = None) -> dict[str, bytes]:
    return {
        "pyproject.toml": f'[project]\nname = "cairn-workbench"\nversion = "{version}"\n'.encode(),
        "src/cairn/__init__.py": f'__version__ = "{package or version}"\n'.encode(),
    }


@dataclass
class Channel:
    root: Path
    work: Path

    def git(self, *args: str) -> str:
        completed = subprocess.run(
            ["git", *IDENTITY, *args],
            cwd=self.work,
            env=env(self.root),
            check=True,
            capture_output=True,
        )
        return completed.stdout.decode().strip()

    def commit(self, files: dict[str, bytes], message: str = "Synthetic change") -> str:
        for name, raw in files.items():
            path = self.work / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        self.git("add", "-A")
        self.git("commit", "-qm", message)
        return self.git("rev-parse", "HEAD")

    def release(self, version: str, extra: dict[str, bytes] | None = None) -> str:
        """Bump the release number (and optionally other files) and commit."""
        return self.commit(version_files(version) | (extra or {}), f"Release {version}")


def channel(tmp_path: Path, branch: str = "stable") -> Channel:
    work = tmp_path / "synthetic-cairn-source"
    work.mkdir()
    result = Channel(tmp_path, work)
    result.git("init", "-q", "-b", branch)
    result.commit(
        version_files("0.1.0")
        | {
            "uv.lock": b"# synthetic lock\n",
            "src/cairn/cli.py": b"VALUE = 1\n",
            "README.md": b"Synthetic channel; not hashed.\n",
        },
        "Synthetic 0.1.0",
    )
    return result
