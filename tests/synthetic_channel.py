"""A local synthetic update channel: throwaway SSH signing keys and signed tags.

No real keys, remotes or homes are involved; every repository lives under tmp_path.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

IDENTITY = ("-c", "user.name=Synthetic", "-c", "user.email=synthetic@example.invalid")


def env(tmp_path: Path) -> dict[str, str]:
    return {
        "HOME": str(tmp_path),
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
    }


def signing_key(tmp_path: Path, name: str) -> tuple[Path, str]:
    """Return a private key path and its allowed-signers line."""
    key = tmp_path / f"synthetic-{name}-key"
    subprocess.run(
        ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", name, "-f", str(key)],
        check=True,
        capture_output=True,
    )
    public = key.with_suffix(".pub").read_text().split()
    return key, f'{name}@example.invalid namespaces="git" {public[0]} {public[1]}'


@dataclass
class Channel:
    root: Path
    work: Path
    key: Path
    signer: str
    files: dict[str, bytes] = field(default_factory=dict)

    def git(self, *args: str) -> str:
        completed = subprocess.run(
            ["git", *IDENTITY, *args],
            cwd=self.work,
            env=env(self.root),
            check=True,
            capture_output=True,
        )
        return completed.stdout.decode().strip()

    def commit(self, files: dict[str, bytes], message: str = "Synthetic release") -> str:
        for name, raw in files.items():
            path = self.work / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        self.files.update(files)
        self.git("add", "-A")
        self.git("commit", "-qm", message)
        return self.git("rev-parse", "HEAD")

    def tag(self, name: str, *, key: Path | None = None, signed: bool = True) -> str:
        if signed:
            self.git(
                "-c",
                "gpg.format=ssh",
                "-c",
                f"user.signingkey={key or self.key}",
                "tag",
                "-s",
                name,
                "-m",
                f"Synthetic {name}",
            )
        else:
            self.git("tag", name)
        return self.git("rev-parse", f"{name}^{{commit}}")


def channel(tmp_path: Path, branch: str = "stable") -> Channel:
    work = tmp_path / "synthetic-cairn-source"
    work.mkdir()
    key, signer = signing_key(tmp_path, "owner")
    result = Channel(tmp_path, work, key, signer)
    result.git("init", "-q", "-b", branch)
    result.commit(
        {
            "pyproject.toml": b'[project]\nname = "cairn-workbench"\nversion = "0.2.0"\n',
            "uv.lock": b"# synthetic lock\n",
            "src/cairn/__init__.py": b'__version__ = "0.2.0"\n',
            "README.md": b"Synthetic channel; not hashed.\n",
        }
    )
    return result
