"""Retired worker entrypoint; do not execute untrusted packets natively."""

import sys

from cairn.adapters.legacy import retired
from cairn.errors import Blocked


def main() -> None:
    try:
        retired("Legacy worker execution")
    except Blocked as exc:
        sys.stderr.write(str(exc) + "\n")
        raise SystemExit(exc.exit_status) from None


if __name__ == "__main__":
    main()
