"""Unattended runs: durable state on a branch, atomic publication, schedules and the template."""

import json
import shutil
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import yaml
from cairn_garden import ci, reports
from cairn_garden import workflow as w
from test_regressions import g
from test_workflows import draft

ROOT = Path(__file__).resolve().parents[3]


def git(repo, *argv):
    return subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.org", *argv],
        capture_output=True,
        text=True,
        check=True,
    ).stdout


@pytest.fixture
def repo(setup, tmp_path, monkeypatch):
    """The knowledge base as its own repository, with a bare remote standing in for GitHub."""
    monkeypatch.setattr(g, "DEFAULTS", {**g.DEFAULTS, "workspace_id": "test-kb"})
    kb = Path(setup["workspace"])
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True)
    git(kb, "init", "-q", "-b", "main")
    (kb / ".gitignore").write_text(".cairn.lock\n")
    git(kb, "add", "-A")
    git(kb, "commit", "-q", "-m", "knowledge base")
    git(kb, "remote", "add", "origin", str(remote))
    git(kb, "push", "-q", "-u", "origin", "main")
    return g.config(), kb, remote


def clone(remote, path):
    subprocess.run(["git", "clone", "-q", str(remote), str(path)], check=True)
    return path


def fresh_runner(monkeypatch, tmp_path, name):
    """A new runner: no gardener home at all."""
    monkeypatch.setattr(g, "HOME", tmp_path / name)


def test_publish_pushes_report_and_state_together(repo, tmp_path, monkeypatch):
    cfg, kb, remote = repo
    assert ci.restore(cfg, kb, "garden-state", "origin", allow_empty=True)["empty"]
    run = w.run(cfg, "daily", renderer=draft)
    result = ci.publish(cfg, kb, "garden-state", "origin", None)
    assert result["published"], result
    files = git(remote, "ls-tree", "-r", "--name-only", "main").split()
    assert "gardening/" + run["report_id"] in files and "gardening/index.md" in files
    state = git(remote, "ls-tree", "-r", "--name-only", "garden-state").split()
    assert "garden/state.json" in state and f"garden/runs/{run['id']}/manifest.json" in state
    assert not any("facts" in f or f.endswith(".log") for f in state)
    assert "garden/state.json" not in files  # state stays off the knowledge base's history

    # A fresh runner restores the state: the period is complete and nothing is redelivered.
    fresh_runner(monkeypatch, tmp_path, "runner-2")
    other = clone(remote, tmp_path / "checkout-2")
    monkeypatch.setenv("CAIRN_WORKSPACE", str(other))
    cfg2 = g.config()
    assert ci.restore(cfg2, other, "garden-state", "origin", allow_empty=False)["imported"]
    assert not w.due(cfg2, "daily", g.now(cfg2).replace(hour=23))
    ledger = g.read_json(g.state_dir(cfg2) / "discoveries.json", {})
    assert ledger["candidates"]["doi:10.1234/one"]["status"] == "delivered"
    assert ci.publish(cfg2, other, "garden-state", "origin", None)["reason"] == "nothing to publish"


def test_missing_corrupt_or_foreign_state_is_refused(repo, tmp_path):
    cfg, kb, _ = repo
    with pytest.raises(ci.StateError, match="allow-empty"):
        ci.restore(cfg, kb, "garden-state", "origin", allow_empty=False)
    folder = tmp_path / "exported"
    ci.export_state(cfg, folder)
    (folder / "garden" / "state.json").write_text("{not json")
    with pytest.raises(ci.StateError, match="corrupt"):
        ci.import_state(cfg, folder)
    ci.export_state(cfg, folder)
    with pytest.raises(ci.StateError, match="belongs to"):
        ci.import_state({**cfg, "workspace_id": "another-kb"}, folder)


def test_budget_actions_and_gate_survive_a_fresh_runner(repo, tmp_path, monkeypatch):
    cfg, kb, _ = repo
    day = g.now(cfg).date().isoformat()
    g.atomic_json(g.state_dir(cfg) / "zotero-writes.json", {"days": {day: 25}, "creations": {}})
    g.atomic_json(g.state_dir(cfg) / "actions.json", {"abc": {"status": "applied"}})
    ci.export_state(cfg, tmp_path / "exported")
    fresh_runner(monkeypatch, tmp_path, "runner-2")
    ci.import_state(cfg, tmp_path / "exported")
    assert g.read_json(g.state_dir(cfg) / "zotero-writes.json", {})["days"][day] == 25
    assert g.read_json(g.state_dir(cfg) / "actions.json", {})["abc"]["status"] == "applied"


@pytest.mark.parametrize("hosted_identity", [False, True])
def test_remote_commit_during_a_run_is_kept(repo, tmp_path, monkeypatch, hosted_identity):
    cfg, kb, remote = repo
    if hosted_identity:
        monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
        monkeypatch.setenv("GIT_CONFIG_KEY_0", "user.useConfigOnly")
        monkeypatch.setenv("GIT_CONFIG_VALUE_0", "true")
        workflow = yaml.safe_load((ROOT / ".github/workflows/garden.yml").read_text())
        for role in ("AUTHOR", "COMMITTER"):
            for field in ("NAME", "EMAIL"):
                key = f"GIT_{role}_{field}"
                monkeypatch.setenv(key, workflow["jobs"]["garden"]["env"][key])
    ci.restore(cfg, kb, "garden-state", "origin", allow_empty=True)
    laptop = clone(remote, tmp_path / "laptop")
    (laptop / "research/notes").mkdir(parents=True, exist_ok=True)
    (laptop / "research/notes/from-laptop.md").write_text(
        "---\ntitle: Laptop\n---\nWritten away.\n"
    )
    git(laptop, "add", "-A")
    git(laptop, "commit", "-q", "-m", "a note from the laptop")
    git(laptop, "push", "-q")
    w.run(cfg, "daily", renderer=draft)
    result = ci.publish(cfg, kb, "garden-state", "origin", None)
    assert result["published"] and result["attempts"] == 2
    files = git(remote, "ls-tree", "-r", "--name-only", "main").split()
    assert "research/notes/from-laptop.md" in files
    assert any(f.startswith("gardening/daily/") for f in files)


def test_conflict_goes_to_a_side_branch_without_advancing_state(repo, tmp_path):
    cfg, kb, remote = repo
    ci.restore(cfg, kb, "garden-state", "origin", allow_empty=True)
    first = w.run(cfg, "daily", renderer=draft)
    assert ci.publish(cfg, kb, "garden-state", "origin", None)["published"]
    state_before = git(remote, "rev-parse", "garden-state")
    laptop = clone(remote, tmp_path / "laptop")
    report = laptop / "gardening" / first["report_id"]
    report.write_text(report.read_text() + "\nUser: an edit on the laptop.\n")
    git(laptop, "commit", "-qam", "edit the digest")
    git(laptop, "push", "-q")
    w.run(cfg, "daily", renderer=quiet_day)  # a rerun appends an update to the same report
    result = ci.publish(cfg, kb, "garden-state", "origin", None)
    assert not result["published"] and "conflict" in result["reason"]
    assert result["branch"] in git(remote, "branch", "--list", "garden/*")
    assert git(remote, "rev-parse", "garden-state") == state_before
    assert "User: an edit on the laptop." in git(
        remote, "show", f"main:gardening/{first['report_id']}"
    )


def quiet_day(*args, **kwargs):
    return {"body": "No new discoveries today; earlier notes stay useful.", "selected": []}, {
        "agent": "claude"
    }


def test_failed_push_is_not_delivered(repo):
    cfg, kb, _ = repo
    ci.restore(cfg, kb, "garden-state", "origin", allow_empty=True)
    w.run(cfg, "daily", renderer=draft)
    git(kb, "remote", "set-url", "origin", "/nonexistent/remote.git")
    result = ci.publish(cfg, kb, "garden-state", "origin", None)
    assert not result["published"] and result["reason"] == "push failed"
    text = ci.summary(cfg, "daily", result)
    assert "NOT published" in text and "**Overall: incomplete**" in text


def test_note_changes_alone_are_published(repo):
    cfg, kb, remote = repo
    ci.restore(cfg, kb, "garden-state", "origin", allow_empty=True)
    g.kb_open(cfg).save(kind="note", title="Catalog entry point", body="Refreshed by the catalog.")
    assert ci.publish(cfg, kb, "garden-state", "origin", None)["published"]
    assert "research/notes/catalog-entry-point.md" in git(
        remote, "ls-tree", "-r", "--name-only", "main"
    )


def test_notes_with_non_ascii_and_spaced_names_are_published(repo):
    cfg, kb, remote = repo
    ci.restore(cfg, kb, "garden-state", "origin", allow_empty=True)
    g.kb_open(cfg).save(kind="note", title="Pólya urns and Erdős", body="Accented title.")
    (kb / "research" / "notes" / "two words.md").write_text("A spaced file name.\n")
    assert ci.publish(cfg, kb, "garden-state", "origin", None)["published"]
    names = git(remote, "-c", "core.quotePath=false", "ls-tree", "-r", "--name-only", "main")
    assert "research/notes/pólya-urns-and-erdős.md" in names
    assert "research/notes/two words.md" in names


def test_changes_outside_the_gardeners_scope_are_refused(repo):
    cfg, kb, _ = repo
    ci.restore(cfg, kb, "garden-state", "origin", allow_empty=True)
    (kb / "tools.py").write_text("print('not knowledge')")
    result = ci.publish(cfg, kb, "garden-state", "origin", None)
    assert not result["published"] and result["paths"] == ["tools.py"]


def test_workspace_id_makes_state_independent_of_the_checkout_path(ws, tmp_path, monkeypatch):
    monkeypatch.setattr(g, "DEFAULTS", {**g.DEFAULTS, "workspace_id": "my-kb"})
    cfg = g.config()
    moved = {**cfg, "workspace": str(tmp_path / "elsewhere")}
    assert g.state_dir(cfg) == g.HOME / "workspaces" / "my-kb"
    assert w.config_hash(cfg) == w.config_hash(moved)
    assert g.workspace_identity(cfg) == g.workspace_identity(moved) == "id:my-kb"
    with pytest.raises(ValueError):
        g.workspace_key({**cfg, "workspace_id": "../escape"})


# Schedules --------------------------------------------------------------------------------------

CHICAGO = ZoneInfo("America/Chicago")


def triggers(day):
    """The template's UTC triggers on one Chicago calendar day."""
    minute, hours = ci.CRON.split()[:2]
    found = []
    for offset in (-1, 0, 1):
        utc_day = datetime(day.year, day.month, day.day, tzinfo=ZoneInfo("UTC")) + timedelta(
            days=offset
        )
        for hour in map(int, hours.split(",")):
            local = utc_day.replace(hour=hour, minute=int(minute)).astimezone(CHICAGO)
            if local.date() == day:
                found.append(local)
    return sorted(found)


@pytest.mark.parametrize("start", ["2026-03-02", "2026-03-09", "2026-10-26", "2026-11-02"])
def test_triggers_reach_every_due_window_across_daylight_saving(start):
    monday = datetime.fromisoformat(start).date()
    for offset in range(7):
        day = monday + timedelta(days=offset)
        times = triggers(day)
        assert len([t for t in times if t.strftime("%H:%M") >= "07:30"]) >= 2, day  # + catch-up
    assert len([t for t in triggers(monday) if t.strftime("%H:%M") >= "10:30"]) >= 2


def test_due_is_idempotent_and_catches_up(setup):
    sunday = datetime(2026, 11, 1, 7, 40, tzinfo=CHICAGO)  # the day clocks fall back
    assert w.due(setup, "daily", sunday)
    state = g.load_state(setup)
    state["last_digest"] = sunday.date().isoformat()
    g.save_state(setup, state)
    assert not w.due(setup, "daily", sunday.replace(hour=13))  # repeated trigger
    late = datetime(2026, 11, 3, 14, 40, tzinfo=CHICAGO)  # Monday's triggers were dropped
    assert w.due(setup, "weekly", late)
    state["last_weekly"] = "2026-11-03"
    g.save_state(setup, state)
    assert not w.due(setup, "weekly", late + timedelta(days=2))


def test_template_is_a_thin_pinned_caller():
    text = ci.template("v9.9.9")
    spec = yaml.safe_load(text)
    assert spec[True]["schedule"] == [{"cron": ci.CRON}]
    assert spec["concurrency"] == {"group": "cairn-garden", "cancel-in-progress": False}
    job = spec["jobs"]["garden"]
    assert job["uses"].endswith("garden.yml@v9.9.9") and job["with"]["version"] == "v9.9.9"
    assert f"garden.yml@v{ci.__version__}" in ci.template()


def test_reusable_workflow_declares_its_interface():
    spec = yaml.safe_load((ROOT / ".github/workflows/garden.yml").read_text())
    call = spec[True]["workflow_call"]
    assert {"version", "mode", "scheduled", "allow-empty-state"} <= set(call["inputs"])
    assert "ZOTERO_API_KEY" in call["secrets"]
    steps = [s.get("name") for s in spec["jobs"]["garden"]["steps"]]
    assert steps.index("Restore garden state") < steps.index("Daily digest")
    assert steps.index("Weekly review") < steps.index("Publish reports and state")
    assert spec["jobs"]["garden"]["permissions"] == {"contents": "write"}


# Catalog ----------------------------------------------------------------------------------------


def stale_catalog(days):
    folder = g.catalog_dir()
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "catalog.sqlite").write_bytes(b"")
    stamp = (datetime.now(ZoneInfo("UTC")) - timedelta(days=days)).isoformat()
    g.atomic_json(folder / "update-state.json", {"last_success_at": stamp})


def test_stale_catalog_warns_and_required_catalog_fails(setup, monkeypatch):
    stale_catalog(20)
    result = w.run(setup, "weekly", renderer=draft)
    assert any("journal catalog is stale" in x for x in result["warnings"])
    stale_catalog(1)
    assert g.catalog_freshness(setup)["fresh"]
    shutil.rmtree(g.catalog_dir())
    with pytest.raises(RuntimeError, match="catalog is missing"):
        w.run({**setup, "catalog_required": True}, "weekly", renderer=draft)


def test_last_weeks_catalog_is_refreshed_before_the_next_review(setup):
    stale_catalog(6.9)  # refreshed in last Monday's slot, finished a little after it began
    assert g.catalog_freshness(setup)["fresh"]  # the review alone would accept it
    assert ci.main(["catalog-fresh", "--max-age", "6"]) == 3
    stale_catalog(1)  # a retry later in the same weekly cycle keeps it
    assert ci.main(["catalog-fresh", "--max-age", "6"]) == 0
    workflow = (ROOT / ".github/workflows/garden.yml").read_text()
    assert "ci catalog-fresh --max-age 6" in workflow


def test_summary_reports_pending_approvals(setup):
    w.run(setup, "weekly", renderer=draft)
    text = ci.summary(setup, None, {"published": True, "pushed": []})
    assert "pending approvals in `weekly/" in text and ": 1" in text
    assert "**Overall: complete**" in text
    assert json.loads(json.dumps(reports.moves(setup))) == {}
