"""Quick sync: commit and push once edits settle, back off on failures, stay idle-cheap."""

import fcntl
import os
import plistlib
import subprocess
import time
from datetime import datetime

import pytest
from cairn_garden import cli, sync, sync_schedule
from cairn_garden import engine as g
from test_sync_setup import configure, fake_launchd, sync_repo  # noqa: F401 - fixtures

QUIET = sync.QUIET_SECONDS


def at(seconds):
    return datetime.fromtimestamp(seconds).astimezone()


def tick(cfg, seconds):
    return sync.run(cfg, quick=True, stamp=at(seconds))


def save(path, text, seconds):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    os.utime(path, (seconds, seconds))


def note(title, kind="paper", body="Body\n"):
    return f"---\ntitle: {title}\nkind: {kind}\n---\n{body}"


def worker(cfg):
    return sync.Sync({"workspace": str(g.workspace(cfg))})


def commits(cfg):
    return int(worker(cfg).output("rev-list", "--count", "HEAD"))


def remote_head(cfg):
    return worker(cfg).output("ls-remote", "origin", "refs/heads/main").split()[0]


def subject(cfg):
    return worker(cfg).output("log", "-1", "--format=%s")


def log_lines(cfg):
    path = sync.state_dir(cfg) / "sync.log"
    return path.read_text().splitlines() if path.exists() else []


@pytest.fixture
def quick(sync_repo):  # noqa: F811 - pytest fixture
    configure(sync_repo)
    return sync_repo


@pytest.fixture
def git_calls(monkeypatch):
    calls = []
    original = subprocess.run

    def record(command, *args, **kwargs):
        if command and command[0] == "git":
            calls.append(command)
        return original(command, *args, **kwargs)

    monkeypatch.setattr(sync.subprocess, "run", record)
    return calls


def network(calls):
    return [c for c in calls if {"fetch", "push", "ls-remote", "pull"} & set(c)]


def test_settled_save_makes_one_commit_and_one_push(quick, git_calls):
    cfg, start = quick, time.time()
    before = commits(cfg)
    save(
        g.workspace(cfg) / "research/papers/attention.md", note("Attention Is All You Need"), start
    )
    assert tick(cfg, start + 60)["reason"] == "waiting for edits to settle"
    assert not network(git_calls)
    done = tick(cfg, start + QUIET + 1)
    assert done["status"] == "success" and done["pushed"] and done["trigger"] == "quick"
    assert commits(cfg) == before + 1
    assert remote_head(cfg) == worker(cfg).output("rev-parse", "HEAD")
    assert subject(cfg) == "reading: Attention Is All You Need"
    git_calls.clear()
    assert tick(cfg, start + QUIET + 61)["reason"] == "no local changes"
    assert not network(git_calls)


def test_saves_closer_than_the_quiet_period_become_one_commit(quick):
    cfg, start = quick, time.time()
    before = commits(cfg)
    path = g.workspace(cfg) / "research/papers/reading-session.md"
    for step in range(5):
        moment = start + 30 * step
        save(path, note("A long reading session", body=f"Step {step}\n"), moment)
        assert tick(cfg, moment + 29)["status"] == "skipped"
    last = start + 120
    assert tick(cfg, last + QUIET - 1)["reason"] == "waiting for edits to settle"
    assert commits(cfg) == before  # nothing is committed before the quiet period ends
    assert tick(cfg, last + QUIET + 1)["pushed"]
    assert commits(cfg) == before + 1
    assert "Step 4" in path.read_text()


def test_idle_tick_makes_no_network_call_and_no_log_line(quick, git_calls):
    cfg = quick
    assert sync.run(cfg)["status"] == "success"
    lines = log_lines(cfg)
    git_calls.clear()
    for minute in range(5):
        assert tick(cfg, time.time() + 60 * minute)["reason"] == "no local changes"
    assert git_calls and not network(git_calls)
    assert all("--no-optional-locks" in c or "rev-list" in c for c in git_calls)
    assert log_lines(cfg) == lines


def test_hand_edit_to_a_tracked_note_is_synced(quick):
    cfg = quick
    path = g.workspace(cfg) / "research/notes/reading.md"
    path.write_text("Edited in a text editor\n")
    os.utime(path, (time.time() - 600, time.time() - 600))
    done = tick(cfg, time.time())
    assert done["status"] == "success" and done["pushed"]
    assert subject(cfg) == "note: reading"


def test_deleted_note_is_detected(quick):
    cfg = quick
    (g.workspace(cfg) / "research/notes/reading.md").unlink()
    assert tick(cfg, time.time() + QUIET + 1)["pushed"]
    assert subject(cfg) == "note: reading (removed)"


def test_commit_messages_name_notes_by_kind_and_title(quick):
    cfg = quick
    root = g.workspace(cfg)
    job = sync.Sync(sync.settings(cfg))
    save(root / "research/ideation/cheap-labels.md", "No front matter\n", time.time())
    job.run()
    assert subject(cfg) == "idea: cheap-labels"
    save(root / "research/topics/recsys.md", note("Recommendation systems", "topic"), 0)
    save(root / "research/papers/tiger.md", note("Generative retrieval"), 0)
    save(root / "research/notes/misc.md", note("Loose thoughts", "note"), 0)
    save(root / "gardening/daily/2026-11-25.md", "# Daily\n", 0)
    job.run()
    assert subject(cfg) == "notes: Generative retrieval, Loose thoughts and 2 more"
    body = worker(cfg).output("log", "-1", "--format=%b")
    assert "- topic: Recommendation systems" in body and "- report: 2026-11-25" in body
    save(root / "research/papers/tiger.md", note("Generative retrieval", body="More\n"), 9)
    save(root / "research/ideation/cheap-labels.md", note("Cheap labels", "idea"), 0)
    job.run()
    assert subject(cfg) == "notes: Generative retrieval and Cheap labels"


def test_note_being_written_is_never_committed(quick, monkeypatch):
    cfg = quick
    monkeypatch.setattr(sync.Sync, "NOTE_LOCK_WAIT", 0.2)
    before = commits(cfg)
    save(g.workspace(cfg) / "research/papers/half.md", note("Half written"), 0)
    with (g.workspace(cfg) / ".cairn.lock").open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        assert tick(cfg, time.time())["status"] == "busy"
        assert commits(cfg) == before and not worker(cfg).output("diff", "--cached")
    assert not any("Deferred" in line for line in log_lines(cfg))
    assert tick(cfg, time.time())["pushed"] and commits(cfg) == before + 1


def test_failures_back_off_log_sparingly_and_recover(quick, tmp_path, git_calls):
    cfg = quick
    remote, hidden = tmp_path / "origin.git", tmp_path / "offline.git"
    save(g.workspace(cfg) / "research/papers/offline.md", note("Written offline"), 0)
    remote.rename(hidden)
    now = time.time()
    delays = []
    for _ in range(7):
        result = tick(cfg, now)
        assert result["status"] == "needs_attention"
        retry = sync.epoch(result["backoff"]["retry_at"])
        delays.append(int(retry - now))
        git_calls.clear()
        assert tick(cfg, retry - 1)["reason"] == "waiting to retry after a failure"
        assert not network(git_calls)
        now = retry
    assert delays == [120, 240, 480, 960, 1800, 1800, 1800]
    errors = [line for line in log_lines(cfg) if " ERROR " in line]
    assert len(errors) == 2
    assert "Sync stopped" in errors[0] and "every 30 minutes" in errors[1]
    # The local commit is kept while offline.
    assert subject(cfg) == "reading: Written offline"
    # A day later, one reminder.
    now += sync.REMINDER_SECONDS
    tick(cfg, now)
    tick(cfg, now + 1800)
    errors = [line for line in log_lines(cfg) if " ERROR " in line]
    assert len(errors) == 3 and "Still failing since" in errors[2]
    hidden.rename(remote)
    done = tick(cfg, now + 3600)
    assert done["status"] == "success" and done["pushed"] and "backoff" not in done
    assert "Recovered after 9 failed attempts" in log_lines(cfg)[-2]
    assert sync.state_dir(cfg).joinpath("status.json").stat().st_size < 4096


def test_conflict_keeps_local_commits_without_markers_and_backs_off(quick, tmp_path, git_calls):
    cfg = quick
    root = g.workspace(cfg)
    cloud = tmp_path / "cloud"
    worker(cfg).git("clone", str(tmp_path / "origin.git"), str(cloud))
    other = sync.Sync({"workspace": str(cloud)})
    (cloud / "research/notes/reading.md").write_text("Cloud version\n")
    other.git("commit", "-am", "Cloud edit")
    other.git("push", "origin", "main")
    (root / "research/notes/reading.md").write_text("My version\n")
    result = tick(cfg, time.time() + QUIET + 1)
    assert result["status"] == "needs_attention" and "manual attention" in result["error"]
    assert len(result["commits_created"]) == 1
    assert (root / "research/notes/reading.md").read_text() == "My version\n"
    assert worker(cfg).output("status", "--porcelain") == ""
    assert subject(cfg) == "note: reading"
    git_calls.clear()
    retry = sync.epoch(result["backoff"]["retry_at"])
    assert tick(cfg, retry - 1)["status"] == "skipped" and not network(git_calls)


def test_setup_preview_shows_the_quick_job_and_quiet_period(quick):
    cfg = quick
    result = sync_schedule.install(cfg, dry_run=True, quiet=300)
    spec = result["quick_job"]
    assert spec["StartInterval"] == 60 and "StartCalendarInterval" not in spec
    assert spec["ProgramArguments"][-3:] == ["sync", "run", "--quick"]
    assert spec["Label"].endswith(".quick") and spec["StandardErrorPath"] == "/dev/null"
    assert result["quiet_minutes"] == 5 and result["settings"]["quiet_seconds"] == 300
    assert result["job"]["StartInterval"] == 3600
    assert not sync_schedule.quick_plist_path(cfg).exists()
    with pytest.raises(sync.SyncError, match="quiet"):
        sync_schedule.install(cfg, dry_run=True, quiet=10)


def test_cli_setup_preview_takes_quiet_minutes(quick, capsys):
    import json

    assert cli.main(["sync", "setup", "--dry-run", "--quiet-minutes", "3"]) == 0
    assert json.loads(capsys.readouterr().out)["settings"]["quiet_seconds"] == 180
    assert cli.main(["sync", "setup", "--dry-run", "--no-quick"]) == 0
    preview = json.loads(capsys.readouterr().out)
    assert preview["quick_job"] is None and not preview["settings"]["quick"]
    assert cli.main(["sync", "run", "--quick"]) == 0
    assert json.loads(capsys.readouterr().out)["reason"] == "no local changes"


def test_setup_installs_upgrades_and_removes_the_quick_job(quick, fake_launchd):  # noqa: F811
    cfg = quick
    sync_schedule.install(cfg)
    path = sync_schedule.quick_plist_path(cfg)
    assert plistlib.loads(path.read_bytes())["ProgramArguments"][-1] == "--quick"
    state = sync_schedule.status(cfg)
    assert state["quick_installed"] and state["quick_loaded"]
    # Re-running setup upgrades both jobs in place.
    sync_schedule.install(cfg, quiet=240)
    assert len(fake_launchd) == 2 and sync.settings(cfg)["quiet_seconds"] == 240
    # Turning quick sync off keeps the daily job alone.
    sync_schedule.install(cfg, quick=False)
    assert not path.exists() and len(fake_launchd) == 1
    assert sync_schedule.plist_path(cfg).exists()
    save(g.workspace(cfg) / "research/papers/later.md", note("Later"), 0)
    assert tick(cfg, time.time())["reason"] == "quick sync is off"
    sync_schedule.install(cfg)
    assert path.exists() and len(fake_launchd) == 2
    assert sync_schedule.remove(cfg)["removed"]
    assert not path.exists() and not fake_launchd
