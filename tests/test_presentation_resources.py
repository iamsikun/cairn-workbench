import json
from pathlib import Path

from cairn.presentation.service import RESOURCE
from cairn.records.models import digest


def test_packaged_presentation_resource_integrity():
    value = json.loads((RESOURCE / "provenance.json").read_bytes())
    assert value["renderer"]["generated_sha256"] == digest(
        (RESOURCE / "application.mjs").read_bytes()
    )
    assert "quill" not in value  # Cairn no longer vendors writing skills.
    vendor = Path("vendor/answer-me-with-html")
    if vendor.exists():
        for path, checksum in value["renderer"]["source_files"].items():
            assert digest((vendor / path).read_bytes()) == checksum, path
