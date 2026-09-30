"""Synthetic >256MiB corpus trial; run only in the documented development container."""

import tempfile
from pathlib import Path

from cairn.records.models import canonical, digest
from cairn.storage.streaming_backup import backup, restore
from cairn.storage.workspace import Workspace


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="cairn-large-library-") as temporary:
        root = Path(temporary)
        code = root / "public-code"
        code.mkdir()
        ws = Workspace.init(root / "synthetic-owner", code_roots=[code], synthetic=True)
        for index in range(65):
            data = bytes([index]) * (4 * 1024 * 1024)
            ws.fs.write(f"blobs/{digest(data)}", data)
        report = backup(ws, root / "library.zip")
        recovered = restore(
            root / "library.zip",
            root / "restored",
            code_roots=[code],
            synthetic=True,
            expected_sha256=str(report["sha256"]),
        )
        assert recovered.config.id == ws.config.id
        assert recovered.fs.files("blobs") == ws.fs.files("blobs")
        assert int(report["payload_bytes"]) > 256 * 1024 * 1024
        print(
            canonical(
                {
                    **report,
                    "restored_blobs": 65,
                    "synthetic_only": True,
                    "semantic_quality": "not_tested",
                }
            ).decode()
        )


if __name__ == "__main__":
    main()
