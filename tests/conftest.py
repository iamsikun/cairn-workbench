from pathlib import Path

import pytest

from cairn.records.models import Record, now
from cairn.storage.workspace import Workspace


@pytest.fixture
def ws(tmp_path: Path) -> Workspace:
    code = tmp_path / "public-code"
    code.mkdir()
    return Workspace.init(tmp_path / "synthetic-private", code_roots=[code], synthetic=True)


@pytest.fixture
def record() -> Record:
    timestamp = now()
    return Record(
        id="concept_demo",
        type="concept",
        title="Synthetic concept",
        domain="research",
        created_at=timestamp,
        updated_at=timestamp,
    )


@pytest.fixture(autouse=True)
def synthetic_cairn_home(tmp_path_factory: pytest.TempPathFactory, monkeypatch) -> Path:
    # The updater lives under CAIRN_HOME; never the real home.
    directory = tmp_path_factory.mktemp("cairn-home")
    monkeypatch.setenv("CAIRN_HOME", str(directory))
    monkeypatch.setenv("CAIRN_NO_AUTO_UPDATE", "1")
    return directory

