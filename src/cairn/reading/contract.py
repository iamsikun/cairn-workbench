"""Cairn's reading contract: the only guidance a Finch packet carries.

How to read is the host agent's business (its own Finch, if installed). What Cairn
needs back, and what the agent may not do, lives here and is bound by hash.
"""

from pathlib import Path

from cairn.records.models import digest

CONTRACT = Path(__file__).with_name("contract.md")


def guidance() -> str:
    return CONTRACT.read_text()


def guidance_hash() -> str:
    return digest(guidance().encode())
