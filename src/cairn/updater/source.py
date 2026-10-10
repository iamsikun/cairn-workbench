"""Verify a release tag in a local mirror of the update channel.

The tag must be an annotated tag whose SSH signature verifies against the owner's
allowed signers, whose embedded name matches its ref, and whose commit is on the
channel branch. Git runs without system/global configuration, so an owner's GPG
keyring or a changed `gpg.program` cannot satisfy the check.
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from cairn.errors import Blocked, Conflict, Denied
from cairn.records.models import canonical, digest
from cairn.records.runtime import tag_version

TAG = re.compile(r"^v(0|[1-9][0-9]{0,8})\.(0|[1-9][0-9]{0,8})\.(0|[1-9][0-9]{0,8})$")
SSH_SIGNATURE = b"-----BEGIN SSH SIGNATURE-----"
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


def git(repo: Path, *args: str, input: bytes | None = None, check: bool = True) -> bytes:
    try:
        completed = subprocess.run(
            ["git", "-C", str(repo), *args],
            input=input,
            env=git_environment(),
            capture_output=True,
            timeout=GIT_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Blocked("git unavailable or timed out") from exc
    if check and completed.returncode != 0:
        raise Blocked("git command failed: " + " ".join(args[:2]))
    return completed.stdout


def channel_ref(ref: str) -> str:
    return f"refs/remotes/origin/{ref}"


def fetch(mirror: Path, repository: str, ref: str) -> None:
    """Refresh a bare mirror of one channel branch and its tags; never a working tree."""
    if not (mirror / "HEAD").is_file():
        mirror.mkdir(parents=True, exist_ok=True)
        git(mirror, "init", "--quiet", "--bare")
    git(
        mirror,
        "fetch",
        "--quiet",
        "--prune",
        "--no-tags",
        repository,
        f"+refs/heads/{ref}:{channel_ref(ref)}",
        "+refs/tags/*:refs/tags/*",
    )


def candidates(mirror: Path, ref: str) -> list[str]:
    """Version tags reachable from the channel branch, newest first."""
    names = git(mirror, "tag", "--list", "v*", "--merged", channel_ref(ref)).decode().split()
    return sorted((name for name in names if TAG.match(name)), key=tag_version, reverse=True)


@dataclass(frozen=True)
class VerifiedRelease:
    tag: str
    commit: str
    signer: str
    source_hash: str


def _signer(mirror: Path, tag: str, allowed_signers: list[str]) -> str:
    if git(mirror, "cat-file", "-t", f"refs/tags/{tag}", check=False).strip() != b"tag":
        raise Denied("release tag must be an annotated, signed tag")
    raw = git(mirror, "cat-file", "tag", f"refs/tags/{tag}")
    header, _, _ = raw.partition(b"\n\n")
    fields = dict(line.split(b" ", 1) for line in header.splitlines() if b" " in line)
    if fields.get(b"type") != b"commit" or fields.get(b"tag") != tag.encode():
        raise Denied("release tag object does not name this tag and a commit")
    if raw.count(SSH_SIGNATURE) != 1:
        raise Denied("release tag lacks exactly one SSH signature")
    with tempfile.TemporaryDirectory(prefix="cairn-signers-") as temporary:
        signers = Path(temporary) / "allowed_signers"
        for line in allowed_signers:
            signers.write_text(line + "\n")
            if _verifies(mirror, tag, signers):
                return line
    raise Denied("release tag is not signed by an owner-authorized key")


def _verifies(mirror: Path, tag: str, signers: Path) -> bool:
    try:
        completed = subprocess.run(
            [
                "git",
                "-C",
                str(mirror),
                "-c",
                "gpg.format=ssh",
                "-c",
                "gpg.program=/bin/false",
                "-c",
                "gpg.x509.program=/bin/false",
                "-c",
                f"gpg.ssh.allowedSignersFile={signers}",
                "verify-tag",
                f"refs/tags/{tag}",
            ],
            env=git_environment(),
            capture_output=True,
            timeout=GIT_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Blocked("git or ssh-keygen unavailable for signature verification") from exc
    return completed.returncode == 0 and b'Good "git" signature' in completed.stderr


def source_hash(mirror: Path, commit: str) -> str:
    """Recompute the manifest source hash from the signed tree, not a working copy."""
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


def verify_release(mirror: Path, tag: str, ref: str, allowed_signers: list[str]) -> VerifiedRelease:
    if not TAG.match(tag):
        raise Denied("release tag must be vMAJOR.MINOR.PATCH")
    signer = _signer(mirror, tag, allowed_signers)
    commit = git(mirror, "rev-parse", "--verify", f"refs/tags/{tag}^{{commit}}").decode().strip()
    reachable = subprocess.run(
        ["git", "-C", str(mirror), "merge-base", "--is-ancestor", commit, channel_ref(ref)],
        env=git_environment(),
        capture_output=True,
        timeout=GIT_TIMEOUT,
        check=False,
    )
    if reachable.returncode != 0:
        raise Denied("release tag is not on the update channel branch")
    return VerifiedRelease(tag, commit, signer, source_hash(mirror, commit))
