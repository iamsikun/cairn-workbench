"""New installations never run a startup updater. Legacy commands require selection."""

import sys

from pydantic import ValidationError

from cairn.errors import CairnError


def main() -> None:
    try:
        if len(sys.argv) > 1 and sys.argv[1] == "legacy":
            # Historical readers/owner workflows retain their original validation.
            sys.argv.pop(1)
            from cairn.cli import app as legacy

            legacy()
        else:
            from cairn.saving.cli import app

            app()
    except (CairnError, ValidationError, OSError) as exc:
        print(
            str(exc) if isinstance(exc, CairnError) else "invalid input or unavailable file",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
