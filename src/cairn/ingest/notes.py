"""Owner notes: written by the owner, searchable as-is, never a model or apply target.

Notes in `vault/notes` and `vault/inbox` are human-authored. They stay protected inputs;
reading them for the owner's local search needs no capture, proposal or approval. They
are not source evidence and are never placed in model packets or exported views.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import get_args

import yaml

from cairn.errors import CairnError, Denied
from cairn.records.models import Classification, Domain, Labels, digest, now
from cairn.storage.markdown import UniqueSafeLoader
from cairn.storage.workspace import Workspace

PREFIXES = ("vault/notes", "vault/inbox")
MAX_NOTE_BYTES = 1024 * 1024


@dataclass(frozen=True)
class Note:
    path: str
    title: str
    body: str
    labels: Labels
    sha256: str


def _front_matter(text: str) -> tuple[dict[str, object], str]:
    if not text.startswith("---\n") or "\n---\n" not in text[4:]:
        return {}, text
    header, body = text[4:].split("\n---\n", 1)
    try:
        if any(
            isinstance(token, (yaml.AliasToken, yaml.AnchorToken)) for token in yaml.scan(header)
        ):
            return {}, body
        value = yaml.load(header, Loader=UniqueSafeLoader)
    except (CairnError, yaml.YAMLError):
        return {}, body
    return (value if isinstance(value, dict) else {}), body


def labels_for(path: str, meta: dict[str, object]) -> Labels:
    """Front matter wins; otherwise the folder domain; otherwise owner-only."""
    folder = path.split("/")[2] if path.count("/") >= 3 else None
    default = (
        Labels(domain=folder, classification="private")  # type: ignore[arg-type]
        if folder in get_args(Domain)
        else Labels(domain="shared", classification="restricted")
    )
    keys = ("domain", "classification", "processing", "compartments")
    try:
        return Labels.model_validate(default.model_dump() | {k: meta[k] for k in keys if k in meta})
    except ValueError:
        # Unclear labels fail closed rather than widening visibility.
        return Labels(domain="shared", classification="restricted")


def read_notes(ws: Workspace) -> list[Note]:
    notes = []
    for prefix in PREFIXES:
        for path in ws.fs.files(prefix):
            if not path.endswith(".md"):
                continue
            try:
                raw = ws.fs.read(path, limit=MAX_NOTE_BYTES)
            except Denied:
                continue  # Oversized or non-regular files are not indexed.
            meta, body = _front_matter(raw.decode("utf-8", errors="replace"))
            heading = re.search(r"^#\s+(.+)$", body, re.MULTILINE)
            title = meta.get("title")
            notes.append(
                Note(
                    path=path,
                    title=str(title)[:500]
                    if title
                    else heading.group(1).strip()[:500]
                    if heading
                    else path.rsplit("/", 1)[-1].removesuffix(".md"),
                    body=body,
                    labels=labels_for(path, meta),
                    sha256=digest(raw),
                )
            )
    return notes


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.casefold()).strip("-")[:48] or "note"


def write_note(
    ws: Workspace,
    text: str,
    *,
    title: str | None = None,
    domain: Domain = "shared",
    classification: Classification = "private",
    at: datetime | None = None,
) -> Note:
    """Owner quick capture into the inbox. Creates a new file; never edits a note."""
    body = text.strip()
    if not body:
        raise CairnError("note text is required")
    timestamp = at or now()
    labels = Labels(domain=domain, classification=classification)
    meta: dict[str, object] = {
        "title": title or body.splitlines()[0][:120],
        "created": timestamp.isoformat(),
        **labels.model_dump(mode="json", exclude={"compartments"}),
    }
    header = yaml.safe_dump(meta, sort_keys=True, allow_unicode=True)
    raw = f"---\n{header}---\n{body}\n".encode()
    if len(raw) > MAX_NOTE_BYTES:
        raise CairnError("note exceeds size limit")
    name = f"{timestamp:%Y-%m-%d}-{_slug(str(meta['title']))}-{digest(raw)[:8]}.md"
    path = f"vault/inbox/{name}"
    with ws.lock(write=True):
        ws.fs.write(path, raw, exclusive=True)
    return Note(
        path=path,
        title=str(meta["title"]),
        body=body + "\n",
        labels=labels,
        sha256=digest(raw),
    )
