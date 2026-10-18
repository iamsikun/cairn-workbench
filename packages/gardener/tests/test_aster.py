"""Aster as a discovery, verification and import source, through a fake `aster` command."""

import json
import sys

import pytest
from test_regressions import g, invoke, kb

FAKE = f"""#!{sys.executable}
import json, os, sys
folder = os.environ["FAKE_ASTER"]
stdin = "" if sys.stdin.isatty() else sys.stdin.read()
with open(os.path.join(folder, "calls.jsonl"), "a") as f:
    f.write(json.dumps({{"argv": sys.argv[1:], "stdin": stdin}}) + "\\n")
reply = json.load(open(os.path.join(folder, "replies.json"))).get(sys.argv[1], {{}})
if reply.get("stdout") is not None:
    print(json.dumps(reply["stdout"]))
sys.exit(reply.get("code", 0))
"""

ITEMS = [
    {
        "work_id": "w_journal",
        "title": "Heterogeneous treatment effects in markets",
        "authors": ["A. Author", "B. Author"],
        "abstract": "We study treatment effects.",
        "kind": "paper",
        "venue": "Marketing Science",
        "date": "2026-10-15",
        "first_seen": "2026-10-16T12:00:00+00:00",
        "ids": {"doi": "10.1287/mksc.2026.0001"},
        "urls": {"landing": "https://pubsonline.informs.org/doi/10.1287/mksc.2026.0001"},
        "fields": ["marketing"],
        "reasons": ["fields:marketing", "match:treatment effects"],
    },
    {
        "work_id": "w_preprint",
        "title": "Treatment effects with language models",
        "authors": ["C. Author"],
        "abstract": None,
        "kind": "paper",
        "date": "2026-10-16",
        "first_seen": "2026-10-16T13:00:00+00:00",
        "ids": {"arxiv": "2610.01234"},
        "urls": {"landing": "https://arxiv.org/abs/2610.01234v1"},
        "fields": ["machine-learning"],
    },
    {
        "work_id": "w_release",
        "title": "A model card about treatment effects",
        "kind": "release",
        "ids": {"hf": "org/model"},
        "urls": {"landing": "https://huggingface.co/org/model"},
    },
]

WORK = {
    "work_id": "w_journal",
    "title": "Heterogeneous Treatment Effects in Markets",
    "authors": ["A. Author", "B. Author"],
    "abstract": "We study treatment effects in two-sided markets.",
    "venue": "Marketing Science",
    "published_date": "2026-10-15",
    "ids": {"doi": "10.1287/mksc.2026.0001"},
}


@pytest.fixture
def fake_aster(ws, tmp_path, monkeypatch):
    folder = tmp_path / "fake-aster"
    folder.mkdir()
    script = folder / "aster"
    script.write_text(FAKE)
    script.chmod(0o755)
    monkeypatch.setenv("CAIRN_ASTER", str(script))
    monkeypatch.setenv("FAKE_ASTER", str(folder))

    def reply(**replies):
        (folder / "replies.json").write_text(json.dumps(replies))

    def calls():
        lines = (folder / "calls.jsonl").read_text().splitlines()
        return [json.loads(line) for line in lines]

    kb().save(kind="topic", title="Treatment effects", body="Causal effects that vary.")
    return reply, calls


def test_new_papers_from_aster_match_topics_since_the_window(fake_aster, monkeypatch):
    reply, calls = fake_aster
    reply(candidates={"stdout": {"schema": "aster.candidates/1", "sources": [], "items": ITEMS}})
    for name in ("catalog_candidates", "arxiv_candidates", "zotero_recent"):
        monkeypatch.setattr(g, name, lambda *a, **kw: {"available": True, "candidates": []})
    result = invoke("new-papers", "--since", "2026-10-16", "--record")["aster"]
    found = {c["identity"]: c for c in result["candidates"]}
    assert set(found) == {"doi:10.1287/mksc.2026.0001", "arxiv:2610.01234"}  # no releases
    assert found["doi:10.1287/mksc.2026.0001"]["venue"] == "Marketing Science"
    assert found["arxiv:2610.01234"]["url"] == "https://arxiv.org/abs/2610.01234"
    call = calls()[0]
    assert call["argv"][0] == "candidates" and "--include-shown" in call["argv"]
    assert call["argv"][call["argv"].index("--first-seen-since") + 1] == "2026-10-15"
    assert call["argv"][-2:] == ["--match-file", "-"] and "Treatment effects" in call["stdin"]
    assert result["available"] and result["complete"] and not result["failed_sources"]


def test_aster_failure_keeps_its_cursor_and_missing_aster_is_quiet(fake_aster, monkeypatch):
    reply, _ = fake_aster
    reply(candidates={"code": 2})
    with pytest.raises(RuntimeError, match="exit code 2"):
        g.aster_candidates(g.config(), ["treatment effects"], "2026-10-16", 10)
    monkeypatch.setenv("CAIRN_ASTER", "/nonexistent/aster")
    missing = g.aster_candidates(g.config(), ["treatment effects"], "2026-10-16", 10)
    assert missing["installed"] is False and missing["candidates"] == []


def test_verify_and_import_use_aster_metadata(fake_aster):
    reply, _ = fake_aster
    sources = [{"source": "crossref", "source_id": WORK["ids"]["doi"]}]
    reply(lookup={"stdout": {"work": WORK, "sources": sources}})
    verified = invoke("verify", "--doi", "https://doi.org/10.1287/mksc.2026.0001")
    assert verified["verified"] and verified["via"] == "aster" and verified["year"] == 2026

    action = {
        "op": "paper",
        "title": "Treatment effects in markets",
        "doi": "10.1287/mksc.2026.0001",
        "topics": ["treatment-effects"],
        "why": "Matches the topic.",
    }
    result = g.run_action(kb(), g.config(), action)
    assert result.endswith("from Aster")
    note = next(n for n in kb().notes().values() if n.kind == "paper")
    assert note.title == WORK["title"] and note.meta["venue"] == "Marketing Science"
    assert "two-sided markets" in note.body and note.meta["year"] == 2026


def test_web_only_findings_are_not_verification(fake_aster):
    reply, _ = fake_aster
    reply(lookup={"stdout": {"work": WORK, "sources": [{"source": "web"}]}})
    verified = invoke("verify", "--doi", "10.1287/mksc.2026.0001")
    assert not verified["verified"]  # falls through to Crossref, which the tests block


def test_aster_freshness(fake_aster):
    reply, _ = fake_aster
    reply(
        doctor={
            "code": 1,
            "stdout": {"last_success": "2000-01-01T00:00:00+00:00", "problems": ["x"]},
        }
    )
    stale = g.aster_freshness(g.config())
    assert stale["available"] and not stale["fresh"] and stale["problems"] == ["x"]
    reply(doctor={"stdout": {"last_success": g.now(g.config()).isoformat(), "problems": []}})
    assert g.aster_freshness(g.config())["fresh"]
