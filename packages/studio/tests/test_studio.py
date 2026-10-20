import json
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

import pytest
from cairn_studio import cli, server, views
from sample import build

from cairn.store import KB

IDEA = "semantic-ids-for-cold-start-ads"
ASSETS = Path(server.__file__).with_name("assets")


@pytest.fixture
def kb(tmp_path: Path) -> KB:
    return build(tmp_path / "kb")


def test_graph_links_existing_notes_only(kb: KB) -> None:
    kb.save(kind="note", title="Dangling", body="See [[nowhere]] and [[uplift-modeling]].")
    graph = views.graph(kb)
    edges = {(e["source"], e["target"], e["kind"]) for e in graph["edges"]}
    assert ("generative-recommendation", "recommendation-systems", "topic") in edges
    assert ("dangling", "uplift-modeling", "link") in edges
    assert not any(e[1] == "nowhere" for e in edges)
    nodes = {n["slug"]: n for n in graph["nodes"]}
    assert nodes[IDEA]["status"] == "exploring"
    assert nodes["recommendation-systems"]["degree"] >= 3


def test_render_links_inside_the_app_and_escapes_html(kb: KB) -> None:
    notes = kb.notes()
    html = views.render("[[uplift-modeling|uplift]] [[missing note]] <script>x</script>", notes)
    assert '<a href="#/note/uplift-modeling">uplift</a>' in html
    assert "<em>missing note</em>" in html
    assert "<script>" not in html and "&lt;script&gt;" in html


def test_minutes_are_split_into_attributed_items(kb: KB) -> None:
    text = (
        "### 2026-10-01\n\n**User:** first line\ncontinues here.\n"
        "**Agent (suggestion):** try X.\n\n"
        "### 2026-10-03 (review)\n\nStatus: seed → exploring.\n\n"
        "**Source:** [[uplift-modeling]] says so.\n\nAn unattributed remark."
    )
    days = views.minutes(text, kb.notes())
    assert [d["date"] for d in days] == ["2026-10-01", "2026-10-03"]
    assert days[1]["label"] == "review"
    first = days[0]["items"]
    assert [i["who"] for i in first] == ["user", "agent"]
    assert "continues here" in first[0]["html"]
    assert first[1]["label"] == "Agent (suggestion)"
    second = days[1]["items"]
    assert second[0] == {"who": "status", "from": "seed", "to": "exploring"}
    assert second[1]["who"] == "source" and "#/note/uplift-modeling" in second[1]["html"]
    assert second[2]["who"] == "note"


def test_idea_note_has_account_minutes_and_trails(kb: KB) -> None:
    note = views.note(kb, IDEA)
    assert note["fields"]["status"] == "exploring"
    assert "## Minutes" not in note["html"] and "Minutes" not in note["html"]
    whos = [i["who"] for day in note["minutes"] for i in day["items"]]
    assert whos == ["user", "agent", "status", "user", "source"]
    assert note["trails"] == [
        [
            {"slug": "recommendation-systems", "title": "Recommendation systems"},
            {"slug": "generative-recommendation", "title": "Generative recommendation"},
        ]
    ]
    assert note["related"][0]["kind"] in ("paper", "idea")


def test_topic_note_lists_narrower_topics_and_members(kb: KB) -> None:
    note = views.note(kb, "Recommendation systems")  # titles resolve like get_note
    narrower = {t["slug"] for t in note["narrower"]}
    assert {"generative-recommendation", "uplift-modeling"} <= narrower
    assert note["members"] == []
    assert "related" not in note
    topic = views.note(kb, "generative-recommendation")
    assert {m["kind"] for m in topic["members"]} == {"paper", "idea"}


def test_idea_board_flags_quiet_ideas(kb: KB) -> None:
    later = date.today().replace(year=date.today().year + 1)
    board = views.ideas(kb, today=later)
    columns = {c["status"]: c["ideas"] for c in board["columns"]}
    assert list(columns) == ["seed", "exploring", "testing", "parked", "developed"]
    assert [i["slug"] for i in columns["exploring"]] == [IDEA]
    assert columns["exploring"][0]["stale"] is True
    assert views.ideas(kb)["columns"][1]["ideas"][0]["stale"] is False


def test_recent_puts_the_latest_save_first(kb: KB) -> None:
    kb.save(kind="paper", title="Saved just now", body="New.", topics=["Causal inference"])
    recent = views.recent(kb)
    assert recent["notes"][0]["title"] == "Saved just now"
    assert recent["notes"][0]["topics"] == [
        {"slug": "causal-inference", "title": "Causal inference"}
    ]
    assert all(n["kind"] != "topic" for n in recent["notes"])
    assert recent["counts"]["paper"] == 4


def test_search_returns_topic_titles(kb: KB) -> None:
    results = views.search(kb, "semantic")["results"]
    assert results[0]["slug"] in (IDEA, "tiger-recommender-systems-with-generative-retrieval")
    assert all(isinstance(t, dict) for r in results for t in r["topics"])
    assert all("**" not in r["snippet"] and "##" not in r["snippet"] for r in results)


def test_signature_changes_when_a_note_changes(kb: KB) -> None:
    before = views.signature(kb)
    assert views.signature(kb) == before
    kb.save(kind="note", title="Another", body="Text.")
    assert views.signature(kb) != before


@pytest.fixture
def studio(kb: KB, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(server, "POLL_SECONDS", 0.05)
    app = server.StudioServer(kb.root, "research")
    thread = threading.Thread(target=app.serve_forever, daemon=True)
    thread.start()
    yield app
    app.shutdown()
    app.server_close()


def fetch(app: server.StudioServer, path: str, host: str | None = None):
    request = urllib.request.Request(app.url.rstrip("/") + path)
    if host:
        request.add_header("Host", host)
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, dict(response.headers), response.read()
    except urllib.error.HTTPError as error:
        return error.code, dict(error.headers), error.read()


def test_server_answers_the_api_and_serves_the_app(studio: server.StudioServer) -> None:
    status, headers, body = fetch(studio, f"/api/note?slug={IDEA}")
    assert status == 200 and json.loads(body)["kind"] == "idea"
    assert "default-src 'self'" in headers["Content-Security-Policy"]
    status, _, body = fetch(studio, "/api/collections")
    assert json.loads(body) == {
        "collections": ["research"],
        "default": "research",
        "catalog": False,
    }
    status, headers, body = fetch(studio, "/")
    assert status == 200 and b"app.js" in body and headers["Content-Type"].startswith("text/html")
    assert fetch(studio, "/assets/app.js")[0] == 200


def test_server_refuses_other_hosts_unknown_notes_and_stray_paths(
    studio: server.StudioServer,
) -> None:
    assert fetch(studio, "/api/recent", host="attacker.example")[0] == 421
    status, _, body = fetch(studio, "/api/note?slug=nope")
    assert status == 404 and "no note" in json.loads(body)["error"]
    assert fetch(studio, "/api/note?slug=x&c=elsewhere")[0] == 404
    assert fetch(studio, "/assets/../server.py")[0] == 404
    assert fetch(studio, "/assets/%2e%2e/server.py")[0] == 404
    assert fetch(studio, "/api/unknown")[0] == 404


def test_events_report_a_save(studio: server.StudioServer, kb: KB) -> None:
    lines: list[str] = []

    def listen() -> None:
        with urllib.request.urlopen(studio.url + "api/events", timeout=5) as response:
            for raw in response:
                lines.append(raw.decode().strip())
                if lines[-1] == "event: change":
                    return

    reader = threading.Thread(target=listen, daemon=True)
    reader.start()
    deadline = time.time() + 5
    while "event: ready" not in lines and time.time() < deadline:
        time.sleep(0.02)
    kb.save(kind="note", title="Fresh", body="Saved while watching.")
    reader.join(timeout=5)
    assert "event: change" in lines


def test_serve_needs_a_workspace(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["serve"]) == 2
    assert "CAIRN_WORKSPACE" in capsys.readouterr().err


def test_serve_rejects_a_folder_that_is_not_a_knowledge_base(tmp_path: Path) -> None:
    assert cli.main(["serve", "-w", str(tmp_path)]) == 1


@pytest.mark.skipif(not shutil.which("node"), reason="Node.js is not installed")
@pytest.mark.parametrize("script", ["app.js", "map.js"])
def test_scripts_parse(script: str) -> None:
    source = (ASSETS / script).read_bytes()  # on stdin, so any Node treats it as a module
    node = [shutil.which("node"), "--input-type=module", "--check"]
    subprocess.run(node, input=source, check=True)


def test_collections_with_notes_are_offered(kb: KB) -> None:
    assert server.collections(kb.root, "research") == ["research"]
    KB(kb.root, "life").save(kind="note", title="Groceries", body="Milk.")
    assert server.collections(kb.root, "research") == ["research", "life"]
