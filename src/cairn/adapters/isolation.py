"""Retired legacy worker interface. No native fallback or process launch."""

from cairn.adapters.legacy import retired


def invoke_worker(image: str, raw: bytes) -> bytes:
    retired("Legacy worker execution")
