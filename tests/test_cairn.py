import io
import json
import sys
from pathlib import Path

import pytest

from cairn import skills
from cairn.cli import connect_command, main
from cairn.html import render
from cairn.mcp import serve
from cairn.store import KB, CairnError, init, normalize_source, parse, split_minutes


@pytest.fixture
def kb(tmp_path: Path) -> KB:
    return KB(init(tmp_path / "kb"))


def test_reading_creates_paper_and_topics(kb: KB) -> None:
    result = kb.save(
        kind="paper",
        title="TIGER: Recommender Systems with Generative Retrieval",
        body="Items get **semantic IDs**; a seq2seq model generates them.",
        topics=["Generative recommendation"],
        fields={"source": "https://arxiv.org/abs/2305.05065v3", "year": 2023},
    )
    assert result["status"] == "created"
    assert result["created_topics"] == ["generative-recommendation"]
    paper = parse(Path(result["path"]))
    assert paper.path.parent.name == "papers"
    assert paper.meta["source"] == "arxiv:2305.05065"
    assert paper.meta["topics"] == ["[[generative-recommendation]]"]  # Obsidian-readable
    assert (kb.dir / "topics" / "generative-recommendation.md").exists()


def test_topic_hierarchy_and_backlinks(kb: KB) -> None:
    kb.save(kind="topic", title="Recommendation systems", body="Predict what users want.")
    kb.save(
        kind="topic",
        title="Generative recommendation",
        body="Generate item identifiers.",
        topics=["Recommendation systems"],
    )
    kb.save(
        kind="topic",
        title="Large recommendation models",
        body="Scaling laws for recommenders; compare [[generative-recommendation]].",
        topics=["recommendation-systems"],
    )
    kb.save(kind="paper", title="TIGER", body="Semantic IDs.", topics=["Generative recommendation"])

    topics = {t["slug"]: t for t in kb.list_topics()}
    root = topics["recommendation-systems"]
    assert root["broader"] == []
    assert sorted(root["narrower"]) == ["generative-recommendation", "large-recommendation-models"]
    assert topics["generative-recommendation"]["papers"] == 1

    note = kb.get("Generative recommendation")
    via = {b["slug"]: b["via"] for b in note["backlinks"]}
    assert via == {"large-recommendation-models": "body", "tiger": "topics"}
    assert note["topics"] == [
        {"slug": "recommendation-systems", "title": "Recommendation systems", "kind": "topic"}
    ]


def test_save_suggests_unlinked_related_topics(kb: KB) -> None:
    kb.save(kind="topic", title="Recommendation systems", body="Overview.")
    kb.save(kind="topic", title="Protein folding", body="Biology.")
    result = kb.save(
        kind="topic",
        title="Large recommendation models",
        body="Scaling transformer-based recommendation to billions of parameters.",
    )
    assert [s["slug"] for s in result["suggested_topics"]] == ["recommendation-systems"]
    linked = kb.save(
        kind="topic",
        title="Large recommendation models",
        body="Scaling recommendation.",
        topics=["Recommendation systems"],
        revision=result["revision"],
    )
    assert linked["suggested_topics"] == []


def test_update_requires_current_revision(kb: KB) -> None:
    first = kb.save(kind="paper", title="TIGER", body="v1", fields={"source": "10.1/X"})
    with pytest.raises(CairnError, match="get_note"):
        kb.save(kind="paper", title="TIGER", body="v2", fields={"source": "10.1/X"})

    # A hand edit in an editor changes the revision; a stale save must not clobber it.
    path = Path(first["path"])
    path.write_text(path.read_text() + "\nMy own observation.\n")
    with pytest.raises(CairnError):
        kb.save(kind="paper", title="TIGER", body="v2", revision=first["revision"])

    current = kb.get("tiger")
    assert "My own observation." in current["body"]
    second = kb.save(
        kind="paper",
        title="TIGER",
        body=current["body"] + "\nv2",
        revision=current["revision"],
        fields={"source": "https://doi.org/10.1/x"},
    )
    assert second["status"] == "updated" and second["slug"] == "tiger"
    assert "My own observation." in kb.get("tiger")["body"]
    assert parse(path).meta["created"] == parse(path).meta["updated"]


def test_rename_by_slug_keeps_identity_links_and_front_matter(kb: KB) -> None:
    first = kb.save(
        kind="note",
        title="Draft",
        body="v1",
        topics=["Recommendation systems"],
        fields={"source": "10.1/x"},
    )
    path = Path(first["path"])
    path.write_text(path.read_text().replace("kind: note", "kind: note\nmine: kept"))
    kb.save(kind="note", title="Other", body="See [[draft]].")
    current = kb.get("draft")
    renamed = kb.save(
        kind="note", title="Better name", body="v2", slug="draft", revision=current["revision"]
    )
    assert renamed["slug"] == "draft" and renamed["status"] == "updated"
    meta = parse(path).meta
    assert meta["title"] == "Better name" and meta["aliases"] == ["Draft"]
    assert meta["mine"] == "kept" and meta["topics"] == ["[[recommendation-systems]]"]
    assert kb.get("Draft")["backlinks"][0]["slug"] == "other"
    assert len(list((kb.dir / "notes").glob("*.md"))) == 2
    with pytest.raises(CairnError, match="another note"):
        kb.save(kind="note", title="Other", body="x", slug="draft", revision=renamed["revision"])
    with pytest.raises(CairnError, match="no note with slug"):
        kb.save(kind="note", title="New", body="x", slug="missing")


def test_idea_minutes_are_append_only_and_status_changes_need_reasons(kb: KB) -> None:
    kb.save(kind="paper", title="TIGER", body="Semantic IDs.", topics=["Generative recommendation"])
    first = kb.save(
        kind="idea",
        title="Semantic IDs for ads",
        body="**Question:** do semantic IDs help cold-start ads? Builds on [[tiger]].",
        topics=["Generative recommendation"],
        fields={"next_action": "Find an ads dataset"},
        minute="**User:** cold-start ads might benefit most.",
    )
    path = Path(first["path"])
    assert path.parent.name == "ideation"
    meta = parse(path).meta
    assert meta["status"] == "seed" and meta["last_discussed"] == meta["created"]

    # A later session resumes the same idea by title, echoing the body as get_note gave it.
    current = kb.get("Semantic IDs for ads")
    with pytest.raises(CairnError, match="reason"):
        kb.save(
            kind="idea",
            title="Semantic IDs for ads",
            body=current["body"],
            fields={"status": "exploring"},
            revision=current["revision"],
        )
    second = kb.save(
        kind="idea",
        title="Semantic IDs for ads",
        body=current["body"].replace("cold-start ads?", "cold-start ads? (narrowed)"),
        fields={"status": "exploring"},
        minute="**User:** worth a pilot; **Agent (suggestion):** use Criteo.",
        revision=current["revision"],
    )
    assert second["slug"] == first["slug"]
    with pytest.raises(CairnError, match="append-only"):
        kb.save(
            kind="idea",
            title="Semantic IDs for ads",
            body=kb.get(first["slug"])["body"].replace("cold-start ads might", "ads might"),
            revision=second["revision"],
        )

    # A retried entry is not added twice, and a review cannot change the status.
    current = kb.get(first["slug"])
    retry = kb.save(
        kind="idea",
        title="Semantic IDs for ads",
        body=split_minutes(current["body"])[0],  # The account alone is fine too.
        minute="**User:** worth a pilot; **Agent (suggestion):** use Criteo.",
        revision=current["revision"],
    )
    assert retry["revision"] == current["revision"]
    with pytest.raises(CairnError, match="review"):
        kb.save(
            kind="idea",
            title="Semantic IDs for ads",
            body="x",
            fields={"status": "parked"},
            minute="stale",
            review=True,
            revision=retry["revision"],
        )
    kb.save(
        kind="idea",
        title="Semantic IDs for ads",
        body="Narrowed question.",
        minute="**Source:** [[tiger]] reports gains on sparse items.",
        review=True,
        revision=retry["revision"],
    )

    idea = parse(path)
    account, minutes = split_minutes(idea.body)
    assert account == "Narrowed question."
    assert minutes.count("worth a pilot") == 1 and "Status: seed → exploring." in minutes
    assert minutes.index("cold-start ads might") < minutes.index("(review)")
    assert idea.meta["status"] == "exploring"
    assert idea.meta["next_action"] == "Find an ads dataset"
    assert idea.meta["last_review"] == idea.meta["last_discussed"]
    assert kb.get("tiger")["backlinks"] == [
        {"slug": first["slug"], "title": "Semantic IDs for ads", "kind": "idea", "via": "body"}
    ]
    [hit] = kb.search("", kind="idea", status="exploring")
    assert hit["next_action"] == "Find an ads dataset" and hit["status"] == "exploring"
    assert kb.search("", status="parked") == []
    [topic] = kb.list_topics()
    assert (topic["papers"], topic["ideas"]) == (1, 1)
    with pytest.raises(CairnError, match="only for ideas"):
        kb.save(kind="note", title="N", body="x", minute="y")


def test_knowledge_base_without_ideation_folder_still_works(kb: KB) -> None:
    (kb.dir / "ideation").rmdir()  # As made by an earlier version of `cairn init`.
    kb.save(kind="paper", title="TIGER", body="Semantic IDs.", topics=["Recsys"])
    assert [t["slug"] for t in kb.list_topics()] == ["recsys"]
    assert kb.search("", kind="idea") == []
    result = kb.save(kind="idea", title="Idea", body="Try it.", topics=["Recsys"])
    assert Path(result["path"]).parent == kb.dir / "ideation"


def test_same_paper_by_doi_reuses_note_and_different_paper_gets_new_slug(kb: KB) -> None:
    a = kb.save(kind="paper", title="Attention", body="x", fields={"source": "doi:10.1/A"})
    b = kb.save(kind="paper", title="Attention", body="y", fields={"source": "10.2/b"})
    assert (a["slug"], b["slug"]) == ("attention", "attention-2")
    with pytest.raises(CairnError, match="already exists"):
        kb.save(
            kind="paper", title="Renamed", body="z", fields={"source": "https://doi.org/10.1/a"}
        )


def test_kind_conflict_and_unresolved_links(kb: KB) -> None:
    kb.save(kind="topic", title="Transformers", body="Attention.")
    with pytest.raises(CairnError, match="topic named"):
        kb.save(kind="note", title="Transformers", body="dup")
    result = kb.save(kind="note", title="Ideas", body="See [[transformers]] and [[nowhere]].")
    assert result["unresolved_links"] == ["nowhere"]


def test_titles_cannot_escape_the_collection(kb: KB) -> None:
    result = kb.save(kind="note", title="../../etc/passwd", body="x")
    assert Path(result["path"]).parent == kb.dir / "notes"
    assert result["slug"] == "etc-passwd"


def test_collections_are_separate(tmp_path: Path) -> None:
    root = init(tmp_path / "kb")
    KB(root, "finance").save(kind="note", title="Budget", body="Rent and savings.")
    research = KB(root)
    assert research.search("savings") == []
    with pytest.raises(CairnError):
        research.get("budget")
    with pytest.raises(CairnError):
        KB(root, "secrets")
    with pytest.raises(CairnError, match="cairn init"):
        KB(tmp_path / "missing")


def test_search_ranks_titles_and_supports_unicode(kb: KB) -> None:
    kb.save(kind="topic", title="Recommendation systems", body="Overview.")
    kb.save(kind="note", title="Misc", body="recommendation appears once")
    kb.save(kind="note", title="推荐系统笔记", body="生成式推荐")
    assert [h["slug"] for h in kb.search("recommendation")] == ["recommendation-systems", "misc"]
    assert kb.search("生成式")[0]["title"] == "推荐系统笔记"


def test_html_links_notes_and_escapes_raw_html(kb: KB) -> None:
    kb.save(kind="topic", title="Recommendation systems", body="Overview.")
    kb.save(
        kind="paper",
        title="TIGER",
        body="Builds on [[recommendation-systems|recsys]]. <script>alert(1)</script>\n\n"
        "| a |\n|---|\n| 1 |",
        topics=["Recommendation systems"],
    )
    out = render(kb)
    page = (out / "tiger.html").read_text()
    assert '<a href="recommendation-systems.html">recsys</a>' in page
    assert "<script>" not in page and "&lt;script&gt;" in page
    assert "<table>" in page
    topic = (out / "recommendation-systems.html").read_text()
    assert "In this topic" in topic and "tiger.html" in topic
    assert "tiger.html" in (out / "index.html").read_text()


def rpc(kb: KB, *messages: dict) -> list[dict]:
    stdin = io.StringIO("".join(json.dumps(m) + "\n" for m in messages) + "not json\n")
    stdout = io.StringIO()
    serve(kb, stdin, stdout)
    return [json.loads(line) for line in stdout.getvalue().splitlines()]


def test_mcp_protocol_round_trip(kb: KB) -> None:
    save = {
        "name": "save_reading",
        "arguments": {
            "title": "TIGER",
            "body": "Semantic IDs.",
            "topics": ["Generative recommendation"],
            "source": "arXiv:2305.05065",
        },
    }
    replies = rpc(
        kb,
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "x"}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": save},
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": save},
        {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "list_topics"}},
        {"jsonrpc": "2.0", "id": 6, "method": "nope"},
    )
    assert [r["id"] for r in replies] == [1, 2, 3, 4, 5, 6, None]
    assert "save_reading" in replies[0]["result"]["instructions"]
    names = [t["name"] for t in replies[1]["result"]["tools"]]
    assert names == ["search", "get_note", "list_topics", "save_reading", "save_idea", "save_note"]
    saved = json.loads(replies[2]["result"]["content"][0]["text"])
    assert saved["slug"] == "tiger" and not replies[2]["result"]["isError"]
    assert replies[3]["result"]["isError"]  # Same paper again without a revision.
    topics = json.loads(replies[4]["result"]["content"][0]["text"])
    assert topics[0]["slug"] == "generative-recommendation" and topics[0]["empty"]
    assert replies[5]["error"]["code"] == -32601
    assert replies[6]["error"]["code"] == -32700


def test_mcp_saves_resumes_and_renames_an_idea(kb: KB) -> None:
    def call(id: int, name: str, **arguments: object) -> dict:
        return {
            "jsonrpc": "2.0",
            "id": id,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }

    idea = {"title": "Semantic IDs for ads", "body": "Do they help?", "minute": "**User:** maybe."}
    replies = rpc(
        kb, call(1, "save_idea", **idea, next_action="Find data"), call(2, "save_idea", **idea)
    )
    saved = json.loads(replies[0]["result"]["content"][0]["text"])
    assert saved["kind"] == "idea" and not replies[0]["result"]["isError"]
    assert replies[1]["result"]["isError"]  # Resuming needs the current revision.

    current = kb.get(saved["slug"])
    replies = rpc(
        kb,
        call(
            1,
            "save_idea",
            title="Semantic IDs for cold-start ads",
            body=current["body"],
            slug=saved["slug"],
            revision=current["revision"],
            status="exploring",
            minute="**User:** narrow to cold start; worth exploring.",
        ),
        call(2, "search", query="", kind="idea", status="exploring"),
    )
    [hit] = json.loads(replies[1]["result"]["content"][0]["text"])
    assert hit["slug"] == saved["slug"] and hit["title"] == "Semantic IDs for cold-start ads"
    assert hit["next_action"] == "Find data"


def test_mcp_reports_bad_arguments_and_tolerates_broken_notes(kb: KB) -> None:
    (kb.dir / "notes" / "broken.md").write_text("---\n: [unclosed\n---\nbody text\n")
    replies = rpc(
        kb,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "save_note", "arguments": {"title": "x"}},
        },
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "search", "arguments": {"query": "body"}},
        },
    )
    assert replies[0]["result"]["isError"]
    assert "kind is required" in replies[0]["result"]["content"][0]["text"]
    hits = json.loads(replies[1]["result"]["content"][0]["text"])
    assert [h["slug"] for h in hits] == ["broken"]


def test_cli_and_connect_commands(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = tmp_path / "kb"
    assert main(["init", str(root)]) == 0
    assert main(["topics", "-w", str(root)]) == 0
    assert main(["search", "--kind", "idea", "--status", "seed", "-w", str(root)]) == 0
    assert main(["connect", "claude", "-w", str(root), "--dry-run"]) == 0
    assert main(["show", "nothing", "-w", str(root)]) == 1
    assert connect_command("claude", root, "research", False) == [
        "claude",
        "mcp",
        "add",
        "--scope",
        "user",
        "cairn",
        "--",
        sys.executable,
        "-m",
        "cairn",
        "mcp",
        "--workspace",
        str(root),
        "--collection",
        "research",
    ]
    assert connect_command("codex", root, "finance", True) == [
        "codex",
        "mcp",
        "remove",
        "cairn-finance",
    ]


def fake_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    for name in ("FINCH", "QUILL", "ASTER"):
        monkeypatch.delenv(f"{name}_HOME", raising=False)
    return home


def test_skills_install_runs_each_installer_at_its_pin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    home = fake_home(tmp_path, monkeypatch)
    assert main(["skills", "install", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert f"/finch/{skills.PINS['finch']}/install.sh | FINCH_REF={skills.PINS['finch']}" in out
    assert "bash -s -- install --no-auto-update" in out and "cairn-garden skill" in out
    assert not (home / ".local").exists() and not (home / ".claude/skills").exists()

    clone = home / ".local/share/finch"
    clone.mkdir(parents=True)
    (clone / "install.sh").write_text('echo "$FINCH_REF $*" > "$HOME/ran"\n')
    assert main(["skills", "install", "finch"]) == 0
    assert (home / "ran").read_text() == f"{skills.PINS['finch']} install --no-auto-update\n"
    assert main(["skills", "remove", "finch"]) == 0
    assert (home / "ran").read_text() == " uninstall\n"
    assert main(["skills", "remove", "quill"]) == 0  # not installed: nothing to run
    assert main(["skills", "install", "zotero"]) == 1


def test_skills_status_and_pin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    home = fake_home(tmp_path, monkeypatch)
    pinned = skills.PINS["aster"].removeprefix("v")
    skill = home / ".local/share/aster/skills/aster"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(f'---\nmetadata:\n  version: "{pinned}"\n---\n')
    (home / ".claude/skills").mkdir()
    (home / ".claude/skills/aster").symlink_to(skill)
    (home / ".claude/skills/kb-gardener").symlink_to(tmp_path / "gone")
    rows = {row["skill"]: row for row in skills.status()}
    assert rows["aster"]["installed"] == pinned and rows["aster"]["ok"]
    assert rows["finch"]["installed"] is None and not rows["finch"]["ok"]
    gardener = rows["kb-gardener"]
    assert not gardener["ok"] and list(gardener["links"].values())[0].startswith("broken")

    assert main(["skills", "pin", "aster"]) == 0
    assert capsys.readouterr().out == skills.PINS["aster"] + "\n"
    assert main(["skills", "pin", "kb-gardener"]) == 1


def test_normalize_source() -> None:
    assert normalize_source("https://doi.org/10.1145/ABC") == "doi:10.1145/abc"
    assert normalize_source("10.1145/abc") == "doi:10.1145/abc"
    assert normalize_source("https://arxiv.org/pdf/2305.05065v2") == "arxiv:2305.05065"
    assert normalize_source("https://example.com/p") == "https://example.com/p"


def test_knowledge_base_cannot_live_inside_a_repository(tmp_path: Path) -> None:
    (tmp_path / "code" / ".git").mkdir(parents=True)
    with pytest.raises(CairnError, match="git repository"):
        init(tmp_path / "code" / "notes")
    (tmp_path / "code" / "kb").mkdir()
    (tmp_path / "code" / "kb" / ".cairn").touch()
    with pytest.raises(CairnError, match="git repository"):
        KB(tmp_path / "code" / "kb")
    private = init(tmp_path / "private")
    (private / ".git").mkdir()  # A knowledge base may be its own private repository.
    assert KB(private).list_topics() == []
