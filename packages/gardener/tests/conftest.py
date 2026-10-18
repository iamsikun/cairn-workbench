"""Keep every test away from the owner's home, configuration, credentials and knowledge base."""

import os
import sys
import tempfile

_SANDBOX = tempfile.mkdtemp(prefix="cairn-garden-tests-")
os.environ["HOME"] = os.path.join(_SANDBOX, "home")
os.makedirs(os.environ["HOME"])
for name in (
    "XDG_CONFIG_HOME",
    "XDG_DATA_HOME",
    "XDG_STATE_HOME",
    "CAIRN_WORKSPACE",
    "CAIRN_COLLECTION",
):
    os.environ.pop(name, None)
os.environ["CAIRN_WORKBENCH_CONFIG"] = os.path.join(_SANDBOX, "config.toml")
os.environ["CAIRN_GARDEN_STATE"] = os.path.join(_SANDBOX, "state")
os.environ["CAIRN_CATALOG_DIR"] = os.path.join(_SANDBOX, "catalog")
os.environ["CAIRN_ASTER"] = os.path.join(_SANDBOX, "no-aster")  # tests install a fake one
os.environ["ASTER_CONFIG"] = os.path.join(_SANDBOX, "aster.yaml")
os.environ["ASTER_DATA_DIR"] = os.path.join(_SANDBOX, "aster-data")
sys.path.insert(
    0, os.path.dirname(__file__)
)  # shared fixtures in test_regressions and test_workflows

import pytest  # noqa: E402 - after the sandbox is in place
from cairn_garden import engine as g  # noqa: E402
from cairn_garden import workflow as w  # noqa: E402


# Shared by the regression, workflow and Zotero tests; test_gardener.py has its own `ws`.
@pytest.fixture
def ws(tmp_path, monkeypatch):
    root = tmp_path / "kb"
    root.mkdir()
    (root / ".cairn").touch()
    for folder in ("papers", "topics", "notes"):
        (root / "research" / folder).mkdir(parents=True)
    monkeypatch.setenv("CAIRN_WORKSPACE", str(root))
    monkeypatch.setenv("CAIRN_CATALOG_DIR", str(tmp_path / "catalog"))
    monkeypatch.setattr(g, "CONFIG_FILE", tmp_path / "missing.toml")
    monkeypatch.setattr(g, "HOME", tmp_path / "history-home")
    monkeypatch.setattr(g, "BRIDGE_CREDENTIALS", tmp_path / "bridge" / "zotero-local.json")
    monkeypatch.setattr(g, "zotero_api_key", lambda: None)

    def no_network(*args, **kwargs):
        raise RuntimeError("external requests disabled in review tests")

    monkeypatch.setattr(g, "fetch_json", no_network)
    monkeypatch.setattr(g, "fetch_text", no_network)
    return root


@pytest.fixture
def setup(ws, monkeypatch):
    monkeypatch.setattr(w, "g", g)
    monkeypatch.setattr(g.ZoteroIndex, "load", lambda: None)
    monkeypatch.setattr(g, "zotero_alive", lambda: False)
    candidate = {
        "source": "catalog",
        "id": "one",
        "title": "New attention paper",
        "doi": "10.1234/one",
        "url": "https://doi.org/10.1234/one",
    }
    monkeypatch.setattr(
        g,
        "catalog_candidates",
        lambda *a, **k: {"available": True, "complete": True, "candidates": [candidate.copy()]},
    )
    for name in ("arxiv_candidates", "zotero_recent"):
        monkeypatch.setattr(
            g, name, lambda *a, **k: {"available": True, "complete": True, "candidates": []}
        )
    g.kb_open(g.config()).save(
        kind="topic", title="Research catalogs", body="Research discovery and maintenance."
    )
    return g.config()
