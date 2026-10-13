"""Keep every test away from the owner's configuration, catalog data and knowledge base."""

import os
import sys
import tempfile

_SANDBOX = tempfile.mkdtemp(prefix="cairn-catalog-tests-")
os.environ["CAIRN_WORKBENCH_CONFIG"] = os.path.join(_SANDBOX, "config.toml")
os.environ["CAIRN_CATALOG_DIR"] = os.path.join(_SANDBOX, "catalog")
os.environ["CAIRN_CATALOG_PREFERENCES"] = os.path.join(_SANDBOX, "preferences.yaml")
os.environ.pop("CAIRN_WORKSPACE", None)
sys.path.insert(0, os.path.dirname(__file__))  # shared fixtures
