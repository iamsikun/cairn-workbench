import json
from pathlib import Path

import pytest

from cairn.adapters.protocol import Job, Result
from cairn.policies.models import Policy
from cairn.records.models import Event, Extraction, Record


@pytest.mark.parametrize("model", [Record, Extraction, Event, Policy, Job, Result])
def test_export_matches_model(model: type[Record]) -> None:
    path = Path(__file__).parents[1] / "schemas" / f"{model.__name__.lower()}-v1.json"
    assert json.loads(path.read_text()) == model.model_json_schema()
