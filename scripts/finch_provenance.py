"""Record the licensed, owner-supplied Finch snapshot; run in the dev container."""

import json
from pathlib import Path

from cairn.records.models import digest

root = Path("src/cairn/reading/resources/finch")
names = [
    "LICENSE",
    "SKILL.md",
    "scripts/extract_pdf.py",
    *(
        f"references/{name}.md"
        for name in ("computational", "empirical", "formal", "literature", "cairn-workflow")
    ),
]
(root / "provenance.json").write_text(
    json.dumps(
        {
            "schema_version": 1,
            "skill": "finch",
            "version": "0.2.0",
            "license": "MIT",
            "author": "Sikun Xu",
            "origin": "Owner-selected Finch 0.2.0 skill snapshot; no upstream commit asserted",
            "cairn_changes": ["references/cairn-workflow.md"],
            "files": {name: digest((root / name).read_bytes()) for name in names},
        },
        indent=2,
        sort_keys=True,
    )
    + "\n"
)
