"""Reject executable/external history configuration before any Git invocation."""

from __future__ import annotations

import configparser

from cairn.errors import Denied


def check_history_config(data: bytes) -> None:
    parser = configparser.ConfigParser(interpolation=None, strict=True)
    try:
        parser.read_string(data.decode("utf-8"))
    except (ValueError, configparser.Error) as exc:
        raise Denied("unsupported local history configuration") from exc
    required = {"repositoryformatversion": "0", "filemode": "true", "bare": "true"}
    # Git writes these on case-insensitive or Unicode-normalizing filesystems such as
    # default macOS APFS. They change path matching only, never execution.
    optional = {"ignorecase": "true", "precomposeunicode": "true"}
    if parser.defaults() or parser.sections() != ["core"]:
        raise Denied("history configuration must use Cairn's local bare repository profile")
    core = dict(parser["core"])
    if any(core.get(key) != value for key, value in required.items()) or any(
        optional.get(key) != value for key, value in core.items() if key not in required
    ):
        raise Denied("history configuration must use Cairn's local bare repository profile")


def check_history_paths(paths: list[str]) -> None:
    forbidden = {
        "history.git/commondir",
        "history.git/gitdir",
        "history.git/info/grafts",
        "history.git/objects/info/alternates",
        "history.git/objects/info/http-alternates",
    }
    if any(path in forbidden or path.startswith("history.git/worktrees/") for path in paths):
        raise Denied("external history repository references are unsupported")
