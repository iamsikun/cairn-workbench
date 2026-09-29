"""Strict JSON data loading, without duplicate-field or non-finite-number ambiguity."""

from __future__ import annotations

import json
from typing import Any

from cairn.errors import CairnError


def read_json(data: bytes) -> Any:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise CairnError("duplicate JSON field")
            result[key] = value
        return result

    def reject(value: str) -> None:
        raise CairnError("non-finite JSON number")

    try:
        return json.loads(data, object_pairs_hook=pairs, parse_constant=reject)
    except (ValueError, RecursionError) as exc:
        raise CairnError("invalid JSON document") from exc
