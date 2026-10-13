from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from cairn_garden import workflow as w
from test_regressions import g, invoke, kb, save_paper
from test_workflows import draft


def test_daily_rerun_preserves_user_metadata(setup):
    first = w.run(setup, "daily", renderer=draft)
    note = kb().resolve(first["report"])
    kb().save(
        kind="note",
        title=note.title,
        body=note.body + "\nUser: keep this observation.",
        topics=["research-catalogs", "Personal synthesis"],
        aliases=["My reading log"],
        fields={"owner": "user", "priority": "important"},
        revision=note.revision,
    )

    def empty(*args, **kwargs):
        return {
            "body": "No new discoveries today; previous observations stay useful.",
            "selected": [],
        }, {"agent": "claude"}

    again = w.run(setup, "daily", renderer=empty)
    current = kb().resolve(again["report"])
    assert "User: keep this observation." in current.body
    assert "personal-synthesis" in current.topics
    assert current.aliases == ["My reading log"]
    assert current.meta.get("owner") == "user"


def test_unverified_publisher_citation_rejected(setup):
    draft_ = {
        "body": "A useful missing paper: [Invented paper](https://publisher.example/papers/fabricated-study). Read this next.",
        "selected": [],
    }
    with pytest.raises(ValueError, match="evidence"):
        w.validate_draft(kb(), draft_, "daily", {"new-papers": {}})


def test_skipped_candidates_do_not_starve_later_discoveries(setup, monkeypatch):
    day = [datetime(2026, 10, 12, 8, tzinfo=ZoneInfo("America/Chicago"))]
    monkeypatch.setattr(g, "now", lambda cfg: day[0])
    rows = [
        {
            "source": "catalog",
            "id": "old1",
            "title": "Old irrelevant one",
            "doi": "10.1234/old1",
            "url": "https://doi.org/10.1234/old1",
        },
        {
            "source": "catalog",
            "id": "old2",
            "title": "Old irrelevant two",
            "doi": "10.1234/old2",
            "url": "https://doi.org/10.1234/old2",
        },
    ]
    monkeypatch.setattr(
        g,
        "catalog_candidates",
        lambda *a, **k: {"available": True, "complete": True, "candidates": rows.copy()},
    )
    monkeypatch.setattr(g, "DEFAULTS", {**g.DEFAULTS, "candidate_limit": 2})

    def no_relevant(*args, **kwargs):
        return {
            "body": "No relevant papers were found today; continue the existing reading chain.",
            "selected": [],
        }, {"agent": "claude"}

    first = w.run(g.config(), "daily", renderer=no_relevant)
    assert first["status"].startswith("success")
    day[0] += timedelta(days=1)
    rows.append(
        {
            "source": "catalog",
            "id": "new",
            "title": "New important paper",
            "doi": "10.1234/new",
            "url": "https://doi.org/10.1234/new",
        }
    )
    result = invoke("new-papers", "--record")
    assert "doi:10.1234/new" in [r["identity"] for r in result["catalog"]["candidates"]]


def test_already_in_kb_papers_cannot_fill_discovery_window(setup, monkeypatch):
    for suffix in ("old1", "old2"):
        save_paper(source="doi:10.1234/" + suffix, title="Existing " + suffix)
    rows = [
        {
            "source": "catalog",
            "id": name,
            "title": name,
            "doi": "10.1234/" + name,
            "url": "https://doi.org/10.1234/" + name,
        }
        for name in ("old1", "old2", "z-new")
    ]
    monkeypatch.setattr(
        g,
        "catalog_candidates",
        lambda *a, **k: {"available": True, "complete": True, "candidates": rows.copy()},
    )
    result = invoke("new-papers", "--record", "--limit", "2")
    assert any(r["identity"] == "doi:10.1234/z-new" for r in result["catalog"]["candidates"])


def test_failure_saving_completion_receipt_does_not_suppress_retry(setup, monkeypatch):
    original = g.atomic_json

    def fail_completion(path, value):
        if path.name == "manifest.json" and value.get("status", "").startswith("success"):
            raise OSError("simulated disk error writing final receipt")
        return original(path, value)

    monkeypatch.setattr(g, "atomic_json", fail_completion)
    with pytest.raises(OSError, match="receipt"):
        w.run(setup, "daily", renderer=draft)
    assert "last_digest" not in g.load_state(setup)


def test_doi_trailing_v_digits_are_identity_not_arxiv_version(ws):
    note = save_paper(source="doi:10.1234/studyv2", title="A DOI ending v2")
    assert g.note_ids(note) == {"doi:10.1234/studyv2"}
