"""The Zotero Web API backend: reads, writes with read-back, throttling and lost outcomes."""

import io
import json
import urllib.error
import urllib.parse
from datetime import timedelta

import pytest
from cairn_garden import workflow as w
from test_regressions import g, invoke, save_paper

PAPER = "arxiv:1706.03762"
LOAD = g.ZoteroIndex.__dict__["load"]  # setup turns Zotero reads off; scheduled writes need them
METADATA = {
    "itemType": "preprint",
    "title": "Original paper",
    "url": "https://arxiv.org/abs/1706.03762",
    "archiveID": "arXiv:1706.03762",
}


class Response(io.BytesIO):
    def __init__(self, value, headers=None):
        super().__init__(json.dumps(value).encode() if value is not None else b"")
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeZotero:
    """Just enough of api.zotero.org for one user library."""

    def __init__(self, user=1, write=True):
        self.user, self.write = user, write
        self.collections = [{"key": "TOPIC001", "data": {"name": "Transformers"}}]
        self.items = {}
        self.calls = []
        self.tokens = set()
        self.throttle = 0
        self.lose_post_response = False

    def error(self, url, code, headers=None):
        return urllib.error.HTTPError(url, code, "error", headers or {}, None)

    def __call__(self, request, timeout=None):
        url = urllib.parse.urlsplit(request.full_url)
        path, query = url.path, dict(urllib.parse.parse_qsl(url.query))
        method = request.get_method()
        self.calls.append((method, path))
        assert request.headers.get("Zotero-api-key") == "secret"
        if self.throttle:
            self.throttle -= 1
            raise self.error(request.full_url, 429, {"Retry-After": "2"})
        if path == "/keys/current":
            return Response({"userID": self.user, "access": {"user": {"write": self.write}}})
        base = f"/users/{self.user}/"
        assert path.startswith(base)
        route = path[len(base) :]
        if route == "collections":
            return Response(self.collections[int(query.get("start", 0)) :][:100])
        if route == "items/top":
            items = sorted(self.items.values(), key=lambda i: i["key"])
            start = int(query.get("start", 0))
            return Response(items[start : start + int(query.get("limit", 100))])
        if route == "items" and method == "POST":
            token = request.headers.get("Zotero-write-token")
            if token in self.tokens:
                raise self.error(request.full_url, 412)
            self.tokens.add(token)
            data = json.loads(request.data)[0]
            key = f"ITEM{len(self.items):04d}"
            data = {**data, "key": key, "dateAdded": "2026-10-14T12:00:00Z"}
            self.items[key] = {"key": key, "version": 1, "data": data}
            if self.lose_post_response:
                self.lose_post_response = False
                raise TimeoutError("response lost after the server stored the item")
            return Response({"successful": {"0": {"key": key}}, "failed": {}})
        key = route.split("/")[1]
        if route.endswith("/children"):
            return Response([])
        item = self.items[key]
        if method == "PATCH":
            if int(request.headers["If-unmodified-since-version"]) != item["version"]:
                raise self.error(request.full_url, 412)
            item["data"].update(json.loads(request.data))
            item["version"] += 1
            return Response(None)
        return Response(item)

    def posts(self):
        return sum(method == "POST" for method, _ in self.calls)


@pytest.fixture
def web(ws, monkeypatch):
    fake = FakeZotero()
    monkeypatch.setattr(g.urllib.request, "urlopen", fake)
    monkeypatch.setattr(g, "zotero_api_key", lambda: "secret")
    monkeypatch.setattr(g, "pause", lambda seconds: fake.calls.append(("PAUSE", seconds)))
    monkeypatch.setattr(g, "remote_metadata", lambda ident: dict(METADATA))
    monkeypatch.setattr(g, "DEFAULTS", {**g.DEFAULTS, "zotero_backend": "web", "zotero_user_id": 1})
    save_paper()
    return fake


def test_web_only_sync_creates_with_read_back_and_no_local_zotero(web):
    result = invoke("zotero-sync")
    assert result["zotero_available"] and result["backend"] == "web" and not result["failed"]
    [created] = result["done"]
    assert created["status"] == "created" and created["verified"]
    assert created["collections"] == ["TOPIC001"]
    assert result["bridge"] == {"library": "users/1", "key_user_id": 1, "write": True}
    again = invoke("zotero-sync")
    assert again["done"] == [] and not again["to_create"] and web.posts() == 1


def test_unverifiable_metadata_is_skipped_without_failing_the_sync(web, monkeypatch):
    # A DataCite DOI or a metadata outage: never created, reported, other writes continue.
    save_paper(source="doi:10.5281/zenodo.1", title="Dataset release")
    monkeypatch.setattr(g, "remote_metadata", lambda i: dict(METADATA) if i == PAPER else None)
    result = invoke("zotero-sync")
    assert not result["failed"] and result["unverified"] == ["doi:10.5281/zenodo.1"]
    assert [x["status"] for x in result["done"]] == ["created"] and web.posts() == 1


def test_web_reads_serve_discovery_and_link_repair(web):
    invoke("zotero-sync")
    g.configure_zotero(g.config())
    recent = g.zotero_recent("2000-01-01")
    assert recent["available"] and recent["candidates"][0]["title"] == "Original paper"
    assert g.ZoteroIndex.load().find([PAPER]) == "ITEM0000"
    assert not any(path.startswith("/api") for _, path in web.calls if isinstance(path, str))


def test_membership_is_added_without_dropping_others(web):
    web.items["OLD00001"] = {
        "key": "OLD00001",
        "version": 4,
        "data": {**METADATA, "key": "OLD00001", "collections": ["OTHER001"], "extra": "mine"},
    }
    [added] = invoke("zotero-sync")["done"]
    assert added["status"] == "added" and added["before_collections"] == ["OTHER001"]
    assert web.items["OLD00001"]["data"]["collections"] == ["OTHER001", "TOPIC001"]
    assert web.items["OLD00001"]["data"]["extra"] == "mine" and web.posts() == 0


def test_throttling_is_waited_out(web):
    web.throttle = 2
    result = invoke("zotero-sync")
    assert result["done"] and ("PAUSE", 2.0) in web.calls
    assert sum(call == ("PAUSE", 2.0) for call in web.calls) == 2


def test_lost_post_response_is_reconciled_without_a_second_item(web):
    web.lose_post_response = True
    first = invoke("zotero-sync")
    assert first["failed"] and len(web.items) == 1
    ledger = g.read_json(g.state_dir(g.config()) / "zotero-writes.json", {})
    assert ledger["creations"][PAPER]["status"] == "pending"
    second = invoke("zotero-sync")
    assert not second["failed"] and web.posts() == 1 and len(web.items) == 1
    assert (
        g.read_json(g.state_dir(g.config()) / "zotero-writes.json", {})["creations"][PAPER][
            "status"
        ]
        == "confirmed"
    )


def test_lost_state_does_not_duplicate_an_item(web):
    invoke("zotero-sync")
    (g.state_dir(g.config()) / "zotero-writes.json").unlink()  # a runner lost its state
    invoke("zotero-sync")
    assert web.posts() == 1 and len(web.items) == 1


def test_unknown_outcome_waits_before_a_new_attempt(web):
    path = g.state_dir(g.config()) / "zotero-writes.json"
    recent = g.now(g.config()).isoformat()
    g.atomic_json(
        path, {"days": {}, "creations": {PAPER: {"status": "pending", "token": "t", "at": recent}}}
    )
    assert invoke("zotero-sync")["failed"] and web.posts() == 0
    old = (g.now(g.config()) - timedelta(hours=13)).isoformat()
    g.atomic_json(
        path, {"days": {}, "creations": {PAPER: {"status": "pending", "token": "t", "at": old}}}
    )
    assert invoke("zotero-sync")["done"][0]["status"] == "created" and web.posts() == 1


@pytest.mark.parametrize("fake", [FakeZotero(user=2), FakeZotero(write=False)])
def test_key_for_another_library_or_read_only_cannot_write(web, monkeypatch, fake):
    monkeypatch.setattr(g.urllib.request, "urlopen", fake)
    writer, backend, error = g.zotero_writer(g.config())
    assert writer is None and backend == "web" and error


def test_write_gate_accepts_only_matching_web_evidence(web):
    cfg = g.config()
    evidence = {"backend": "web", "bridge": {"library": "users/1", "key_user_id": 1, "write": True}}
    assert w.identity_verified(cfg, evidence, lambda: "")
    assert not w.identity_verified({**cfg, "zotero_user_id": 2}, evidence, lambda: "")
    assert not w.identity_verified({**cfg, "zotero_backend": "auto"}, evidence, lambda: "")
    read_only = {**evidence, "bridge": {**evidence["bridge"], "write": False}}
    assert not w.identity_verified(cfg, read_only, lambda: "")
    assert w.write_verification(cfg) == {"daily": False, "weekly": False}
    with pytest.raises(RuntimeError, match="Scheduled writes remain disabled"):
        w.enable_scheduled_writes(cfg)


def test_scheduled_web_run_stays_read_only_until_enabled(web, setup):
    result = w.run(
        g.config(),
        "daily",
        renderer=lambda *a, **k: (
            {
                "body": "No recommendations today; nothing new was found in the sources.",
                "selected": [],
            },
            {"agent": "claude"},
        ),
        scheduled=True,
    )
    assert "Scheduled Zotero writes are gated; sync is read-only" in result["warnings"]
    assert web.posts() == 0


def enable(cfg, monkeypatch):
    verified = {"daily": True, "weekly": True}
    monkeypatch.setattr(w, "write_verification", lambda cfg: verified)
    monkeypatch.setattr(
        w, "readiness", lambda cfg: {"ready": True, "zotero_write_verification": verified}
    )
    state = g.load_state(cfg)
    state.update(zotero_verified_daily="daily-run", zotero_verified_weekly="weekly-run")
    g.save_state(cfg, state)
    w.enable_scheduled_writes(cfg)


def test_write_gate_stays_open_across_upgrades_unless_strict(web, monkeypatch):
    cfg = g.config()
    enable(cfg, monkeypatch)
    assert w.scheduled_writes_enabled(cfg)
    monkeypatch.setattr(w, "release_hash", lambda: "another release")
    monkeypatch.setattr(w, "writer_hash", lambda: "changed write path")
    assert w.scheduled_writes_enabled(cfg)
    assert not w.scheduled_writes_enabled({**cfg, "zotero_strict_write_gate": True})
    assert "write code changed" in w.write_gate_closed(cfg)
    assert not w.scheduled_writes_enabled({**cfg, "zotero_user_id": 2})
    assert "library changed" in w.write_gate_closed({**cfg, "zotero_user_id": 2})


def test_gate_without_writer_is_migrated(web):
    cfg = g.config()
    bridge = {"library": "users/1", "key_user_id": 1, "write": True}
    g.atomic_json(g.state_dir(cfg) / w.GATE, {"config": "old", "bridge": bridge})
    assert w.scheduled_writes_enabled(cfg)
    g.atomic_json(g.state_dir(cfg) / w.GATE, {"config": "old", "bridge": {"user_id": 1}})
    assert w.scheduled_writes_enabled(cfg)


def scheduled_daily(monkeypatch):
    monkeypatch.setattr(g.ZoteroIndex, "load", LOAD)
    return w.run(
        g.config(),
        "daily",
        renderer=lambda *a, **k: (
            {"body": "No recommendations today; nothing new was found.", "selected": []},
            {"agent": "claude"},
        ),
        scheduled=True,
    )


def test_changed_writer_is_reverified_by_the_next_scheduled_write(web, setup, monkeypatch):
    g.atomic_json(g.state_dir(g.config()) / w.GATE, {"writer": "old", "bridge": {"user_id": 1}})
    result = scheduled_daily(monkeypatch)
    assert any(x.startswith(w.WRITES_UNVERIFIED) for x in result["warnings"])
    assert web.posts() == 1
    gate = g.read_json(g.state_dir(g.config()) / w.GATE, {})
    assert gate["writer"] == w.writer_hash() and gate["reverified"]["run"] == result["id"]
    assert w.gate_current(g.config(), gate) and not gate.get("paused")


def test_failed_reverification_pauses_writes(web, setup, monkeypatch):
    g.atomic_json(g.state_dir(g.config()) / w.GATE, {"writer": "old", "bridge": {"user_id": 1}})

    def broken(*args):
        raise RuntimeError("read-back does not show the created item's identifier")

    monkeypatch.setattr(g.WebWriter, "readback", broken)
    with pytest.raises(RuntimeError, match="read-back failures"):
        scheduled_daily(monkeypatch)
    assert not w.scheduled_writes_enabled(g.config())
    assert "could not verify" in w.write_gate_closed(g.config())


def test_paused_writes_are_reported_distinctly(web, monkeypatch):
    g.atomic_json(g.state_dir(g.config()) / w.GATE, {"writer": "old", "paused": "a test"})
    result = w.run(
        g.config(),
        "daily",
        renderer=lambda *a, **k: (
            {"body": "No recommendations today; nothing new was found.", "selected": []},
            {"agent": "claude"},
        ),
        scheduled=True,
    )
    assert any(x.startswith(w.WRITES_PAUSED) for x in result["warnings"])
    assert web.posts() == 0


def test_run_page_flags_writes_paused_now_not_in_an_old_run(web, capsys):
    from cairn_garden import ci

    cfg = g.config()
    old = g.state_dir(cfg) / "runs" / "20261019T140007-weekly-old" / "manifest.json"
    old.parent.mkdir(parents=True)
    warning = f"{w.WRITES_PAUSED}: the Zotero write code changed since they were enabled"
    g.atomic_json(old, {"id": old.parent.name, "mode": "weekly", "warnings": [warning]})
    # A later run re-verified writes: the old weekly's warning is history, not news.
    g.atomic_json(g.state_dir(cfg) / w.GATE, {"bridge": {"user_id": 1}})
    ci.main(["summary", "--mode", "daily"])
    assert "::warning" not in capsys.readouterr().out
    g.atomic_json(g.state_dir(cfg) / w.GATE, {"bridge": {"user_id": 1}, "paused": "a test"})
    ci.main(["summary", "--mode", "daily"])
    assert (
        f"::warning title=Zotero writes paused::{w.WRITES_PAUSED}: a test"
        in capsys.readouterr().out
    )
