from pathlib import Path
from typing import Annotated

import typer

from cairn.cli.commands import JsonOption, emit, guarded
from cairn.storage.release import load_release, verify_bundle, verify_runtime


def register(app: typer.Typer) -> None:
    release = typer.Typer(help="Verify an independently reviewed offline release.")
    app.add_typer(release, name="release")

    @release.command("check-bundle")
    @guarded
    def bundle(
        directory: Path,
        sha256: Annotated[str, typer.Option()],
        json_output: JsonOption = False,
    ) -> None:
        manifest = verify_bundle(directory, expected_sha256=sha256)
        emit(
            {
                "bundle_verified": True,
                "code_revision": manifest.code_revision,
                "platform": manifest.platform,
                "wheels": len(manifest.artifacts),
            },
            json_output,
        )

    @release.command("check-runtime")
    @guarded
    def runtime(
        manifest: Path,
        sha256: Annotated[str, typer.Option()],
        json_output: JsonOption = False,
    ) -> None:
        emit(verify_runtime(load_release(manifest, expected_sha256=sha256)), json_output)

    @release.command("check-worker")
    @guarded
    def worker(image: str, json_output: JsonOption = False) -> None:
        """Retired: native Cairn has no worker activation or probes."""
        from cairn.storage.activation import check_worker

        emit(check_worker(image), json_output)
