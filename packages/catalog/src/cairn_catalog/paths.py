"""Where the catalog keeps its data, its preferences, and which Cairn collection it serves.

Source files ship with the package; everything the catalog harvests or builds lives in the
data folder, outside the knowledge base. Environment variables override the shared config
file (~/.config/cairn-workbench/config.toml):

    workspace = "~/knowledge"          # or $CAIRN_WORKSPACE
    collection = "research"            # or $CAIRN_COLLECTION
    [catalog]
    data_dir = "..."                   # or $CAIRN_CATALOG_DIR
    preferences = "..."                # or $CAIRN_CATALOG_PREFERENCES
"""

from __future__ import annotations

import json
import os
import tomllib
from pathlib import Path

ASSETS = Path(__file__).resolve().with_name("assets")


def journals(root: Path) -> list[dict]:
    """The edition's journal registry snapshot, or the packaged registry for a new data folder."""
    path = root / "journals.json"
    return json.loads(
        (path if path.exists() else ASSETS / "journals.json").read_text(encoding="utf-8")
    )


def _home(variable: str, fallback: str) -> Path:
    return Path(os.environ.get(variable) or Path.home() / fallback).expanduser()


def config_file() -> Path:
    default = _home("XDG_CONFIG_HOME", ".config") / "cairn-workbench" / "config.toml"
    return Path(os.environ.get("CAIRN_WORKBENCH_CONFIG") or default).expanduser()


def settings() -> dict:
    path = config_file()
    return tomllib.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _setting(variable: str, key: str, section: str | None = None) -> str | None:
    if os.environ.get(variable):
        return os.environ[variable]
    values = settings()
    return (values.get(section) or {}).get(key) if section else values.get(key)


def data_dir() -> Path:
    value = _setting("CAIRN_CATALOG_DIR", "data_dir", "catalog")
    default = _home("XDG_DATA_HOME", ".local/share") / "cairn-workbench" / "catalog"
    return Path(value).expanduser() if value else default


def preferences_file() -> Path:
    value = _setting("CAIRN_CATALOG_PREFERENCES", "preferences", "catalog")
    return (
        Path(value).expanduser() if value else config_file().with_name("catalog-preferences.yaml")
    )


def workspace() -> Path | None:
    value = _setting("CAIRN_WORKSPACE", "workspace")
    return Path(value).expanduser() if value else None


def collection() -> str:
    return _setting("CAIRN_COLLECTION", "collection") or "research"
