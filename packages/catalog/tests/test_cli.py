"""The installed command finds its data, preferences and workspace from configuration alone."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from catalog_fixtures import synthetic_catalog

from cairn.store import KB, init


def run(env, *args):
    result = subprocess.run(
        [sys.executable, "-m", "cairn_catalog", *args],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


class CommandTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="cairn-catalog-cli-")
        self.root = Path(self.tmp.name)
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("CAIRN_")}
        self.env["HOME"] = str(self.root / "home")
        self.env.pop("XDG_CONFIG_HOME", None)
        self.env.pop("XDG_DATA_HOME", None)

    def tearDown(self):
        self.tmp.cleanup()

    def test_defaults_stay_under_home(self):
        resolved = json.loads(run(self.env, "paths"))
        home = self.root / "home"
        self.assertEqual(resolved["data"], str(home / ".local/share/cairn-workbench/catalog"))
        self.assertEqual(
            resolved["preferences"], str(home / ".config/cairn-workbench/catalog-preferences.yaml")
        )
        self.assertIsNone(resolved["workspace"])
        self.assertEqual(resolved["collection"], "research")

    def test_config_file_and_environment_override(self):
        config = self.root / "home/.config/cairn-workbench/config.toml"
        config.parent.mkdir(parents=True)
        config.write_text(
            f'workspace = "{self.root / "kb"}"\n[catalog]\ndata_dir = "{self.root / "data"}"\n'
        )
        resolved = json.loads(run(self.env, "paths"))
        self.assertEqual(
            (resolved["workspace"], resolved["data"]),
            (str(self.root / "kb"), str(self.root / "data")),
        )
        resolved = json.loads(
            run({**self.env, "CAIRN_CATALOG_DIR": str(self.root / "other")}, "paths")
        )
        self.assertEqual(resolved["data"], str(self.root / "other"))

    def test_import_paper_into_configured_collection(self):
        data, workspace = self.root / "data", self.root / "kb"
        data.mkdir()
        synthetic_catalog(data)
        init(workspace)
        env = {**self.env, "CAIRN_CATALOG_DIR": str(data), "CAIRN_WORKSPACE": str(workspace)}
        found = [json.loads(line) for line in run(env, "search", "synthetic").splitlines()]
        self.assertEqual([p["doi"] for p in found], ["10.0000/fixture"])
        saved = json.loads(run(env, "import-paper", "10.0000/fixture").splitlines()[-1])
        note = KB(workspace).resolve(saved["slug"])
        self.assertEqual((note.kind, note.meta["source"]), ("paper", "doi:10.0000/fixture"))
        self.assertIn("american-economic-review", [t.strip("[]") for t in note.topics])
        self.assertFalse((data / "journals.json").exists())  # the packaged registry served the read


if __name__ == "__main__":
    unittest.main()
