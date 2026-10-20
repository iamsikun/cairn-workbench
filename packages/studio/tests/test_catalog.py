import base64
import hashlib
import json
import sqlite3
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest
from cairn_catalog import catalog_server
from cairn_studio import catalog, server, views
from sample import build

from cairn.store import KB

CONFIG = b"window.CAIRN_CONFIG={};"
PAGE = b"<!doctype html><script>" + CONFIG + b'</script><script src="x.js"></script>'


@pytest.fixture
def kb(tmp_path: Path) -> KB:
    return build(tmp_path / "kb")


@pytest.fixture
def journals(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A built catalog with three DOIs: one an arXiv DOI, one an alternate of the first paper."""
    root = tmp_path / "catalog"
    (root / "catalog-assets-v1").mkdir(parents=True)
    (root / "raw").mkdir()
    (root / "catalog.html").write_bytes(PAGE)
    (root / "catalog-assets-v1" / "catalog-ui.js").write_text("// ui")
    (root / "README.md").write_text("# Catalog guide")
    (root / "raw" / "page.js").write_text("// raw evidence")
    (root / ".secret.js").write_text("// hidden")
    with sqlite3.connect(root / "catalog.sqlite") as con:
        con.execute("CREATE TABLE paper_dois(doi TEXT PRIMARY KEY, paper_id TEXT, is_primary INT)")
        con.executemany(
            "INSERT INTO paper_dois VALUES(?,?,?)",
            [
                ("10.1073/pnas.1804597116", "pnas-meta", 1),
                ("10.1073/pnas.alternate", "pnas-meta", 0),
                ("10.48550/arxiv.2305.05065", "tiger", 1),
                ("10.1000/unread", "unread", 1),
            ],
        )
    con.close()
    monkeypatch.setattr(catalog_server, "ROOT", root)
    return catalog_server


def test_catalog_is_offered_only_once_its_pages_are_built(journals, tmp_path: Path) -> None:
    assert catalog.load() is journals
    (tmp_path / "catalog" / "catalog.html").unlink()
    assert catalog.load() is None


def test_catalog_papers_in_the_knowledge_base_are_matched_by_doi_or_arxiv_id(
    kb: KB, journals
) -> None:
    marks = views.in_catalog(kb, journals.papers_with)["papers"]
    assert marks == {
        "pnas-meta": {
            "slug": "meta-learners-for-heterogeneous-treatment-effects",
            "title": "Meta-learners for heterogeneous treatment effects",
        },
        "tiger": {
            "slug": "tiger-recommender-systems-with-generative-retrieval",
            "title": "TIGER: Recommender Systems with Generative Retrieval",
        },
    }
    assert journals.papers_with([]) == {}


def test_only_pages_and_guides_inside_the_data_folder_are_served(tmp_path: Path) -> None:
    root = tmp_path / "data"
    (root / "catalog-assets-v1").mkdir(parents=True)
    (root / "raw").mkdir()
    (root / "cairn-library" / "research" / "papers").mkdir(parents=True)
    for name in [
        "catalog.html",
        "catalog-assets-v1/a.js",
        "catalog.sqlite",
        ".hidden.js",
        "raw/publisher-page.html",
        "cairn-library/research/papers/p.md",
    ]:
        (root / name).write_text("x")
    (tmp_path / "outside.js").write_text("x")
    assert catalog.file(root, "catalog.html") == (root / "catalog.html").resolve()
    assert catalog.file(root, "catalog-assets-v1/a.js")
    assert catalog.file(root, "cairn-library/research/papers/p.md")
    for name in [
        "catalog.sqlite",
        ".hidden.js",
        "raw/publisher-page.html",
        "../outside.js",
        "%2e%2e/outside.js",
        "catalog-assets-v1/../../outside.js",
        "",
    ]:
        assert catalog.file(root, name) is None
    assert catalog.immutable("catalog-assets-v1/a.js") and not catalog.immutable("catalog.html")


@pytest.fixture
def studio(kb: KB, journals):
    app = server.StudioServer(kb.root, "research", catalog=journals)
    threading.Thread(target=app.serve_forever, daemon=True).start()
    yield app
    app.shutdown()
    app.server_close()


def request(app, path: str, body: bytes | None = None, headers: dict[str, str] | None = None):
    req = urllib.request.Request(app.url.rstrip("/") + path, data=body, headers=headers or {})
    opener = urllib.request.build_opener(NoRedirect)
    try:
        with opener.open(req, timeout=5) as response:
            return response.status, dict(response.headers), response.read()
    except urllib.error.HTTPError as error:
        return error.code, dict(error.headers), error.read()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def test_studio_serves_the_catalog_pages_under_their_own_policy(studio) -> None:
    status, headers, _ = request(studio, "/catalog/")
    assert status == 302 and headers["Location"] == "/catalog/catalog.html"
    status, headers, body = request(studio, "/catalog/catalog.html")
    assert status == 200 and body == PAGE
    digest = base64.b64encode(hashlib.sha256(CONFIG).digest()).decode()
    assert f"script-src 'self' 'sha256-{digest}';" in headers["Content-Security-Policy"]
    status, headers, _ = request(studio, "/catalog/catalog-assets-v1/catalog-ui.js")
    assert status == 200 and "immutable" in headers["Cache-Control"]
    assert headers["Content-Security-Policy"] == server.SECURITY["Content-Security-Policy"]
    assert request(studio, "/catalog/README.md")[0] == 200
    for path in ["catalog.sqlite", "raw/page.js", ".secret.js", "..%2fcatalog.html"]:
        assert request(studio, "/catalog/" + path)[0] == 404, path
    assert request(studio, "/catalog/catalog.html", headers={"Host": "evil.example"})[0] == 421
    _, _, body = request(studio, "/api/collections")
    assert json.loads(body)["catalog"] is True


def test_studio_answers_the_catalog_api_and_marks_papers_in_the_knowledge_base(
    studio, journals, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(journals, "api", lambda path, args: {"path": path, "args": args})
    status, _, body = request(studio, "/catalog/api/papers?query=x")
    assert status == 200 and json.loads(body) == {"path": "/api/papers", "args": {"query": ["x"]}}
    status, _, body = request(studio, "/catalog/in-kb.json?c=research")
    assert status == 200 and set(json.loads(body)["papers"]) == {"pnas-meta", "tiger"}
    assert request(studio, "/catalog/in-kb.json?c=elsewhere")[0] == 404


def test_only_the_catalog_pages_change_its_preferences(
    studio, journals, monkeypatch: pytest.MonkeyPatch
) -> None:
    changes = []
    monkeypatch.setattr(
        journals, "save_preferences", lambda c: changes.append(c) or {"personal": None}
    )
    change = json.dumps({"action": "keyword", "value": "uplift"}).encode()
    kind = {"Content-Type": "application/json"}
    origin = {"Origin": studio.url.rstrip("/"), **kind}
    assert request(studio, "/catalog/api/preferences", change, kind)[0] == 403
    elsewhere = {"Origin": "http://evil.example", **kind}
    assert request(studio, "/catalog/api/preferences", change, elsewhere)[0] == 403
    assert request(studio, "/api/preferences", change, origin)[0] == 404
    status, _, body = request(studio, "/catalog/api/preferences", change, origin)
    assert status == 200 and json.loads(body) == {"personal": None}
    assert changes == [{"action": "keyword", "value": "uplift"}]


def test_without_the_catalog_the_studio_says_so(kb: KB) -> None:
    app = server.StudioServer(kb.root, "research")
    threading.Thread(target=app.serve_forever, daemon=True).start()
    try:
        status, _, body = request(app, "/catalog/")
        assert status == 404 and b"not installed" in body
        assert json.loads(request(app, "/api/collections")[2])["catalog"] is False
        change = b"{}"
        origin = {"Origin": app.url.rstrip("/"), "Content-Type": "application/json"}
        assert request(app, "/catalog/api/preferences", change, origin)[0] == 404
    finally:
        app.shutdown()
        app.server_close()
