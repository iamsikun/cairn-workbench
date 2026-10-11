"""Offline HTML pages generated from the Markdown notes, on request.

The Markdown is authoritative; pages are rebuilt from it every time and can be deleted.
Raw HTML in notes is escaped, so imported text cannot inject scripts.
"""

from __future__ import annotations

import html
import re
from pathlib import Path

from markdown_it import MarkdownIt

from cairn.store import KB, WIKILINK, Note, _write, slugify

STYLE = """
body{max-width:46rem;margin:2rem auto;padding:0 1rem;font:16px/1.6 system-ui,sans-serif;
color:#1d1d1f;background:#fff}
a{color:#0b5cad}h1{line-height:1.2}nav,.meta{color:#555;font-size:.9rem}
table{border-collapse:collapse}td,th{border:1px solid #ccc;padding:.3rem .5rem}
pre{overflow-x:auto;background:#f5f5f7;padding:.75rem}code{font-size:.9em}
ul.tree ul{margin:0}
@media (prefers-color-scheme:dark){body{color:#e8e8ea;background:#18181a}a{color:#7ab7ff}
pre{background:#26262a}nav,.meta{color:#aaa}}
@media print{nav{display:none}}
"""
MD = MarkdownIt("commonmark", {"html": False}).enable("table")


def _page(title: str, content: str) -> str:
    return (
        '<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; '
        "style-src 'unsafe-inline'; img-src data:\">"
        f"<title>{html.escape(title)}</title><style>{STYLE}</style></head>"
        f'<body><nav><a href="index.html">All topics</a></nav>{content}</body></html>\n'
    )


def _link(slug: str, notes: dict[str, Note]) -> str:
    note = notes.get(slug)
    if note is None:
        return html.escape(slug)
    return f'<a href="{html.escape(slug)}.html">{html.escape(note.title)}</a>'


def _body(note: Note, notes: dict[str, Note]) -> str:
    def replace(match: re.Match[str]) -> str:
        slug = slugify(match.group(1))
        label = (match.group(2) or (notes[slug].title if slug in notes else match.group(1))).strip()
        label = label.replace("[", "").replace("]", "")
        return f"[{label}]({slug}.html)" if slug in notes else label

    return MD.render(WIKILINK.sub(replace, note.body))


def note_page(note: Note, notes: dict[str, Note]) -> str:
    parts = [f"<h1>{html.escape(note.title)}</h1>"]
    meta = []
    if note.topics:
        meta.append("Topics: " + ", ".join(_link(s, notes) for s in note.topics))
    for key in ("authors", "year", "source", "url"):
        value = note.meta.get(key)
        if value:
            text = ", ".join(map(str, value)) if isinstance(value, list) else str(value)
            if key == "url" and text.startswith(("http://", "https://")):
                text = f'<a href="{html.escape(text)}">{html.escape(text)}</a>'
            else:
                text = html.escape(text)
            meta.append(f"{key.capitalize()}: {text}")
    if meta:
        parts.append('<p class="meta">' + "<br>".join(meta) + "</p>")
    parts.append(_body(note, notes))
    inside = [o for o in notes.values() if note.slug in o.topics]
    mentioned = [o for o in notes.values() if note.slug in o.body_links and o not in inside]
    for heading, group in (("In this topic", inside), ("Mentioned by", mentioned)):
        if group:
            items = "".join(
                f"<li>{_link(o.slug, notes)} <small>({o.kind})</small></li>"
                for o in sorted(group, key=lambda o: (o.kind, o.title.casefold()))
            )
            parts.append(f"<h2>{heading}</h2><ul>{items}</ul>")
    return _page(note.title, "".join(parts))


def index_page(kb: KB, notes: dict[str, Note]) -> str:
    children: dict[str, list[Note]] = {}
    for note in notes.values():
        for topic in note.topics:
            if topic in notes:
                children.setdefault(topic, []).append(note)

    def tree(note: Note, seen: frozenset[str]) -> str:
        kids = sorted(children.get(note.slug, []), key=lambda o: (o.kind != "topic", o.title))
        inner = "".join(tree(k, seen | {note.slug}) for k in kids if k.slug not in seen)
        return f"<li>{_link(note.slug, notes)}" + (f"<ul>{inner}</ul>" if inner else "") + "</li>"

    roots = [
        n
        for n in notes.values()
        if (n.kind == "topic" and not any(t in notes for t in n.topics))
        or (n.kind != "topic" and not n.topics)
    ]
    roots.sort(key=lambda n: (n.kind != "topic", n.title.casefold()))
    items = "".join(tree(n, frozenset()) for n in roots)
    title = f"Cairn — {kb.collection}"
    return _page(title, f'<h1>{html.escape(title)}</h1><ul class="tree">{items}</ul>')


def render(kb: KB) -> Path:
    """Rebuild every page of the collection; return the output directory."""
    out = kb.root / "html" / kb.collection
    notes = kb.notes()
    for note in notes.values():
        _write(out / f"{note.slug}.html", note_page(note, notes))
    _write(out / "index.html", index_page(kb, notes))
    for stale in out.glob("*.html"):
        if stale.stem != "index" and stale.stem not in notes:
            stale.unlink()
    return out
