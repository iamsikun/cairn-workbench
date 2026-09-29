from __future__ import annotations

import os
import stat
import unicodedata
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from uuid import uuid4

from cairn.errors import Conflict, Denied

MAX_FILE_BYTES = 32 * 1024 * 1024


def disjoint(a: Path, b: Path) -> bool:
    a, b = a.resolve(), b.resolve()
    return a != b and a not in b.parents and b not in a.parents


def components(relative: str) -> tuple[str, ...]:
    path = PurePosixPath(relative)
    if (
        not relative
        or path.is_absolute()
        or "\\" in relative
        or any(ord(c) < 32 or ord(c) == 127 for c in relative)
        or any(part in ("", ".", "..") for part in relative.split("/"))
        or unicodedata.normalize("NFC", relative) != relative
    ):
        raise Denied("unsafe relative path")
    return path.parts


class RootFS:
    """Descriptor-relative operations: no symlinks or hard links at any component."""

    def __init__(self, root: Path):
        self.root = root.resolve(strict=True)

    @contextmanager
    def parent(self, relative: str, *, create: bool = False) -> Iterator[tuple[int, str]]:
        parts = components(relative)
        fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for part in parts[:-1]:
                self._collision(fd, part)
                if create:
                    try:
                        os.mkdir(part, mode=0o700, dir_fd=fd)
                        os.fsync(fd)
                    except FileExistsError:
                        pass
                next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = next_fd
            self._collision(fd, parts[-1])
            yield fd, parts[-1]
        except (NotADirectoryError, OSError) as exc:
            if isinstance(exc, FileNotFoundError):
                raise
            raise Denied("unsafe or inaccessible workspace path") from exc
        finally:
            os.close(fd)

    @staticmethod
    def _collision(fd: int, name: str) -> None:
        key = unicodedata.normalize("NFC", name).casefold()
        for sibling in os.listdir(fd):
            if sibling != name and unicodedata.normalize("NFC", sibling).casefold() == key:
                raise Denied("ambiguous case or Unicode path")

    @staticmethod
    def _regular(info: os.stat_result) -> None:
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise Denied("only regular files with one link are supported")

    def read(self, relative: str, *, limit: int = MAX_FILE_BYTES) -> bytes:
        with self.parent(relative) as (fd, name):
            file_fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
            with os.fdopen(file_fd, "rb") as stream:
                info = os.fstat(stream.fileno())
                self._regular(info)
                if info.st_size > limit:
                    raise Denied("file exceeds size limit")
                data = stream.read(limit + 1)
                if len(data) > limit:
                    raise Denied("file exceeds size limit")
                return data

    def exists(self, relative: str) -> bool:
        try:
            with self.parent(relative) as (fd, name):
                self._regular(os.stat(name, dir_fd=fd, follow_symlinks=False))
            return True
        except FileNotFoundError:
            return False

    def write(self, relative: str, data: bytes, *, exclusive: bool = False) -> None:
        if len(data) > MAX_FILE_BYTES:
            raise Denied("file exceeds size limit")
        with self.parent(relative, create=True) as (fd, name):
            try:
                self._regular(os.stat(name, dir_fd=fd, follow_symlinks=False))
                if exclusive:
                    raise Conflict("object already exists")
            except FileNotFoundError:
                pass
            temporary = f".tmp_{uuid4().hex}"
            file_fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=fd)
            try:
                with os.fdopen(file_fd, "wb") as stream:
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, name, src_dir_fd=fd, dst_dir_fd=fd)
                os.fsync(fd)
            finally:
                try:
                    os.unlink(temporary, dir_fd=fd)
                except FileNotFoundError:
                    pass

    def remove(self, relative: str) -> None:
        with self.parent(relative) as (fd, name):
            self._regular(os.stat(name, dir_fd=fd, follow_symlinks=False))
            os.unlink(name, dir_fd=fd)
            os.fsync(fd)

    def files(self, prefix: str) -> list[str]:
        components(prefix)
        result: list[str] = []

        # Walk through directory descriptors so swapping a directory for a symlink
        # cannot change the directory being traversed between validation and access.
        def walk(fd: int, path: str) -> None:
            seen: set[str] = set()
            for name in sorted(os.listdir(fd)):
                key = unicodedata.normalize("NFC", name).casefold()
                if key in seen:
                    raise Denied("ambiguous directory entries")
                seen.add(key)
                components(name)
                info = os.stat(name, dir_fd=fd, follow_symlinks=False)
                child = f"{path}/{name}"
                if stat.S_ISDIR(info.st_mode):
                    child_fd = os.open(
                        name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd
                    )
                    try:
                        walk(child_fd, child)
                    finally:
                        os.close(child_fd)
                else:
                    self._regular(info)
                    if not name.startswith(".tmp_"):
                        result.append(child)

        try:
            with self.parent(f"{prefix}/sentinel") as (fd, _):
                walk(fd, prefix)
        except FileNotFoundError:
            return []
        return result
