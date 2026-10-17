"""Package setup and scheduling, with synthetic KBs and a fake launchd."""

import json
import os
import plistlib
import subprocess
from datetime import datetime

import pytest
from cairn_garden import cli, sync, sync_schedule
from cairn_garden import engine as g


@pytest.fixture
def sync_repo(ws, tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for role in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{role}_NAME", "Sync test")
        monkeypatch.setenv(f"GIT_{role}_EMAIL", "sync@example.invalid")
    worker = sync.Sync({"workspace": str(ws)})
    worker.git("init", "-b", "main")
    (ws / ".gitignore").write_text(".cairn.lock\n.env\n")
    (ws / "research/notes/reading.md").write_text("A reading note\n")
    worker.git("add", ".")
    worker.git("commit", "-m", "Initial knowledge base")
    remote = tmp_path / "origin.git"
    worker.git("init", "--bare", "-b", "main", str(remote))
    worker.git("remote", "add", "origin", str(remote))
    worker.git("push", "-u", "origin", "main")
    return g.config()


@pytest.fixture
def fake_launchd(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(
        sync_schedule.schedule, "agents_folder", lambda: home / "Library/LaunchAgents"
    )
    monkeypatch.setattr(sync_schedule.sys, "platform", "darwin")
    loaded = set()

    def call(*args, check=True):
        result = subprocess.CompletedProcess(args, 0, "", "")
        if args[0] == "print":
            result.returncode = 0 if args[1] in loaded else 1
        elif args[0] == "bootout":
            loaded.discard(args[1])
        elif args[0] == "bootstrap":
            spec = plistlib.loads(open(args[2], "rb").read())
            loaded.add(args[1] + "/" + spec["Label"])
        if check and result.returncode:
            raise sync.SyncError("not loaded")
        return result

    monkeypatch.setattr(sync_schedule, "launchctl", call)
    return loaded


def configure(cfg):
    value, _ = sync_schedule.plan(cfg, "origin", "main", "07:15")
    g.atomic_json(sync.state_dir(cfg) / "settings.json", value)
    return value


def test_preview_writes_nothing(sync_repo):
    cfg = sync_repo
    result = sync_schedule.install(cfg, dry_run=True)
    assert result["dry_run"]
    spec = result["job"]
    assert spec["StartCalendarInterval"] == {"Hour": 7, "Minute": 15}
    assert "StartInterval" not in spec and not spec.get("RunAtLoad")
    assert spec["ProgramArguments"][-3:] == ["sync", "run", "--scheduled"]
    assert result["settings"]["expected_remote_url"].endswith("origin.git")
    assert not sync.state_dir(cfg).exists()
    assert not sync_schedule.plist_path(cfg).exists()


def test_setup_status_remove_and_upgrade_use_packaged_command(sync_repo, fake_launchd):
    cfg = sync_repo
    result = sync_schedule.install(cfg)
    assert result["enabled"]
    path = sync_schedule.plist_path(cfg)
    assert path.exists() and sync.settings(cfg)["daily_time"] == "07:15"
    state = sync_schedule.status(cfg)
    assert state["installed"] and state["loaded"] and state["last_run"] is None
    # Installing a new time replaces one job instead of creating another.
    sync_schedule.install(cfg, at="06:45")
    assert len(fake_launchd) == 1
    assert plistlib.loads(path.read_bytes())["StartCalendarInterval"] == {"Hour": 6, "Minute": 45}
    assert sync_schedule.remove(cfg)["removed"]
    assert not path.exists() and not fake_launchd
    assert sync.settings(cfg)["daily_time"] == "06:45"


@pytest.mark.parametrize("at", ["24:15", "07:60", "7:15", "bad"])
def test_invalid_time_is_rejected_without_writes(sync_repo, at):
    with pytest.raises(sync.SyncError, match="--at"):
        sync_schedule.install(sync_repo, at=at, dry_run=True)
    assert not sync.state_dir(sync_repo).exists()


def test_non_macos_setup_preview_only(sync_repo, monkeypatch):
    monkeypatch.setattr(sync_schedule.sys, "platform", "linux")
    assert sync_schedule.install(sync_repo, dry_run=True)["dry_run"]
    with pytest.raises(sync.SyncError, match="macOS"):
        sync_schedule.install(sync_repo)


def test_custom_collection_reports_and_daily_due(sync_repo):
    cfg = {**sync_repo, "reports": "reviews"}
    value = configure(cfg)
    assert "reviews/" in value["note_folders"] and "finance/" in value["note_folders"]
    root = g.workspace(cfg)
    (root / "reviews").mkdir()
    (root / "reviews/review.md").write_text("New report\n")
    (root / "finance").mkdir()
    (root / "finance/new.md").write_text("A new finance note\n")
    before = datetime.fromisoformat("2026-10-16T07:14:00-05:00")
    after = before.replace(hour=8)
    assert sync.run(cfg, scheduled=True, stamp=before)["status"] == "skipped"
    done = sync.run(cfg, scheduled=True, stamp=after)
    assert done["status"] == "success" and done["pushed"]
    assert sync.run(cfg, scheduled=True, stamp=after)["status"] == "skipped"
    assert sync_schedule.status(cfg)["last_run"]["last_success_day"] == "2026-10-16"
    # A deliberate manual sync is always available, even after today's scheduled success.
    assert sync.run(cfg, stamp=after)["status"] == "success"


def test_failed_legacy_replacement_leaves_old_job_loaded(sync_repo, fake_launchd, monkeypatch):
    cfg = sync_repo
    old = sync_schedule.schedule.agents_folder() / "old-sync.plist"
    old.parent.mkdir(parents=True)
    old.write_bytes(plistlib.dumps({"Label": "example.old-sync"}))
    service = f"gui/{os.getuid()}/example.old-sync"
    fake_launchd.add(service)
    original = sync_schedule.launchctl

    def fail(*args, **kwargs):
        if args[0] == "bootstrap":
            raise sync.SyncError("Simulated new-job registration failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(sync_schedule, "launchctl", fail)
    with pytest.raises(sync.SyncError, match="registration failure"):
        sync_schedule.install(cfg, replace_plist=old)
    assert old.exists() and fake_launchd == {service}
    assert not sync_schedule.plist_path(cfg).exists()


def test_local_sync_settings_are_not_exported_to_cloud(sync_repo, tmp_path):
    from cairn_garden import ci

    configure(sync_repo)
    target = tmp_path / "cloud-export"
    ci.export_state(sync_repo, target)
    assert (target / "garden/meta.json").exists()
    assert not any(
        path.name == "sync" or path.name == "settings.json" for path in target.rglob("*")
    )


def test_manual_sync_before_daily_time_does_not_suppress_schedule(sync_repo):
    cfg = sync_repo
    configure(cfg)
    morning = datetime.fromisoformat("2026-10-16T01:00:00-05:00")
    assert sync.run(cfg, stamp=morning)["status"] == "success"
    note = g.workspace(cfg) / "research/notes/reading.md"
    note.write_text("Notes written after the early manual sync\n")
    result = sync.run(cfg, scheduled=True, stamp=morning.replace(hour=8))
    assert result["status"] == "success" and result["pushed"]


def test_explicit_legacy_replacement_keeps_its_files(sync_repo, fake_launchd):
    cfg = sync_repo
    old = sync_schedule.schedule.agents_folder() / "old-sync.plist"
    old.parent.mkdir(parents=True)
    old.write_bytes(plistlib.dumps({"Label": "example.old-sync"}))
    fake_launchd.add(f"gui/{os.getuid()}/example.old-sync")
    preview = sync_schedule.install(cfg, replace_plist=old, dry_run=True)
    assert old.exists() and preview["replace_plist"] == str(old)
    sync_schedule.install(cfg, replace_plist=old)
    assert not old.exists() and old.with_suffix(".plist.disabled").exists()
    assert len(fake_launchd) == 1


def test_cli_setup_preview_and_missing_setup_error(sync_repo, capsys):
    assert cli.main(["sync", "setup", "--dry-run"]) == 0
    assert json.loads(capsys.readouterr().out)["dry_run"]
    assert cli.main(["sync", "run"]) == 1
    assert "setup" in json.loads(capsys.readouterr().out)["error"]


def test_setup_refuses_cloud_state_branch(sync_repo):
    worker = sync.Sync({"workspace": str(g.workspace(sync_repo))})
    worker.git("checkout", "-b", "garden-state")
    with pytest.raises(sync.SyncError, match="cloud runner"):
        sync_schedule.install(sync_repo, branch="garden-state", dry_run=True)


def test_local_gardener_lock_defers_without_staging(sync_repo):
    cfg = sync_repo
    configure(cfg)
    note = g.workspace(cfg) / "research/notes/reading.md"
    note.write_text("An edit waiting for the gardener\n")
    with g.engine_lock(cfg, "reports"):
        assert sync.run(cfg)["status"] == "busy"
    worker = sync.Sync({"workspace": str(g.workspace(cfg))})
    assert not worker.output("diff", "--cached")
    assert sync.run(cfg)["status"] == "success"


def test_failed_schedule_update_restores_previous_install(sync_repo, fake_launchd, monkeypatch):
    cfg = sync_repo
    sync_schedule.install(cfg)
    old_settings = sync.settings(cfg)
    path = sync_schedule.plist_path(cfg)
    original_plist = path.read_bytes()
    original = sync_schedule.launchctl
    attempts = []

    def fail_once(*args, **kwargs):
        if args[0] == "bootstrap":
            attempts.append(args)
            if len(attempts) == 1:
                raise sync.SyncError("Simulated failed bootstrap")
        return original(*args, **kwargs)

    monkeypatch.setattr(sync_schedule, "launchctl", fail_once)
    with pytest.raises(sync.SyncError, match="Simulated"):
        sync_schedule.install(cfg, at="06:30")
    assert path.read_bytes() == original_plist
    assert sync.settings(cfg) == old_settings
    assert sync_schedule.status(cfg)["loaded"] and len(fake_launchd) == 1


def test_changed_remote_requires_setup_before_publish(sync_repo):
    cfg = sync_repo
    configure(cfg)
    worker = sync.Sync({"workspace": str(g.workspace(cfg))})
    worker.git("remote", "set-url", "origin", "/unintended/repo")
    result = sync.run(cfg)
    assert result["status"] == "needs_attention" and "Fetch remote differs" in result["error"]


def test_lock_file_must_be_ignored_before_setup(sync_repo):
    cfg = sync_repo
    (g.workspace(cfg) / ".gitignore").write_text(".env\n")
    with pytest.raises(sync.SyncError, match="gitignore"):
        sync_schedule.install(cfg, dry_run=True)
