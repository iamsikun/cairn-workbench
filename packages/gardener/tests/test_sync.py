import fcntl
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from cairn_garden import engine as g
from cairn_garden import sync


def git(repo, *args):
    env = dict(os.environ)
    env.update(
        GIT_CONFIG_GLOBAL="/dev/null",
        GIT_CONFIG_NOSYSTEM="1",
        GIT_AUTHOR_NAME="Sync test",
        GIT_AUTHOR_EMAIL="sync@example.invalid",
        GIT_COMMITTER_NAME="Sync test",
        GIT_COMMITTER_EMAIL="sync@example.invalid",
    )
    return subprocess.run(
        ["/usr/bin/git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    ).stdout.strip()


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="cairn-sync-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.remote = self.root / "remote.git"
        self.local = self.root / "local"
        self.cloud = self.root / "cloud"
        self.state = self.root / "state"
        self.state.mkdir()
        git(self.root, "init", "--bare", "--initial-branch=main", str(self.remote))
        git(self.root, "clone", str(self.remote), str(self.local))
        (self.local / "research").mkdir()
        (self.local / ".gitignore").write_text(".cairn.lock\n.env\n")
        (self.local / ".cairn").touch()
        (self.local / "research/reading.md").write_text("Original note\n")
        git(self.local, "add", ".")
        git(self.local, "commit", "-m", "Initial knowledge base")
        git(self.local, "push", "-u", "origin", "main")
        git(self.root, "clone", str(self.remote), str(self.cloud))
        self.config = dict(
            workspace=str(self.local),
            expected_remote_url=str(self.remote),
            note_folders=["research/", "gardening/"],
            daily_time="07:15",
            branch="main",
            remote="origin",
        )
        self.job = sync.Sync(self.config)
        self.job.env.update(
            GIT_CONFIG_GLOBAL="/dev/null",
            GIT_CONFIG_NOSYSTEM="1",
            GIT_AUTHOR_NAME="Sync test",
            GIT_AUTHOR_EMAIL="sync@example.invalid",
            GIT_COMMITTER_NAME="Sync test",
            GIT_COMMITTER_EMAIL="sync@example.invalid",
        )

    def publish_cloud(self, filename="gardening/daily/test.md", text="Cloud report\n"):
        path = self.cloud / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        git(self.cloud, "add", ".")
        git(self.cloud, "commit", "-m", "Cloud gardener update")
        git(self.cloud, "push", "origin", "main")

    def assert_clean_and_synced(self):
        self.assertEqual(git(self.local, "status", "--porcelain"), "")
        self.assertEqual(
            git(self.local, "rev-parse", "HEAD"), git(self.remote, "rev-parse", "main")
        )

    def test_local_and_cloud_changes_merge_then_no_op(self):
        (self.local / "research/reading.md").write_text("My updated reading notes\n")
        (self.local / "research/new.md").write_text("A new topic\n")
        self.publish_cloud()
        result = self.job.run()
        self.assertTrue(result["pushed"])
        self.assertEqual(len(result["commits_created"]), 1)
        self.assertEqual(
            (self.local / "research/reading.md").read_text(), "My updated reading notes\n"
        )
        self.assertTrue((self.local / "gardening/daily/test.md").exists())
        self.assert_clean_and_synced()
        head = git(self.local, "rev-parse", "HEAD")
        self.assertFalse(self.job.run()["pushed"])
        self.assertEqual(git(self.local, "rev-parse", "HEAD"), head)

    def test_cloud_only_fast_forwards(self):
        self.publish_cloud()
        self.assertFalse(self.job.run()["pushed"])
        self.assert_clean_and_synced()

    def test_conflict_preserves_notes_without_markers(self):
        (self.local / "research/reading.md").write_text("My version\n")
        self.publish_cloud("research/reading.md", "Cloud version\n")
        remote_before = git(self.remote, "rev-parse", "main")
        with self.assertRaisesRegex(sync.SyncError, "manual attention"):
            self.job.run()
        self.assertEqual((self.local / "research/reading.md").read_text(), "My version\n")
        self.assertEqual(git(self.local, "status", "--porcelain"), "")
        self.assertFalse((self.local / ".git/MERGE_HEAD").exists())
        self.assertEqual(git(self.remote, "rev-parse", "main"), remote_before)
        self.assertEqual(len(self.job.created), 1)

    def test_preserves_partial_staging(self):
        (self.local / "research/reading.md").write_text("Staged portion\n")
        git(self.local, "add", "research/reading.md")
        (self.local / "research/reading.md").write_text("Staged portion\nUnstaged portion\n")
        staged = git(self.local, "diff", "--cached")
        unstaged = git(self.local, "diff")
        with self.assertRaisesRegex(sync.SyncError, "Staged changes"):
            self.job.run()
        self.assertEqual(git(self.local, "diff", "--cached"), staged)
        self.assertEqual(git(self.local, "diff"), unstaged)

    def test_wrong_branch_is_untouched(self):
        git(self.local, "checkout", "-b", "manual-work")
        (self.local / "research/reading.md").write_text("Manual work\n")
        with self.assertRaisesRegex(sync.SyncError, "not on main"):
            self.job.run()
        self.assertEqual(git(self.local, "diff", "--name-only"), "research/reading.md")

    def test_ignored_secret_stays_local(self):
        (self.local / ".env").write_text("EXAMPLE_SECRET=synthetic\n")
        (self.local / "research/new.md").write_text("New note\n")
        self.job.run()
        self.assertNotIn(".env", git(self.local, "ls-files").splitlines())
        self.assertTrue((self.local / ".env").exists())
        self.assert_clean_and_synced()

    def test_unexpected_untracked_file_stops_before_staging(self):
        (self.local / "private.txt").write_text("Do not publish\n")
        (self.local / "research/new.md").write_text("New note\n")
        with self.assertRaisesRegex(sync.SyncError, "untracked files"):
            self.job.run()
        self.assertEqual(git(self.local, "diff", "--cached"), "")
        self.assertEqual(len(self.job.created), 0)

    def test_cairn_writer_lock_defers_sync(self):
        self.job.NOTE_LOCK_WAIT = 0.3
        with (self.local / ".cairn.lock").open("a") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            with self.assertRaises(sync.Busy):
                self.job.run()
        self.job.run()
        self.assert_clean_and_synced()

    def test_brief_cairn_save_is_waited_for(self):
        import threading

        (self.local / "research/new.md").write_text("Saved while a note was being written\n")
        handle = (self.local / ".cairn.lock").open("a")
        fcntl.flock(handle, fcntl.LOCK_EX)
        threading.Timer(0.5, handle.close).start()
        self.job.run()
        self.assert_clean_and_synced()

    def test_offline_fetch_preserves_local_commit(self):
        (self.local / "research/new.md").write_text("Unsynced local work\n")
        original = self.job.git

        def offline(*args, **kwargs):
            if args[0] == "fetch":
                raise sync.SyncError("Simulated offline network")
            return original(*args, **kwargs)

        self.job.git = offline
        with self.assertRaisesRegex(sync.SyncError, "offline"):
            self.job.run()
        self.assertEqual(git(self.local, "status", "--porcelain"), "")
        self.assertEqual(len(self.job.created), 1)
        self.job.git = original
        self.job.run()
        self.assert_clean_and_synced()

    def test_cloud_push_race_retries_without_force(self):
        (self.local / "research/new.md").write_text("Local work\n")
        original = self.job.git
        pushes = []

        def racing(*args, **kwargs):
            if args[0] == "push":
                pushes.append(args)
                if len(pushes) == 1:
                    self.publish_cloud()
            return original(*args, **kwargs)

        self.job.git = racing
        self.job.run()
        self.assertEqual(len(pushes), 2)
        self.assertFalse(any("force" in arg for args in pushes for arg in args))
        self.assert_clean_and_synced()
        self.assertTrue((self.local / "research/new.md").exists())
        self.assertTrue((self.local / "gardening/daily/test.md").exists())

    def test_distinct_push_remote_is_rejected(self):
        git(self.local, "config", "remote.origin.pushurl", "/unintended/repository")
        with self.assertRaisesRegex(sync.SyncError, "Push remote differs"):
            self.job.run()

    def test_renamed_note_and_tracked_config_sync(self):
        (self.local / "research/reading.md").rename(self.local / "research/renamed.md")
        (self.local / ".gitignore").write_text(".cairn.lock\n.env\n*.key\n")
        self.job.run()
        self.assert_clean_and_synced()
        self.assertIn(
            "research/renamed.md", git(self.remote, "ls-tree", "-r", "--name-only", "main")
        )

    def test_command_records_success_and_later_failure(self):
        import sys

        state = self.state / "workspaces" / g.workspace_key(self.config) / "sync"
        state.mkdir(parents=True)
        (state / "settings.json").write_text(json.dumps(self.config))
        self.job.env.update(
            CAIRN_WORKSPACE=str(self.local),
            CAIRN_GARDEN_STATE=str(self.state),
            CAIRN_WORKBENCH_CONFIG=str(self.root / "missing.toml"),
        )
        command = [sys.executable, "-m", "cairn_garden", "sync", "run"]
        done = subprocess.run(command, env=self.job.env, capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        status = json.loads((state / "status.json").read_text())
        self.assertEqual(status["status"], "success")
        last_success = status["last_success_at"]
        (self.local / "research/reading.md").write_text("My version\n")
        self.publish_cloud("research/reading.md", "Cloud version\n")
        failed = subprocess.run(command, env=self.job.env, capture_output=True, text=True)
        self.assertEqual(failed.returncode, 1, failed.stderr)
        status = json.loads((state / "status.json").read_text())
        self.assertEqual(status["status"], "needs_attention")
        self.assertEqual(status["last_success_at"], last_success)
        self.assertIn("manual attention", status["error"])
        self.assertIn("Sync stopped", (state / "sync.log").read_text())


if __name__ == "__main__":
    unittest.main()
