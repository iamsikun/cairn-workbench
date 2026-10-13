"""Run the Node.js checks of the offline browser runtime."""

import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class BrowserScriptTests(unittest.TestCase):
    def test_bundle_parts(self):
        script = Path(__file__).with_name("test_bundle_parts.js")
        subprocess.run([shutil.which("node"), str(script)], check=True)
