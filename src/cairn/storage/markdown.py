from __future__ import annotations

import json
from typing import Any

import yaml

from cairn.errors import CairnError
from cairn.records.models import Record, canonical


class UniqueSafeLoader(yaml.SafeLoader):
    pass


def unique_mapping(loader: UniqueSafeLoader, node: yaml.MappingNode) -> dict[str, Any]:
    mapping: dict[str, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node)
        if not isinstance(key, str) or key in mapping:
            raise CairnError("front matter keys must be unique strings")
        mapping[key] = loader.construct_object(value_node)
    return mapping


UniqueSafeLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, unique_mapping)


def decode(data: bytes) -> tuple[Record, str]:
    try:
        text = data.decode("utf-8")
        if not text.startswith("---\n"):
            raise CairnError("record requires YAML front matter")
        header, body = text[4:].split("\n---\n", 1)
        if len(header) > 128 * 1024:
            raise CairnError("front matter exceeds limit")
        # Aliases add unnecessary complexity and can hide amplification or cycles.
        if any(
            isinstance(token, (yaml.AliasToken, yaml.AnchorToken)) for token in yaml.scan(header)
        ):
            raise CairnError("YAML aliases and anchors are not supported")
        return Record.model_validate(yaml.load(header, Loader=UniqueSafeLoader)), body
    except (UnicodeError, ValueError, yaml.YAMLError) as exc:
        raise CairnError("invalid Markdown record") from exc


def encode(record: Record, body: str) -> bytes:
    header = yaml.safe_dump(json.loads(canonical(record)), sort_keys=True, allow_unicode=True)
    return f"---\n{header}---\n{body}".encode()
