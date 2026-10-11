from pathlib import Path

import pytest

from cairn.storage.workspace import parse_config


@pytest.mark.parametrize("version", [1, 2, 3])
def test_legacy_config_reader_does_not_rewrite(version: int) -> None:
    path = Path(__file__).parents[1] / "examples" / "legacy" / f"workspace-v{version}.json"
    original = path.read_bytes()
    config = parse_config(original)
    assert config.schema_version == version
    assert config.synthetic
    assert path.read_bytes() == original
