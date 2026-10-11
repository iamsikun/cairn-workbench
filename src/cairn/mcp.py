"""Stdio MCP server: five tools over one collection of a knowledge base."""

from __future__ import annotations

import json
import sys
from typing import IO, Any

from cairn import __version__
from cairn.html import render
from cairn.store import KB, CairnError

INSTRUCTIONS = """\
Cairn is the user's persistent research knowledge base: Markdown notes for papers and \
topics, connected into a network. Save to it automatically; do not ask for permission.

While the user reads or discusses a paper (for example with the Finch skill):
1. Before writing, `search` for the paper and `list_topics` to see the existing network.
   If the paper already has a note, `get_note` it and extend that note.
2. After each substantive step (main idea, method, evidence, the user's own questions or \
judgements), call `save_reading` with the whole updated note. Keep the user's own \
observations, attributed as theirs. Do not wait for the end of the session.
3. Connect the paper: put it in 1-4 specific `topics`, reusing existing topics by their \
exact title or slug. A topic name that does not exist is created automatically.
4. Grow the hierarchy: when a topic is new, `save_note` it with kind=topic, a short \
explanation, and its broader `topics` (e.g. "Generative recommendation" -> \
"Recommendation systems"). A topic may have several broader topics.
5. Read `suggested_topics` and `created_topics` in every save result. Link genuinely \
related suggestions with another save; ignore weak ones. Use [[slug]] in a body to \
reference another note.

Updating an existing note requires its current `revision` from get_note; if a save is \
rejected, get_note again, merge, and retry. Report the saved slug when done. Only \
claim something is saved after a successful tool result.\
"""

TOPICS = {
    "type": "array",
    "items": {"type": "string"},
    "description": "Titles or slugs of topics; missing topics are created.",
}
COMMON = {
    "title": {"type": "string"},
    "body": {"type": "string", "description": "The whole note in Markdown."},
    "topics": TOPICS,
    "aliases": {"type": "array", "items": {"type": "string"}},
    "revision": {"type": "string", "description": "Required when updating an existing note."},
}
TOOLS: dict[str, dict[str, Any]] = {
    "search": {
        "description": "Search notes in this knowledge base by keywords.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "kind": {"type": "string", "enum": ["paper", "topic", "note"]},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50},
            },
            "required": ["query"],
        },
    },
    "get_note": {
        "description": "Read a note by slug, title or alias: body, revision, topics, links and "
        "backlinks. html=true also writes an offline HTML page and returns its path; use it "
        "only when the user asks for HTML.",
        "inputSchema": {
            "type": "object",
            "properties": {"name": {"type": "string"}, "html": {"type": "boolean"}},
            "required": ["name"],
        },
    },
    "list_topics": {
        "description": "List all topics with their broader/narrower topics and paper counts. "
        "empty=true marks topics that still need an explanation.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    "save_reading": {
        "description": "Create or update the note for a paper and link it to topics. One note "
        "per paper: the same DOI/arXiv id always maps to the same note.",
        "inputSchema": {
            "type": "object",
            "properties": {
                **COMMON,
                "source": {"type": "string", "description": "DOI, arXiv id, or URL."},
                "authors": {"type": "array", "items": {"type": "string"}},
                "year": {"type": "integer"},
                "url": {"type": "string"},
            },
            "required": ["title", "body", "topics"],
        },
    },
    "save_note": {
        "description": "Create or update a topic (kind=topic; `topics` are its broader topics) "
        "or a free-standing note (kind=note).",
        "inputSchema": {
            "type": "object",
            "properties": {**COMMON, "kind": {"type": "string", "enum": ["topic", "note"]}},
            "required": ["title", "body", "kind"],
        },
    },
}


def _strings(args: dict[str, Any], key: str) -> list[str] | None:
    value = args.get(key)
    if value is None:
        return None
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise CairnError(f"{key} must be a list of strings")
    return value


def _text(args: dict[str, Any], key: str) -> str:
    value = args.get(key)
    if not isinstance(value, str):
        raise CairnError(f"{key} is required and must be a string")
    return value


def call(kb: KB, name: str, args: dict[str, Any]) -> Any:
    if name == "search":
        limit = args.get("limit", 10)
        return kb.search(_text(args, "query"), int(limit), args.get("kind"))
    if name == "get_note":
        note = kb.get(_text(args, "name"))
        if args.get("html"):
            note["html"] = str(render(kb) / f"{note['slug']}.html")
        return note
    if name == "list_topics":
        return kb.list_topics()
    if name in ("save_reading", "save_note"):
        paper = name == "save_reading"
        fields = {k: args.get(k) for k in ("source", "authors", "year", "url")} if paper else {}
        return kb.save(
            kind="paper" if paper else _text(args, "kind"),
            title=_text(args, "title"),
            body=_text(args, "body"),
            topics=_strings(args, "topics"),
            aliases=_strings(args, "aliases"),
            revision=args.get("revision"),
            fields=fields,
        )
    raise CairnError(f"unknown tool {name!r}")


def handle(kb: KB, message: dict[str, Any]) -> dict[str, Any] | None:
    if "id" not in message:
        return None  # Notifications need no reply.
    method, params = message.get("method"), message.get("params") or {}
    if method == "initialize":
        result: Any = {
            "protocolVersion": params.get("protocolVersion", "2025-06-18"),
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "cairn", "version": __version__},
            "instructions": INSTRUCTIONS,
        }
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": [{"name": n, **spec} for n, spec in TOOLS.items()]}
    elif method == "tools/call":
        try:
            value = call(kb, str(params.get("name")), params.get("arguments") or {})
            text, error = json.dumps(value, ensure_ascii=False, indent=1), False
        except Exception as exc:  # Report to the agent; a broken note must not kill the server.
            text, error = str(exc) or type(exc).__name__, True
        result = {"content": [{"type": "text", "text": text}], "isError": error}
    else:
        return {
            "jsonrpc": "2.0",
            "id": message["id"],
            "error": {"code": -32601, "message": f"method not found: {method}"},
        }
    return {"jsonrpc": "2.0", "id": message["id"], "result": result}


def serve(kb: KB, stdin: IO[str] = sys.stdin, stdout: IO[str] = sys.stdout) -> None:
    for line in stdin:
        if not line.strip():
            continue
        try:
            message = json.loads(line)
            response = handle(kb, message) if isinstance(message, dict) else None
        except json.JSONDecodeError:
            response = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": "parse error"},
            }
        if response is not None:
            stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            stdout.flush()
