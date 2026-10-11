"""Record checked-in renderer provenance after the reproducible native source build."""

import json
from hashlib import sha256
from pathlib import Path

root = Path(__file__).resolve().parents[1]
resources = root / "src/cairn/presentation/resources"
vendor = root / "vendor/answer-me-with-html"


def hashes(directory: Path) -> dict[str, str]:
    return {
        p.relative_to(directory).as_posix(): sha256(p.read_bytes()).hexdigest()
        for p in sorted(directory.rglob("*"))
        if p.is_file() and not {"node_modules", "__pycache__", "dist", ".git"}.intersection(p.parts)
    }


value = {
    "schema_version": 1,
    "renderer": {
        "upstream_repository": "https://github.com/QingYunA/answer-me-with-html",
        "upstream_version": "0.5.0",
        "upstream_commit": "19b2b5b07676d3e65c83ca9a7b6621f300b54c92",
        "maintained_base_commit": "de54bc1fe9653a5c505bb90e8d30b62b4343b9f0",
        "maintained_commit": "0a13bfcaaa5081b87e6cd191537426261da8c1df",
        "profile": "application-v1",
        "license": "MIT",
        "source_files": hashes(vendor),
        "generated_sha256": sha256((resources / "application.mjs").read_bytes()).hexdigest(),
        "build": "node scripts/build-application.mjs OUTPUT (in vendor directory)",
    },
    "build_runtime": "Node 24; locked npm dependencies; native build",
}
(resources / "provenance.json").write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
(resources / "THIRD_PARTY_LICENSES").write_bytes(
    (vendor / "LICENSE").read_bytes()
    + b"\n\nMarked\n======\n"
    + (vendor / "LICENSE.marked").read_bytes()
)
