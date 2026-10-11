"""Six scoped operations for an existing agent. No agent or scheduler is launched."""

import json
import sys
from importlib.resources import files
from typing import IO, Any, Literal

from pydantic import Field, ValidationError

from cairn import __version__
from cairn.errors import CairnError
from cairn.records.models import ID, Domain, Model
from cairn.saving.models import Capture, SaveNote, SaveReading
from cairn.saving.retrieval import get_note, list_topics, search
from cairn.saving.service import save
from cairn.saving.workspace import Book


class Search(Model):
    query: str = Field(max_length=2000)
    limit: int = Field(default=20, ge=1, le=100)


class GetNote(Model):
    id: ID
    format: Literal["markdown", "html"] = "markdown"


class Empty(Model):
    pass


TOOLS: dict[str, tuple[type[Model], str, bool]] = {
    "capture": (
        Capture,
        "Retain a URL/DOI reference, supplied text or base64 PDF. "
        "Missing extraction never blocks reference capture. Use an operation key for retries.",
        False,
    ),
    "search": (
        Search,
        "Search the selected collection's current notes, sources and attributed observations. "
        "Returns saved revision hashes and unfinished enrichment.",
        True,
    ),
    "get_note": (
        GetNote,
        "Read Markdown, revisions, source coverage, observations and explained backlinks. "
        "Request format=html only when the user asks for HTML; "
        "this creates or refreshes an offline companion.",
        False,
    ),
    "list_topics": (
        Empty,
        "List learning notebooks and research questions in this collection "
        "with current revisions and pending work.",
        True,
    ),
    "save_reading": (
        SaveReading,
        "Directly save a reading checkpoint and ready topic changes together. Retrieve current "
        "notes first; include expected_revision for every existing target and a stable "
        "operation_key. Preserve user observations, distinguish source claims from inference, "
        "and report returned saved IDs. Finch supplies reading method; Quill supplies substantial "
        "learning prose. Keep unfinished work in enrichment/unresolved. "
        "HTML is separate and optional.",
        False,
    ),
    "save_note": (
        SaveNote,
        "Directly save a notebook, research question or note. Retrieve it first and supply "
        "expected_revision plus operation_key. Original observations are appended by stable ID; "
        "rejected relationships remain remembered. Saving does not verify claims or adopt "
        "decisions. Report confirmed IDs and revisions; retry an interrupted request unchanged.",
        False,
    ),
}


def instructions() -> str:
    return files("cairn.saving").joinpath("agent.md").read_text()


def call(book: Book, collection: Domain, name: str, arguments: Any) -> dict[str, Any]:
    try:
        if name not in TOOLS:
            raise CairnError("unknown operation")
        args = TOOLS[name][0].model_validate(arguments or {})
        if isinstance(args, (Capture, SaveNote)):
            value: Any = save(book, collection, args)
        elif isinstance(args, Search):
            value = search(book, collection, args.query, args.limit)
        elif isinstance(args, GetNote):
            value = get_note(book, collection, args.id)
            if args.format == "html":
                from cairn.saving.views import render

                value["html"] = render(book, collection, args.id)
        else:
            value = list_topics(book, collection)
        return {
            "content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False)}],
            "isError": False,
        }
    except ValidationError:
        return failure("invalid request; use the tool schema")
    except (CairnError, OSError, ValueError) as exc:
        # OSError paths and parser inputs can disclose unrelated filesystem data.
        return failure(
            str(exc) if isinstance(exc, CairnError) else "operation failed; content preserved"
        )


def failure(message: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": message}], "isError": True}


def handle(book: Book, collection: Domain, message: Any) -> dict[str, Any] | None:
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
        return {
            "jsonrpc": "2.0",
            "id": None,
            "error": {"code": -32600, "message": "invalid request"},
        }
    if "id" not in message:
        return None
    result: dict[str, Any]
    method = message.get("method")
    params = message.get("params") or {}
    if not isinstance(params, dict):
        return {
            "jsonrpc": "2.0",
            "id": message["id"],
            "error": {"code": -32602, "message": "invalid params"},
        }
    if method == "initialize":
        result = {
            "protocolVersion": "2025-06-18",
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "cairn", "version": __version__},
            "instructions": instructions(),
        }
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {
            "tools": [
                {
                    "name": name,
                    "description": text,
                    "inputSchema": model.model_json_schema(),
                    "annotations": {"readOnlyHint": readonly, "openWorldHint": False},
                }
                for name, (model, text, readonly) in TOOLS.items()
            ]
        }
    elif method == "tools/call":
        result = call(book, collection, str(params.get("name")), params.get("arguments"))
    else:
        return {
            "jsonrpc": "2.0",
            "id": message["id"],
            "error": {"code": -32601, "message": "method not found"},
        }
    return {"jsonrpc": "2.0", "id": message["id"], "result": result}


def serve(book: Book, collection: Domain, stdin: IO[bytes], stdout: IO[bytes]) -> None:
    book.collection(collection)
    with book.lock():
        pass
    while line := stdin.readline(24 * 1024 * 1024 + 1):
        if len(line) > 24 * 1024 * 1024:
            raise CairnError("MCP request exceeds input budget")
        try:
            response = handle(book, collection, json.loads(line))
        except ValueError:
            response = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": "parse error"},
            }
        if response is not None:
            stdout.write(json.dumps(response, ensure_ascii=False).encode() + b"\n")
            stdout.flush()


def main(book: Book, collection: Domain) -> None:
    serve(book, collection, sys.stdin.buffer, sys.stdout.buffer)
