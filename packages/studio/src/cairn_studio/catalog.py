"""The journal catalog inside the Studio, when cairn-catalog is installed and its pages are built.

    GET  /catalog/                  the catalog's What's New page
    GET  /catalog/<file>            its pages, offline bundles and guides, from its data folder
    GET  /catalog/api/<name>        its read-only SQLite API, as `cairn-catalog serve` answers it
    POST /catalog/api/preferences   one change to the catalog preferences, from these pages only
    GET  /catalog/in-kb.json?c=     catalog papers that have a paper note in the collection

The catalog's data and preferences stay in its own folders, outside the knowledge base.
"""

from __future__ import annotations

import base64
import hashlib
import re
import threading
from pathlib import Path
from types import ModuleType
from urllib.parse import unquote

INLINE_SCRIPT = re.compile(rb"<script>(.*?)</script>", re.S)
# What the pages load: the pages and guides beside them, each edition's bundles (named after
# the edition, never changed) and the library's paper notes. Raw evidence, such as publisher
# pages kept as fetched, is never served.
SERVED = re.compile(
    r"^(?:[^/]+\.(?:html|js|css|md)|catalog-assets-[^/]+/[^/]+\.(?:js|css)|cairn-library/.+\.md)$"
)
IMMUTABLE = re.compile(r"^catalog-assets-[^/]+/")


def load() -> ModuleType | None:
    """The catalog's server module, or None when cairn-catalog is absent or has no pages yet."""
    try:
        from cairn_catalog import catalog_server
    except ImportError:
        return None
    return catalog_server if (catalog_server.ROOT / "catalog.html").is_file() else None


def warm(server: ModuleType) -> None:
    """Refresh the catalog's personal matches in the background, as `cairn-catalog serve` does."""
    threading.Thread(target=server.warm_preferences, daemon=True).start()


def file(root: Path, name: str) -> Path | None:
    """A file the catalog pages load, inside the data folder; never data or anything above it."""
    name = unquote(name)
    if not name or any(part.startswith(".") for part in name.split("/")):
        return None
    root = root.resolve()
    path = (root / name).resolve()
    if not SERVED.match(name) or not path.is_relative_to(root) or not path.is_file():
        return None
    return path


def immutable(name: str) -> bool:
    return bool(IMMUTABLE.match(unquote(name)))


def script_hashes(page: bytes) -> str:
    """CSP sources for a page's inline scripts: the catalog carries its edition's settings inline."""
    return " ".join(
        "'sha256-" + base64.b64encode(hashlib.sha256(script).digest()).decode() + "'"
        for script in INLINE_SCRIPT.findall(page)
    )
