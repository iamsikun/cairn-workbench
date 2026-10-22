"""The Studio's localhost server: the app's files, a read-only JSON API and change events.

    GET /                          the app
    GET /assets/<file>             its scripts and styles
    GET /api/collections           the collections that hold notes
    GET /api/recent?c=             counts and the latest notes
    GET /api/graph?c=              nodes and edges for the map
    GET /api/ideas?c=              the idea board
    GET /api/note?c=&slug=         one note, rendered
    GET /api/search?c=&q=&kind=    keyword search
    GET /api/events?c=             server-sent events: `change` when a note changes on disk
    /catalog/...                   the journal catalog, if cairn-catalog is installed (catalog.py)

It binds to 127.0.0.1 and answers only requests addressed to localhost, so another site
open in the browser cannot read the notes through it. It never writes notes; the only
write is a change to the catalog's preferences, posted by the catalog's own pages.
"""

from __future__ import annotations

import json
import mimetypes
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import ModuleType
from typing import Any
from urllib.parse import parse_qs, urlparse

from cairn.store import COLLECTIONS, KB, CairnError

from . import catalog, views

ASSETS = Path(__file__).resolve().with_name("assets")
POLL_SECONDS = 1.0
HEARTBEAT_SECONDS = 15.0
POLICY = (
    "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'{scripts}; "
    "connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)
SECURITY = {
    "Content-Security-Policy": POLICY.format(scripts=""),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}


def collections(root: Path, default: str) -> list[str]:
    """The default collection plus any other that holds notes; `cairn init` makes all three."""
    return [c for c in COLLECTIONS if c == default or any((root / c).glob("*/*.md"))]


class Handler(BaseHTTPRequestHandler):
    server: StudioServer

    def log_message(self, format: str, *args: Any) -> None:
        if self.server.verbose:
            super().log_message(format, *args)

    def do_GET(self) -> None:
        if not self._local():
            return self._send(421, b"Misdirected request", "text/plain")
        url = urlparse(self.path)
        args = {k: v[-1] for k, v in parse_qs(url.query).items()}
        if url.path == "/":
            return self._file(ASSETS / "index.html")
        if url.path.startswith("/assets/"):
            return self._file(ASSETS / url.path.removeprefix("/assets/"))
        if url.path == "/api/events":
            return self._events(args)
        if url.path == "/catalog" or url.path.startswith("/catalog/"):
            return self._catalog(url.path.removeprefix("/catalog").lstrip("/"), url.query)
        if url.path.startswith("/api/"):
            try:
                return self._json(200, self._api(url.path.removeprefix("/api/"), args))
            except CairnError as exc:
                return self._json(404, {"error": str(exc)})
        self._send(404, b"Not found", "text/plain")

    def do_POST(self) -> None:
        if not self._local():
            return self._send(421, b"Misdirected request", "text/plain")
        if urlparse(self.path).path != "/catalog/api/preferences" or not self.server.catalog:
            return self._send(404, b"Not found", "text/plain")
        # Only the catalog's pages, served from here, may change its preferences.
        port = self.server.server_address[1]
        origins = (f"http://127.0.0.1:{port}", f"http://localhost:{port}")
        kind = self.headers.get("Content-Type", "").split(";")[0]
        if self.headers.get("Origin") not in origins or kind != "application/json":
            return self._json(
                403, {"error": "Preferences can only be changed from the catalog pages."}
            )
        self._json(*self.server.catalog.save(self.headers.get("Content-Length"), self.rfile))

    def _local(self) -> bool:
        port = self.server.server_address[1]
        return self.headers.get("Host") in (f"127.0.0.1:{port}", f"localhost:{port}")

    def _kb(self, args: dict[str, str]) -> KB:
        return KB(self.server.root, args.get("c") or self.server.collection)

    def _api(self, name: str, args: dict[str, str]) -> Any:
        if name == "collections":
            return {
                "collections": collections(self.server.root, self.server.collection),
                "default": self.server.collection,
                "catalog": self.server.catalog is not None,
            }
        kb = self._kb(args)
        if name == "recent":
            return views.recent(kb)
        if name == "graph":
            return views.graph(kb)
        if name == "ideas":
            return views.ideas(kb)
        if name == "note":
            found = views.note(kb, args.get("slug", ""))
            if self.server.catalog is not None and found["kind"] == "paper":
                found["catalog"] = views.catalog_paper(
                    found["fields"], self.server.catalog.papers_with
                )
            return found
        if name == "search":
            return views.search(kb, args.get("q", ""), args.get("kind"))
        raise CairnError(f"no such view {name!r}")

    def _catalog(self, name: str, query: str) -> None:
        server = self.server.catalog
        if server is None:
            return self._send(404, b"The journal catalog is not installed", "text/plain")
        if not name:
            return self._redirect("/catalog/catalog.html")
        if name.startswith("api/"):
            return self._json(*server.answer("/" + name, parse_qs(query)))
        if name == "in-kb.json":
            args = {k: v[-1] for k, v in parse_qs(query).items()}
            try:
                return self._json(200, views.in_catalog(self._kb(args), server.papers_with))
            except CairnError as exc:
                return self._json(404, {"error": str(exc)})
        path = catalog.file(server.ROOT, name)
        if path is None:
            return self._send(404, b"Not found", "text/plain")
        body, headers = path.read_bytes(), {}
        if path.suffix == ".html":
            scripts = catalog.script_hashes(body)
            headers["Content-Security-Policy"] = POLICY.format(
                scripts=f" {scripts}" if scripts else ""
            )
        if catalog.immutable(name):
            headers["Cache-Control"] = "max-age=31536000, immutable"
        self._send(200, body, self._type(path), headers)

    def _events(self, args: dict[str, str]) -> None:
        try:
            kb = self._kb(args)
        except CairnError as exc:
            return self._json(404, {"error": str(exc)})
        self.send_response(200)
        self._headers({"Content-Type": "text/event-stream", "Cache-Control": "no-store"})
        last = views.signature(kb)
        quiet = 0.0
        try:
            self.wfile.write(f"event: ready\ndata: {last}\n\n".encode())
            self.wfile.flush()
            while not self.server.stopping:
                time.sleep(POLL_SECONDS)
                now = views.signature(kb)
                if now != last:
                    last, quiet = now, 0.0
                    self.wfile.write(f"event: change\ndata: {now}\n\n".encode())
                elif (quiet := quiet + POLL_SECONDS) >= HEARTBEAT_SECONDS:
                    quiet = 0.0
                    self.wfile.write(b": still here\n\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _file(self, path: Path) -> None:
        path = path.resolve()
        if path.parent != ASSETS or not path.is_file():
            return self._send(404, b"Not found", "text/plain")
        self._send(200, path.read_bytes(), self._type(path))

    @staticmethod
    def _type(path: Path) -> str:
        kind = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if kind.startswith("text/") or kind.endswith(("javascript", "json")):
            kind += "; charset=utf-8"
        return kind

    def _redirect(self, location: str) -> None:
        self.send_response(302)
        self._headers({"Location": location, "Content-Length": "0"})

    def _json(self, code: int, value: Any) -> None:
        body = json.dumps(value, ensure_ascii=False, default=str).encode()
        self._send(code, body, "application/json; charset=utf-8")

    def _send(
        self, code: int, body: bytes, kind: str, headers: dict[str, str] | None = None
    ) -> None:
        self.send_response(code)
        self._headers(
            {"Content-Type": kind, "Content-Length": str(len(body)), "Cache-Control": "no-store"}
            | (headers or {})
        )
        self.wfile.write(body)

    def _headers(self, headers: dict[str, str]) -> None:
        for key, value in (SECURITY | headers).items():
            self.send_header(key, value)
        self.end_headers()


class StudioServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        root: Path,
        collection: str,
        port: int = 0,
        verbose: bool = False,
        catalog: ModuleType | None = None,
    ):
        KB(root, collection)  # fail early on a folder that is not a knowledge base
        self.root, self.collection, self.verbose = root, collection, verbose
        self.catalog = catalog  # cairn_catalog.catalog_server, when it is installed and built
        self.stopping = False
        super().__init__(("127.0.0.1", port), Handler)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}/"

    def shutdown(self) -> None:
        self.stopping = True
        super().shutdown()
