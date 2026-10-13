"""Local writes, durable retry behavior, and the unattended-write release gate."""

import copy
import json
import subprocess
from pathlib import Path

import pytest
from cairn_garden.zotero_local import LocalWriter, bridge_hash, package
from test_regressions import g, invoke, save_paper
from test_workflows import draft, w


class Bridge:
    def __init__(self):
        self.status = {"build": bridge_hash(), "user_id": 1}
        self.items = {}
        self.calls = []
        self.lose_response = False

    def request(self, op, **args):
        self.calls.append((op, copy.deepcopy(args)))
        key = args["key"]
        if op == "create":
            identity = args["identity"]
            matches = [k for k, v in self.items.items() if identity in g.item_ids(v)]
            key = matches[0] if matches else key
        created = key not in self.items
        if created:
            self.items[key] = {**args["data"], "collections": []}
        before = list(self.items[key]["collections"])
        self.items[key]["collections"] = sorted(set(before) | set(args["collections"]))
        value = {
            "key": key,
            "created": created,
            "changed": created or before != self.items[key]["collections"],
            "before_collections": before,
            "data": copy.deepcopy(self.items[key]),
        }
        if self.lose_response:
            self.lose_response = False
            raise TimeoutError("response lost after commit")
        return value

    verify = LocalWriter.verify


@pytest.fixture
def bridge(ws, monkeypatch):
    b = Bridge()
    monkeypatch.setattr(
        g, "DEFAULTS", {**g.DEFAULTS, "zotero_backend": "local", "zotero_user_id": 1}
    )
    monkeypatch.setattr(g, "zotero_writer", lambda cfg: (b, "local", None))
    monkeypatch.setattr(
        g, "zotero_get", lambda route: {"data": copy.deepcopy(b.items[route.split("/")[-1]])}
    )
    monkeypatch.setattr(
        g.ZoteroIndex,
        "load",
        lambda: g.ZoteroIndex(
            [{"key": k, "data": copy.deepcopy(v)} for k, v in b.items.items()],
            [{"key": "COLLECTA", "data": {"name": "Transformers"}}],
        ),
    )
    monkeypatch.setattr(
        g,
        "remote_metadata",
        lambda ident: {
            "itemType": "preprint",
            "title": "Verified paper",
            "url": "https://arxiv.org/abs/" + ident.split(":", 1)[1],
        },
    )
    return b


def test_local_import_then_rerun_is_noop(bridge):
    save_paper()
    first = invoke("zotero-sync")
    assert first["backend"] == "local" and first["done"][0]["verified"]
    assert first["done"][0]["status"] == "created"
    assert invoke("zotero-sync")["done"] == []
    assert len(bridge.items) == len(bridge.calls) == 1


def test_lost_response_reconciles_without_repeating_creation(bridge):
    save_paper()
    bridge.lose_response = True
    assert invoke("zotero-sync")["failed"]
    assert not invoke("zotero-sync")["failed"]
    assert len(bridge.items) == len(bridge.calls) == 1


def test_failure_before_commit_retries_same_persisted_key(bridge, monkeypatch):
    save_paper()
    actual = bridge.request
    attempted = []

    def request(op, **args):
        attempted.append(args["key"])
        if len(attempted) == 1:
            raise TimeoutError("connection failed before commit")
        return actual(op, **args)

    monkeypatch.setattr(bridge, "request", request)
    assert invoke("zotero-sync")["failed"]
    assert invoke("zotero-sync")["done"][0]["status"] == "created"
    assert attempted[0] == attempted[1]


def test_local_add_preserves_memberships_metadata_and_does_not_import(bridge):
    save_paper()
    before = {
        "itemType": "preprint",
        "title": "User title",
        "url": "https://arxiv.org/abs/1706.03762",
        "collections": ["COLLECTB"],
        "creators": [{"name": "Author", "creatorType": "author"}],
        "extra": "User notes",
    }
    bridge.items["PAPERAAA"] = copy.deepcopy(before)
    result = invoke("zotero-sync")
    assert result["done"][0]["operation"] == "add" and result["done"][0]["verified"]
    assert bridge.items["PAPERAAA"] == {**before, "collections": ["COLLECTA", "COLLECTB"]}
    assert len(bridge.items) == 1


def test_local_read_back_failure_not_reported_done(bridge, monkeypatch):
    save_paper()
    monkeypatch.setattr(g, "zotero_get", lambda route: {"data": {"collections": []}})
    result = invoke("zotero-sync")
    assert result["failed"] and not result["done"]


def test_dry_run_and_zero_budget_never_call_writer(bridge):
    save_paper()
    assert invoke("zotero-sync", "--dry-run")["to_create"]
    assert not invoke("zotero-sync", "--limit", "0")["done"]
    assert not bridge.calls


def test_local_budget_survives_retries_and_does_not_claim_completion(bridge, monkeypatch):
    save_paper()
    bridge.items["PAPERAAA"] = {
        "itemType": "preprint",
        "title": "A",
        "url": "https://arxiv.org/abs/1706.03762",
        "collections": [],
    }
    monkeypatch.setattr(g, "DEFAULTS", {**g.DEFAULTS, "zotero_write_limit": 0})
    result = invoke("zotero-sync")
    assert result["to_add"] and not result["done"] and not bridge.calls


def test_web_uncertain_creation_cannot_be_retried_locally(bridge):
    save_paper()
    g.atomic_json(
        g.state_dir(g.config()) / "zotero-writes.json",
        {"days": {}, "creations": {"arxiv:1706.03762": {"status": "pending", "token": "old"}}},
    )
    assert invoke("zotero-sync")["failed"] and not bridge.calls


def test_local_backend_does_not_fall_back_when_extension_is_missing(ws, monkeypatch):
    monkeypatch.setattr(g, "zotero_api_key", lambda: "web-key")
    writer, backend, error = g.zotero_writer({**g.config(), "zotero_backend": "local"})
    assert writer is None and backend == "local" and error


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1/api/users/0",
        "http://example.com/api/users/0",
        "http://user:pass@localhost/api/users/0",
        "http://localhost/api/groups/1",
    ],
)
def test_bridge_rejects_remote_and_wrong_library_urls(tmp_path, url):
    with pytest.raises(ValueError):
        LocalWriter({"zotero_user_id": 1}, tmp_path, url)


def test_bridge_refuses_world_readable_credentials(tmp_path):
    path = tmp_path / "zotero-local.json"
    path.write_text(json.dumps({"token": "a" * 64, "user_id": 1}))
    path.chmod(0o644)
    with pytest.raises(ValueError, match="600"):
        LocalWriter({"zotero_user_id": 1}, tmp_path, "http://localhost/api/users/0")


def test_shipped_extension_regressions():
    from cairn_garden.zotero_local import BRIDGE

    result = subprocess.run(
        [
            g.node_runtime() or "node",
            str(Path(__file__).with_name("bridge_regressions.js")),
            str(BRIDGE / "bootstrap.js"),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_package_contains_matching_build(tmp_path):
    import zipfile

    path = tmp_path / "bridge.xpi"
    package(path)
    with zipfile.ZipFile(path) as z:
        assert bridge_hash() in z.read("bootstrap.js").decode()
        assert set(z.namelist()) == {"bootstrap.js", "manifest.json"}
        manifest = json.loads(z.read("manifest.json"))
        settings = manifest["applications"]["zotero"]
        assert all(settings.get(k) for k in ("id", "update_url", "strict_max_version"))
        assert settings["update_url"] == "https://kb-gardener.invalid/updates.json"


@pytest.mark.parametrize("mode", ["daily", "weekly"])
def test_scheduled_workflow_is_read_only_without_gate(setup, monkeypatch, mode):
    calls = []
    original = w.execute

    def execute(*args):
        if args[0] == "zotero-sync":
            calls.append(args)
        return original(*args)

    monkeypatch.setattr(w, "execute", execute)
    w.run(setup, mode, renderer=draft, scheduled=True, verify_html=True)
    assert calls and "--dry-run" in calls[0]
    with pytest.raises(RuntimeError):
        w.enable_scheduled_writes(setup)


@pytest.mark.parametrize("mode", ["daily", "weekly"])
def test_manual_daily_and_weekly_attempt_actual_writes(setup, monkeypatch, mode):
    calls = []
    original = w.execute

    def execute(*args):
        if args[0] == "zotero-sync":
            calls.append(args)
        return original(*args)

    monkeypatch.setattr(w, "execute", execute)
    w.run(setup, mode, renderer=draft, verify_html=True, zotero_limit=2)
    assert calls[0] == ("zotero-sync", "--limit", "2")


def test_failed_write_prevents_workflow_acknowledgement(setup, monkeypatch):
    original = w.execute

    def execute(*args):
        if args[0] == "zotero-sync":
            return {"can_write": True, "backend": "local", "failed": [{"error": "readback failed"}]}
        return original(*args)

    monkeypatch.setattr(w, "execute", execute)
    with pytest.raises(RuntimeError, match="incomplete"):
        w.run(setup, "daily", renderer=draft)
    assert "last_run_daily" not in g.load_state(setup)


@pytest.mark.parametrize(
    "doi",
    ["http://dx.doi.org/10.1234/paper", "https://doi.org/10.1234%2Fpaper", "DOI: 10.1234/PAPER"],
)
def test_legacy_doi_prefixes_reconcile_to_canonical_identity(doi):
    assert g.item_ids({"DOI": doi}) == {"doi:10.1234/paper"}
