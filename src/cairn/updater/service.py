"""Retired managed updater. These entrypoints never read state or start acquisition."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from typing import Any

from cairn.adapters.legacy import retired
from cairn.updater.home import Home, RuntimeInfo, UpdaterConfig
from cairn.updater.source import ChannelRelease

type Runner = Callable[..., subprocess.CompletedProcess[bytes]]


def install(
    home: Home, release: ChannelRelease, config: UpdaterConfig, runner: Runner
) -> RuntimeInfo:
    retired("Managed runtime installation")


def run(
    home: Home, *, if_due: bool = False, runner: Runner = subprocess.run
) -> dict[str, Any]:
    retired("Managed automatic updates")
