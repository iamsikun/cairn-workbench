"""Machine-local updater state under CAIRN_HOME (default ~/.local/share/cairn).

Layout::

    updater.json           channel, signer keys and registered knowledge bases
    state.json             last check and the one-time update notice
    source.git/            bare mirror of the channel branch and its tags
    runtimes/<sha256>/     bundle/, venv/ and runtime.json (written last = complete)
    current -> runtimes/<sha256>
    backups/<workspace>/   pre-upgrade and pre-migration archives
    skills/<name>/         managed skill clones
"""

from __future__ import annotations

import fcntl
import json
import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from pydantic import Field

from cairn.errors import Conflict
from cairn.records.models import Digest, Model, canonical, now
from cairn.records.runtime import ReleaseTag, SignerLine

HOME_ENV = "CAIRN_HOME"
DEFAULT_REPOSITORY = "https://github.com/iamsikun/cairn-workbench.git"
DEFAULT_REF = "stable"


class Busy(Conflict):
    """Another updater holds the machine-wide update lock."""


class UpdaterConfig(Model):
    schema_version: int = 1
    repository: str = Field(default=DEFAULT_REPOSITORY, min_length=1, max_length=2048)
    ref: str = Field(default=DEFAULT_REF, pattern=r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,199}$")
    allowed_signers: list[SignerLine] = Field(min_length=1, max_length=32)
    workspaces: list[str] = Field(default_factory=list)
    enabled: bool = True
    interval_hours: int = Field(default=24, ge=1, le=168)
    # The owner's PATH at setup, so scheduled runs find git, uv and docker.
    path: str = Field(default="/usr/local/bin:/usr/bin:/bin", max_length=8192)


class UpdaterState(Model):
    schema_version: int = 1
    last_check: datetime | None = None
    last_result: str | None = None
    notice: str | None = None
    notice_shown: bool = True
    errors: list[str] = Field(default_factory=list)


class RuntimeInfo(Model):
    schema_version: int = 1
    release_tag: ReleaseTag
    commit: str = Field(pattern=r"^[0-9a-f]{40,64}$")
    release_sha256: Digest
    worker_image: str
    installed_at: datetime


@dataclass(frozen=True)
class Home:
    root: Path

    @classmethod
    def from_env(cls, environ: dict[str, str] | None = None) -> Home:
        env = os.environ if environ is None else environ
        configured = env.get(HOME_ENV)
        if configured:
            return cls(Path(configured).absolute())
        return cls(Path.home() / ".local" / "share" / "cairn")

    @property
    def config_path(self) -> Path:
        return self.root / "updater.json"

    @property
    def state_path(self) -> Path:
        return self.root / "state.json"

    @property
    def mirror(self) -> Path:
        return self.root / "source.git"

    @property
    def runtimes(self) -> Path:
        return self.root / "runtimes"

    @property
    def current(self) -> Path:
        return self.root / "current"

    @property
    def backups(self) -> Path:
        return self.root / "backups"

    @property
    def log(self) -> Path:
        return self.root / "update.log"

    def runtime(self, release_sha256: str) -> Path:
        return self.runtimes / release_sha256

    def python(self, release_sha256: str) -> Path:
        return self.runtime(release_sha256) / "venv" / "bin" / "python"

    def config(self) -> UpdaterConfig | None:
        if not self.config_path.is_file():
            return None
        return UpdaterConfig.model_validate_json(self.config_path.read_bytes())

    def save_config(self, config: UpdaterConfig) -> None:
        _write(self.config_path, canonical(config))

    def state(self) -> UpdaterState:
        if not self.state_path.is_file():
            return UpdaterState()
        try:
            return UpdaterState.model_validate_json(self.state_path.read_bytes())
        except ValueError:
            return UpdaterState()

    def save_state(self, state: UpdaterState) -> None:
        _write(self.state_path, canonical(state))

    def installed(self, release_sha256: str) -> RuntimeInfo | None:
        info = self.runtime(release_sha256) / "runtime.json"
        if not info.is_file():
            return None
        return RuntimeInfo.model_validate_json(info.read_bytes())

    def current_runtime(self) -> RuntimeInfo | None:
        if not self.current.is_symlink():
            return None
        return self.installed(Path(os.readlink(self.current)).name)

    def running_runtime(self) -> RuntimeInfo | None:
        """The managed runtime executing this process, if any."""
        prefix = Path(sys.prefix).resolve()
        if prefix.name != "venv" or prefix.parent.parent != self.runtimes.resolve():
            return None
        return self.installed(prefix.parent.name)

    def due(self, config: UpdaterConfig, state: UpdaterState) -> bool:
        return state.last_check is None or now() - state.last_check >= timedelta(
            hours=config.interval_hours
        )

    def set_current(self, release_sha256: str) -> None:
        temporary = self.root / f".current-{os.getpid()}"
        if temporary.is_symlink():
            temporary.unlink()
        os.symlink(self.runtime(release_sha256), temporary)
        os.replace(temporary, self.current)

    @contextmanager
    def lock(self) -> Iterator[None]:
        """Only one updater runs at a time; a concurrent run reports busy."""
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(self.root / "update.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise Busy("another update is running") from exc
            yield
        finally:
            os.close(fd)


def _write(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_bytes(raw)
    os.replace(temporary, path)


def bound_release(workspace: Path) -> str | None:
    """Read a workspace's bound release digest without opening or verifying it."""
    try:
        data = json.loads((workspace / "workspace.json").read_bytes())
    except (OSError, ValueError):
        return None
    value = data.get("runtime_release_hash") if isinstance(data, dict) else None
    return value if isinstance(value, str) and len(value) == 64 else None
