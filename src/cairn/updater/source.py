"""Read Cairn releases from a local mirror of the update channel.

Like Finch and Quill, a release is the `stable` branch of the configured repository:
the owner bumps the version (in `pyproject.toml` and `src/cairn/__init__.py`), adds a
changelog entry, and fast-forwards `stable`. A commit is a release candidate only if
both version declarations agree on `MAJOR.MINOR.PATCH`, and it is adopted only when
that version is higher than the installed one and the commit builds on the installed
commit (stable is never force-pushed). Git runs without system or global configuration.
"""

from __future__ import annotations

import os
import re
import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path

from cairn.errors import Blocked, Conflict, Denied
from cairn.records.models import canonical, digest

VERSION = re.compile(r"^(0|[1-9][0-9]{0,8})\.(0|[1-9][0-9]{0,8})\.(0|[1-9][0-9]{0,8})$")
INIT_VERSION = re.compile(rb'^__version__ = "([^"\n]+)"$', re.MULTILINE)
GIT_TIMEOUT = 300
# Paths hashed by scripts/build_release.py into ReleaseManifest.source_hash.
SOURCE_PATHS = ("pyproject.toml", "uv.lock", "src")


def git_environment() -> dict[str, str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if key in ("PATH", "HOME", "TMPDIR", "LANG", "LC_ALL", "SSH_AUTH_SOCK")
    }
    return env | {
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_ASKPASS": "/bin/false",
    }


def _git(repo: Path, *args: str, input: bytes | None = None) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            ["git", "-C", str(repo), *args],
            input=input,
            env=git_environment(),
            capture_output=True,
            timeout=GIT_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Blocked("git unavailable or timed out") from exc


def git(repo: Path, *args: str, input: bytes | None = None) -> bytes:
    completed = _git(repo, *args, input=input)
    if completed.returncode != 0:
        raise Blocked("git command failed: " + " ".join(args[:2]))
    return completed.stdout


def channel_ref(ref: str) -> str:
    return f"refs/remotes/origin/{ref}"


def fetch(mirror: Path, repository: str, ref: str) -> None:
    """Refresh a bare mirror of the channel branch; never a working tree."""
    if not (mirror / "HEAD").is_file():
        mirror.mkdir(parents=True, exist_ok=True)
        git(mirror, "init", "--quiet", "--bare")
    refspec = f"+refs/heads/{ref}:{channel_ref(ref)}"
    git(mirror, "fetch", "--quiet", "--no-tags", repository, refspec)


def tag_for(version: str) -> str:
    return f"v{version}"


def release_version(mirror: Path, commit: str) -> str:
    """The release number declared by a commit; both declarations must agree."""
    try:
        project = tomllib.loads(git(mirror, "show", f"{commit}:pyproject.toml").decode())
        declared = project["project"]["version"]
    except (tomllib.TOMLDecodeError, KeyError, TypeError, UnicodeDecodeError) as exc:
        raise Conflict("release pyproject.toml declares no version") from exc
    package = INIT_VERSION.search(git(mirror, "show", f"{commit}:src/cairn/__init__.py"))
    if not isinstance(declared, str) or not VERSION.match(declared):
        raise Conflict("release version must be MAJOR.MINOR.PATCH")
    if package is None or package.group(1).decode() != declared:
        raise Conflict("pyproject.toml and src/cairn/__init__.py versions differ")
    return declared


def is_ancestor(mirror: Path, older: str, newer: str) -> bool:
    return _git(mirror, "merge-base", "--is-ancestor", older, newer).returncode == 0


def has_commit(mirror: Path, commit: str) -> bool:
    return _git(mirror, "cat-file", "-e", f"{commit}^{{commit}}").returncode == 0


@dataclass(frozen=True)
class ChannelRelease:
    tag: str
    commit: str
    source_hash: str


def source_hash(mirror: Path, commit: str) -> str:
    """Recompute the manifest source hash from the channel tree, not a working copy."""
    listing = git(mirror, "ls-tree", "-r", "-z", "--full-tree", commit, "--", *SOURCE_PATHS)
    entries = []
    for item in listing.split(b"\0"):
        if not item:
            continue
        meta, _, path = item.partition(b"\t")
        mode, kind, obj = meta.decode().split()
        name = path.decode()
        if kind != "blob" or mode not in ("100644", "100755"):
            raise Conflict("release source contains an unsupported tree entry")
        if "__pycache__" in name.split("/"):
            continue
        entries.append((name, obj))
    request = "".join(f"{obj}\n" for _, obj in entries).encode()
    output = git(mirror, "cat-file", "--batch", input=request)
    hashes: dict[str, str] = {}
    offset = 0
    for name, obj in entries:
        end = output.index(b"\n", offset)
        sha, kind, size = output[offset:end].decode().split()
        if sha != obj or kind != "blob":
            raise Conflict("release source object mismatch")
        start = end + 1
        hashes[name] = digest(output[start : start + int(size)])
        offset = start + int(size) + 1
    return digest(canonical(hashes))


def channel_head(mirror: Path, ref: str) -> ChannelRelease:
    commit = git(mirror, "rev-parse", "--verify", f"{channel_ref(ref)}^{{commit}}").decode().strip()
    return ChannelRelease(
        tag_for(release_version(mirror, commit)), commit, source_hash(mirror, commit)
    )


def verify_release(mirror: Path, commit: str, ref: str, tag: str) -> ChannelRelease:
    """Check that a commit is on the channel branch and declares the expected release."""
    if not has_commit(mirror, commit) or not is_ancestor(mirror, commit, channel_ref(ref)):
        raise Denied("release commit is not on the update channel branch")
    if tag_for(release_version(mirror, commit)) != tag:
        raise Denied("release commit does not declare the expected version")
    return ChannelRelease(tag, commit, source_hash(mirror, commit))
