"""Record the licensed upstream Finch snapshot and installer; run in the dev container."""

import json
from pathlib import Path

from cairn.records.models import digest

resources = Path("src/cairn/reading/resources")
root = resources / "finch"
installer = resources / "finch-installer"
names = [
    "LICENSE",
    "SKILL.md",
    "scripts/extract_pdf.py",
    *(
        f"references/{name}.md"
        for name in ("computational", "empirical", "formal", "literature", "cairn")
    ),
]
(root / "provenance.json").write_text(
    json.dumps(
        {
            "schema_version": 1,
            "skill": "finch",
            "version": "0.3.0",
            "license": "MIT",
            "author": "Sikun Xu",
            "origin": "iamsikun/finch commit 4de3695e18b854809d280d90b3c027bf18330c21 "
            "(branch cairn-handoff; not yet released to stable)",
            "cairn_changes": [],
            "files": {name: digest((root / name).read_bytes()) for name in names},
            "installer": {
                name: digest((installer / name).read_bytes()) for name in ("LICENSE", "install.sh")
            },
        },
        indent=2,
        sort_keys=True,
    )
    + "\n"
)
