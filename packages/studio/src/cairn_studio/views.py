"""The Studio's views of one collection, computed from its notes on every request.

Every answer is plain JSON. Shapes follow the MCP tools where one exists (`search`,
`get_note`, `list_topics`), so later clients can share them. Nothing here writes.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Iterable
from datetime import date
from typing import Any

from markdown_it import MarkdownIt

from cairn.store import (
    FOLDERS,
    KB,
    STATUSES,
    WIKILINK,
    Note,
    normalize_source,
    slugify,
    split_minutes,
)

MD = MarkdownIt("commonmark", {"html": False}).enable(["table", "strikethrough"])
FIELDS = ("authors", "year", "venue", "source", "url", "doi")
IDEA_FIELDS = ("status", "next_action", "last_discussed", "last_review")
STALE_DAYS = 30
MARKUP = re.compile(r"#{1,6} |\*\*|__|`|\[\[|\]\]|^> ", re.M)
DAY_HEADING = re.compile(r"^### (\d{4}-\d{2}-\d{2})(.*)$", re.M)
STATUS_LINE = re.compile(r"^Status: (\w+) → (\w+)\.?\s*(.*)$", re.S)
SPEAKER = re.compile(r"^(?:[-*]\s+)?\*\*(User|Agent[^*:]*|Source)(?::\*\*|\*\*:)\s*", re.IGNORECASE)


def signature(kb: KB) -> str:
    """Changes whenever a note in the collection is added, removed or edited."""
    digest = hashlib.sha256()
    for folder in FOLDERS.values():
        for path in sorted((kb.dir / folder).glob("*.md")):
            stat = path.stat()
            digest.update(f"{path.name}:{stat.st_mtime_ns}:{stat.st_size};".encode())
    return digest.hexdigest()[:16]


def render(markdown: str, notes: dict[str, Note]) -> str:
    """Markdown to HTML with raw HTML escaped; [[slug]] becomes a link inside the app."""

    def replace(match: re.Match[str]) -> str:
        slug = slugify(match.group(1))
        label = match.group(2) or (notes[slug].title if slug in notes else match.group(1))
        label = label.strip().replace("[", "").replace("]", "")
        return f"[{label}](#/note/{slug})" if slug in notes else f"*{label}*"

    return MD.render(WIKILINK.sub(replace, markdown))


def _days_since(value: Any, today: date) -> int | None:
    try:
        return (today - date.fromisoformat(str(value))).days
    except ValueError:
        return None


def _refs(slugs: list[str], notes: dict[str, Note]) -> list[dict[str, str]]:
    return [{"slug": s, "title": notes[s].title} for s in slugs if s in notes]


def _summary(note: Note, notes: dict[str, Note]) -> dict[str, Any]:
    item = {
        "slug": note.slug,
        "title": note.title,
        "kind": note.kind,
        "topics": _refs(note.topics, notes),
        "updated": str(note.meta.get("updated") or note.meta.get("created") or ""),
    }
    if note.kind == "idea":
        item.update({k: str(note.meta[k]) for k in IDEA_FIELDS if note.meta.get(k)})
        item.setdefault("status", "seed")
    return item


def graph(kb: KB) -> dict[str, Any]:
    """Nodes for every note; edges for topic filing and [[links]] between existing notes."""
    notes = kb.notes()
    edges, seen = [], set()
    for note in notes.values():
        for kind, targets in (("topic", note.topics), ("link", note.body_links)):
            for target in targets:
                key = (note.slug, target)
                if target in notes and target != note.slug and key not in seen:
                    seen.add(key)
                    edges.append({"source": note.slug, "target": target, "kind": kind})
    degree: dict[str, int] = {}
    for edge in edges:
        for end in (edge["source"], edge["target"]):
            degree[end] = degree.get(end, 0) + 1
    nodes = [
        {**_summary(n, notes), "topics": n.topics, "degree": degree.get(n.slug, 0)}
        for n in notes.values()
    ]
    return {"collection": kb.collection, "nodes": nodes, "edges": edges}


def recent(kb: KB, limit: int = 40) -> dict[str, Any]:
    notes = kb.notes()
    counts: dict[str, int] = {}
    for item in notes.values():
        counts[item.kind] = counts.get(item.kind, 0) + 1
    # Dates are days, so the file's modification time orders notes saved on the same day.
    latest = sorted(
        (n for n in notes.values() if n.kind != "topic"),
        key=lambda n: (str(n.meta.get("updated") or ""), n.path.stat().st_mtime_ns),
        reverse=True,
    )
    return {
        "collection": kb.collection,
        "counts": counts,
        "notes": [_summary(n, notes) for n in latest[:limit]],
    }


def ideas(kb: KB, today: date | None = None) -> dict[str, Any]:
    """The idea board: one column per status, most recently discussed first."""
    today = today or date.today()
    columns: dict[str, list[dict[str, Any]]] = {s: [] for s in STATUSES}
    notes = kb.notes()
    for note in notes.values():
        if note.kind != "idea":
            continue
        card = _summary(note, notes)
        discussed = card.get("last_discussed") or card["updated"]
        card["days_since"] = _days_since(discussed, today) if discussed else None
        card["stale"] = (
            card["status"] in ("seed", "exploring", "testing")
            and (card["days_since"] or 0) > STALE_DAYS
        )
        columns.setdefault(card["status"], []).append(card)
    for cards in columns.values():
        cards.sort(key=lambda c: c.get("last_discussed") or c["updated"], reverse=True)
    return {
        "collection": kb.collection,
        "columns": [{"status": s, "ideas": c} for s, c in columns.items()],
    }


def minutes(text: str, notes: dict[str, Note]) -> list[dict[str, Any]]:
    """An idea's minutes as dated entries, each split into attributed items.

    An item starts at a paragraph or at a line opening with **User:**, **Agent ...:** or
    **Source:**. A status change (`Status: a → b.`) is its own item.
    """
    days = []
    heads = list(DAY_HEADING.finditer(text))
    for i, head in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        label = head.group(2).strip()
        items = []
        for block in re.split(r"\n\s*\n", text[head.end() : end].strip()):
            for chunk in _speakers(block.strip()):
                change = STATUS_LINE.match(chunk)
                if change:
                    items.append({"who": "status", "from": change[1], "to": change[2]})
                    chunk = change[3].strip()
                    if not chunk:
                        continue
                match = SPEAKER.match(chunk)
                who = match.group(1).lower().split()[0] if match else "note"
                body = chunk[match.end() :] if match else chunk
                items.append(
                    {
                        "who": who,
                        "label": match.group(1) if match else "",
                        "html": render(body, notes),
                    }
                )
        days.append({"date": head.group(1), "label": label.strip("() "), "items": items})
    return days


def _speakers(block: str) -> list[str]:
    chunks: list[list[str]] = []
    for line in block.splitlines():
        if not chunks or SPEAKER.match(line) or STATUS_LINE.match(line):
            chunks.append([line])
        else:
            chunks[-1].append(line)
    return ["\n".join(c).strip() for c in chunks if "".join(c).strip()]


def note(kb: KB, name: str) -> dict[str, Any]:
    """`get_note` plus rendered HTML, topic trails, parsed minutes and related papers."""
    notes = kb.notes()
    found = kb.get(name)
    current = notes[found["slug"]]
    account, minute_text = (
        split_minutes(current.body) if current.kind == "idea" else (current.body, "")
    )
    result: dict[str, Any] = {
        key: found[key]
        for key in ("slug", "title", "kind", "revision", "topics", "links", "backlinks")
    }
    result["fields"] = {
        k: current.meta[k]
        for k in (*FIELDS, *IDEA_FIELDS, "created", "updated")
        if current.meta.get(k) not in (None, "", [])
    }
    result["aliases"] = current.aliases
    result["html"] = render(account, notes)
    result["trails"] = trails(current.slug, notes)
    if current.kind == "idea":
        result["fields"].setdefault("status", "seed")
        result["minutes"] = minutes(minute_text, notes)
    if current.kind == "topic":
        inside = [o for o in notes.values() if current.slug in o.topics]
        result["narrower"] = [_summary(o, notes) for o in inside if o.kind == "topic"]
        result["members"] = [_summary(o, notes) for o in inside if o.kind != "topic"]
    else:
        result["related"] = related(current, notes)
    return result


def trails(slug: str, notes: dict[str, Note], limit: int = 6) -> list[list[dict[str, str]]]:
    """Paths from the note's topics up to the roots of the topic hierarchy."""
    found: list[list[str]] = []

    def climb(path: list[str]) -> None:
        if len(found) >= limit:
            return
        ups = [t for t in notes[path[0]].topics if t in notes and t not in path]
        if not ups:
            found.append(path)
        for up in ups:
            climb([up, *path])

    for topic in notes[slug].topics:
        if topic in notes:
            climb([topic])
    return [[{"slug": s, "title": notes[s].title} for s in path] for path in found]


def related(current: Note, notes: dict[str, Note], limit: int = 8) -> list[dict[str, Any]]:
    """Other papers and ideas ranked by how many of this note's topics they share."""
    mine = set(current.topics)
    scored = []
    for other in notes.values():
        if other.slug == current.slug or other.kind in ("topic", "note"):
            continue
        shared = mine & set(other.topics)
        if shared:
            scored.append((len(shared), other))
    scored.sort(key=lambda s: (-s[0], s[1].title.casefold()))
    return [{**_summary(o, notes), "shared": n} for n, o in scored[:limit]]


def search(kb: KB, query: str, kind: str | None = None, limit: int = 30) -> dict[str, Any]:
    notes = kb.notes()
    results = kb.search(query, limit=limit, kind=kind or None)
    for result in results:
        result["topics"] = _refs(result["topics"], notes)
        result["snippet"] = " ".join(MARKUP.sub("", result["snippet"]).split())
        result["updated"] = str(notes[result["slug"]].meta.get("updated") or "")
    return {"collection": kb.collection, "query": query, "results": results}


def in_catalog(kb: KB, lookup: Callable[[Iterable[str]], dict[str, str]]) -> dict[str, Any]:
    """Catalog papers that have a paper note here, matched by DOI, arXiv id or web address.

    `lookup` maps paper identities (a note's `source` and `url`) to catalog paper ids; it is the
    catalog's.
    """
    notes: dict[str, Note] = {}
    for note in kb.notes().values():
        if note.kind != "paper":
            continue
        for key in ("source", "url"):
            if note.meta.get(key):
                notes.setdefault(normalize_source(str(note.meta[key])), note)
    found = lookup(list(notes)) if notes else {}
    return {
        "papers": {
            paper: {"slug": notes[source].slug, "title": notes[source].title}
            for paper, source in found.items()
        }
    }
