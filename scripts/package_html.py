"""Create a deterministic portable skill ZIP; run in the native synthetic environment."""

import argparse
import json
import zipfile
from hashlib import sha256
from pathlib import Path


def package(output: Path) -> str:
    root = Path(__file__).resolve().parents[1]
    resources = root / "src/cairn/presentation/resources"
    files = {
        str(p.relative_to(root / "skills/cairn-html")): p.read_bytes()
        for p in sorted((root / "skills/cairn-html").rglob("*"))
        if p.is_file()
    }
    files["runtime/application.mjs"] = (resources / "application.mjs").read_bytes()
    files["runtime/LICENSE"] = (root / "vendor/answer-me-with-html/LICENSE").read_bytes()
    files["runtime/THIRD_PARTY_LICENSES"] = (resources / "THIRD_PARTY_LICENSES").read_bytes()
    files["PROVENANCE.json"] = (resources / "provenance.json").read_bytes()
    files["SHA256SUMS.json"] = (
        json.dumps(
            {p: sha256(raw).hexdigest() for p, raw in sorted(files.items())},
            sort_keys=True,
            indent=2,
        )
        + "\n"
    ).encode()
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path, raw in sorted(files.items()):
            info = zipfile.ZipInfo("cairn-html/" + path, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, raw)
    return sha256(output.read_bytes()).hexdigest()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("dist/cairn-html.zip"))
    args = parser.parse_args()
    print(package(args.output))
