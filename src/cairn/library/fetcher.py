"""Retired legacy public-fetch worker; metadata remains readable."""

from cairn.adapters.legacy import retired
from cairn.storage.workspace import Workspace


def fetch_isolated(ws: Workspace, url: str, hosts: set[str]) -> bytes:
    retired("Legacy public-fetch worker")


if __name__ == "__main__":
    retired("Legacy public-fetch worker")
