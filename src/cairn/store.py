"""A Markdown knowledge base: one file per note, connected by [[wikilinks]].

Layout of a knowledge base::

    <root>/.cairn                     marker written by `cairn init`
    <root>/<collection>/papers/*.md   one evolving note per paper
    <root>/<collection>/topics/*.md   topic notebooks; `topics:` lists broader topics
    <root>/<collection>/ideation/*.md research ideas: an account plus dated minutes
    <root>/<collection>/notes/*.md    anything else

A note's file name (its slug) is its identity and is unique within a collection.
Links live in the `topics:` front matter (paper -> topic, topic -> broader topic) and as
[[slug]] links in the body. Backlinks and topic trees are computed when read.
"""

from __future__ import annotations

import fcntl
import hashlib
import os
import re
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import yaml

COLLECTIONS = ("research", "finance", "life")
FOLDERS = {"paper": "papers", "topic": "topics", "idea": "ideation", "note": "notes"}
MARKER = ".cairn"
MANAGED = {"title", "kind", "topics", "aliases", "created", "updated"}
STATUSES = ("seed", "exploring", "testing", "parked", "developed")
MINUTES = re.compile(r"^## Minutes[ \t]*$", re.M)
WIKILINK = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|([^\]]*))?\]\]")
STOPWORDS = set(
    "a an and are as at be by for from in into is of on or the to via with "
    "model models method methods paper study learning based using towards".split()
)


class CairnError(Exception):
    """A problem the caller can fix; the message is safe to show to the agent."""


def slugify(title: str) -> str:
    slug = re.sub(r"[^\w]+", "-", title.casefold()).strip("-_")
    return slug[:80].rstrip("-") or "untitled"


def normalize_source(value: str) -> str:
    """Canonical paper identity, so the same DOI/arXiv paper maps to one note."""
    value = value.strip()
    low = value.lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/", "doi:"):
        if low.startswith(prefix):
            return "doi:" + low[len(prefix) :]
    if low.startswith("10.") and "/" in low:
        return "doi:" + low
    match = re.match(r"(?:arxiv:|https?://(?:www\.)?arxiv\.org/(?:abs|pdf)/)(\d{4}\.\d{4,5})", low)
    if match:
        return "arxiv:" + match.group(1)
    return value


def revision(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()[:16]


def _unlink(value: str) -> str:
    match = WIKILINK.fullmatch(value.strip())
    return slugify(match.group(1) if match else value)


@dataclass
class Note:
    slug: str
    path: Path
    meta: dict[str, Any]
    body: str
    revision: str

    @property
    def title(self) -> str:
        return str(self.meta.get("title") or self.slug)

    @property
    def kind(self) -> str:
        return str(self.meta.get("kind") or "note")

    @property
    def topics(self) -> list[str]:
        return [_unlink(str(t)) for t in self.meta.get("topics") or []]

    @property
    def aliases(self) -> list[str]:
        return [str(a) for a in self.meta.get("aliases") or []]

    @property
    def body_links(self) -> list[str]:
        return list(dict.fromkeys(slugify(m.group(1)) for m in WIKILINK.finditer(self.body)))

    def text(self) -> str:
        return "\n".join([self.title, *self.aliases, self.body]).casefold()


def parse(path: Path) -> Note:
    raw = path.read_bytes()
    text = raw.decode("utf-8")
    meta: dict[str, Any] = {}
    body = text
    if text.startswith("---\n"):
        header, sep, rest = text[4:].partition("\n---\n")
        try:
            loaded = yaml.safe_load(header) if sep else None
        except yaml.YAMLError:
            loaded = None  # A hand-broken header keeps the note readable as plain text.
        if isinstance(loaded, dict):
            meta, body = loaded, rest
    return Note(path.stem, path, meta, body, revision(raw))


def split_minutes(body: str) -> tuple[str, str]:
    """An idea's body: its current account, then the `## Minutes` section."""
    match = MINUTES.search(body)
    if match is None:
        return body.strip(), ""
    return body[: match.start()].strip(), body[match.end() :].strip()


def _squash(text: str) -> str:
    return " ".join(text.split())


def dump(meta: dict[str, Any], body: str) -> str:
    header = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True, width=1000)
    return f"---\n{header}---\n{body.strip()}\n"


def _write(path: Path, content: str) -> None:
    """Atomic replace: a crash leaves either the old or the new file, never half of one."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".md")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _outside_repositories(root: Path) -> Path:
    """Keep private notes out of code checkouts, e.g. this public repository.

    The knowledge base may itself be a (private) git repository; it may not sit inside one.
    """
    root = Path(root).expanduser().resolve()
    for parent in root.parents:
        if (parent / ".git").exists():
            raise CairnError(f"{root} is inside the git repository {parent}; use a private folder")
    return root


def init(root: Path) -> Path:
    root = _outside_repositories(root)
    root.mkdir(parents=True, exist_ok=True)
    (root / MARKER).touch()
    for collection in COLLECTIONS:
        for folder in FOLDERS.values():
            (root / collection / folder).mkdir(parents=True, exist_ok=True)
    return root


class KB:
    """One collection of a knowledge base. Every read and write stays inside it."""

    def __init__(self, root: Path | str, collection: str = "research"):
        self.root = _outside_repositories(root)
        if not (self.root / MARKER).exists():
            raise CairnError(f"{self.root} is not a Cairn knowledge base; run `cairn init`")
        if collection not in COLLECTIONS:
            raise CairnError(f"unknown collection {collection!r}; use one of {COLLECTIONS}")
        self.collection = collection
        self.dir = self.root / collection

    # Reading

    def notes(self) -> dict[str, Note]:
        found: dict[str, Note] = {}
        for folder in FOLDERS.values():
            for path in sorted((self.dir / folder).glob("*.md")):
                found.setdefault(path.stem, parse(path))
        return found

    def resolve(self, name: str, notes: dict[str, Note] | None = None) -> Note | None:
        """Find a note by slug, title or alias."""
        notes = self.notes() if notes is None else notes
        key = _unlink(name)
        if key in notes:
            return notes[key]
        wanted = name.strip().casefold()
        for note in notes.values():
            if wanted in (a.casefold() for a in [note.title, *note.aliases]):
                return note
        return None

    def get(self, name: str) -> dict[str, Any]:
        notes = self.notes()
        note = self.resolve(name, notes)
        if note is None:
            raise CairnError(f"no note named {name!r}; use search or list_topics")

        def ref(slug: str) -> dict[str, Any]:
            other = notes.get(slug)
            if other is None:
                return {"slug": slug, "missing": True}
            return {"slug": slug, "title": other.title, "kind": other.kind}

        result: dict[str, Any] = {
            "slug": note.slug,
            "title": note.title,
            "kind": note.kind,
            "revision": note.revision,
            "path": str(note.path),
            "meta": note.meta,
            "body": note.body,
            "topics": [ref(s) for s in note.topics],
            "links": [ref(s) for s in note.body_links],
            "backlinks": [
                {**ref(o.slug), "via": "topics" if note.slug in o.topics else "body"}
                for o in notes.values()
                if o.slug != note.slug and (note.slug in o.topics or note.slug in o.body_links)
            ],
        }
        return result

    def list_topics(self) -> list[dict[str, Any]]:
        notes = self.notes()
        members: dict[str, list[str]] = {}
        for note in notes.values():
            for topic in note.topics:
                members.setdefault(topic, []).append(note.slug)
        topics = []
        for note in notes.values():
            if note.kind != "topic":
                continue
            inside = members.get(note.slug, [])
            topics.append(
                {
                    "slug": note.slug,
                    "title": note.title,
                    "broader": note.topics,
                    "narrower": [s for s in inside if notes[s].kind == "topic"],
                    "papers": sum(notes[s].kind == "paper" for s in inside),
                    "empty": not note.body.strip(),
                }
            )
        return sorted(topics, key=lambda t: t["title"].casefold())

    def search(self, query: str, limit: int = 10, kind: str | None = None) -> list[dict[str, Any]]:
        terms = [t for t in query.casefold().split() if t]
        hits = []
        for note in self.notes().values():
            if kind and note.kind != kind:
                continue
            title = " ".join([note.title, *note.aliases]).casefold()
            body = note.body.casefold()
            score = sum(5 * title.count(t) + min(body.count(t), 10) for t in terms)
            if score or not terms:
                hits.append((score, note))
        hits.sort(key=lambda h: (-h[0], h[1].title.casefold()))
        return [
            {
                "slug": n.slug,
                "title": n.title,
                "kind": n.kind,
                "topics": n.topics,
                "snippet": _snippet(n.body, terms),
            }
            for _, n in hits[:limit]
        ]

    def suggest_topics(
        self, note: Note, notes: dict[str, Note], limit: int = 5
    ) -> list[dict[str, str]]:
        """Existing topics this note probably belongs to but does not link yet.

        A cheap keyword heuristic: the share of a topic's title words that occur in the note.
        The connected agent decides whether a suggestion is real.
        """
        text = note.text()
        linked = {note.slug, *note.topics, *note.body_links}
        scored = []
        for topic in notes.values():
            if topic.kind != "topic" or topic.slug in linked:
                continue
            best = 0.0
            for name in [topic.title, *topic.aliases]:
                words = [w for w in re.findall(r"\w+", name.casefold()) if w not in STOPWORDS]
                if words:
                    best = max(best, sum(w in text for w in words) / len(words))
            if best >= 0.5:
                scored.append((best, topic))
        scored.sort(key=lambda s: (-s[0], s[1].title.casefold()))
        return [{"slug": t.slug, "title": t.title} for _, t in scored[:limit]]

    # Writing

    @contextmanager
    def lock(self) -> Iterator[None]:
        with open(self.root / ".cairn.lock", "a") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    def save(
        self,
        *,
        kind: str,
        title: str,
        body: str,
        topics: list[str] | None = None,
        aliases: list[str] | None = None,
        revision: str | None = None,
        fields: dict[str, Any] | None = None,
        slug: str | None = None,
        minute: str | None = None,
        review: bool = False,
    ) -> dict[str, Any]:
        """Create or update a note, creating any topics it names that do not exist yet.

        Updating an existing note requires the revision returned by `get`, so edits made
        meanwhile (by you in an editor, or by another session) are never overwritten.
        `slug` names the note to update; with it the title may change, and the old title
        is kept as an alias. Front matter not passed again is kept. For ideas, `minute` is
        appended to the minutes (see `_idea_body`); `review` marks it as a maintenance review.
        """
        if kind not in FOLDERS:
            raise CairnError(f"kind must be one of {list(FOLDERS)}")
        if not title.strip() or not body.strip():
            raise CairnError("title and body are required")
        fields = {k: v for k, v in (fields or {}).items() if v not in (None, "", [])}
        if "source" in fields:
            fields["source"] = normalize_source(str(fields["source"]))
        with self.lock():
            notes = self.notes()
            if slug is not None:
                existing = self._by_slug(kind, slug, title, notes)
            else:
                existing = self._existing(kind, title, fields.get("source"), notes)
            if existing is not None and revision != existing.revision:
                raise CairnError(
                    f"{existing.slug!r} already exists and may hold earlier or hand-made edits; "
                    "call get_note, merge its body into yours, and save with its revision"
                )
            if existing is None and revision is not None:
                raise CairnError("revision given, but no such note exists")
            today = date.today().isoformat()
            if kind == "idea":
                body = self._idea_body(existing, body, fields, minute, review, today)
            elif minute is not None or review:
                raise CairnError("minutes and reviews are only for ideas")
            slug = existing.slug if existing else self._new_slug(title, notes)
            old = existing.meta if existing else {}
            if topics is None:
                topics = [str(t) for t in old.get("topics") or []]
            if aliases is None:
                aliases = [str(a) for a in old.get("aliases") or []]
            if existing and existing.title != title.strip() and existing.title not in aliases:
                aliases = [*aliases, existing.title]

            topic_slugs, created = [], []
            for name in topics or []:
                target = self.resolve(name, notes)
                if target is None:
                    target = self._create_topic(name, notes)
                    created.append(target.slug)
                if target.slug != slug and target.slug not in topic_slugs:
                    topic_slugs.append(target.slug)

            meta: dict[str, Any] = {"title": title.strip(), "kind": kind}
            meta.update((k, v) for k, v in old.items() if k not in MANAGED)
            meta.update(fields)
            if topic_slugs:
                meta["topics"] = [f"[[{s}]]" for s in topic_slugs]
            if aliases:
                meta["aliases"] = aliases
            meta["created"] = existing.meta.get("created", today) if existing else today
            meta["updated"] = today
            path = self.dir / FOLDERS[kind] / f"{slug}.md"
            content = dump(meta, body)
            if existing is None or existing.path.read_text("utf-8") != content:
                _write(path, content)
            note = parse(path)
            notes[slug] = note
            return {
                "slug": slug,
                "title": note.title,
                "kind": kind,
                "path": str(path),
                "revision": note.revision,
                "status": "updated" if existing else "created",
                "topics": topic_slugs,
                "created_topics": created,
                "unresolved_links": [s for s in note.body_links if s not in notes],
                "suggested_topics": self.suggest_topics(note, notes),
            }

    def _idea_body(
        self,
        existing: Note | None,
        body: str,
        fields: dict[str, Any],
        minute: str | None,
        review: bool,
        today: str,
    ) -> str:
        """The account the agent sent, then the stored minutes plus a new dated entry.

        Minutes are append-only, and a retried entry is not added twice. A status change
        needs a reason, and a review (maintenance, not the user's decision) cannot make one.
        """
        account, sent = split_minutes(body)
        minutes = split_minutes(existing.body)[1] if existing else ""
        if not account:
            raise CairnError("the body needs the idea's current account above '## Minutes'")
        if sent and _squash(sent) != _squash(minutes):
            raise CairnError(
                "minutes are append-only: leave the '## Minutes' section as get_note returned "
                "it, or omit it, and pass the new entry as `minute`"
            )
        before = str(existing.meta.get("status", "seed")) if existing else "seed"
        status = str(fields.setdefault("status", before))
        if status not in STATUSES:
            raise CairnError(f"status must be one of {list(STATUSES)}")
        text = (minute or "").strip()
        entry = []
        if existing and status != before:
            if review:
                raise CairnError("a review cannot change an idea's status; that is the user's")
            if not text:
                raise CairnError("give the reason for the status change in `minute`")
            entry.append(f"Status: {before} → {status}.")
        if text and _squash(text) not in _squash(minutes):
            entry.append(text)
        if entry:
            heading = f"### {today}" + (" (review)" if review else "")
            minutes = "\n\n".join(filter(None, [minutes, heading, *entry]))
            fields["last_review" if review else "last_discussed"] = today
        return account + (f"\n\n## Minutes\n\n{minutes}" if minutes else "")

    def _by_slug(self, kind: str, slug: str, title: str, notes: dict[str, Note]) -> Note:
        note = notes.get(_unlink(slug))
        if note is None:
            raise CairnError(f"no note with slug {slug!r}; omit slug to create a note")
        if note.kind != kind:
            raise CairnError(f"{note.slug!r} is a {note.kind}, not a {kind}")
        other = self.resolve(title, notes)
        if other is not None and other.slug != note.slug:
            raise CairnError(f"another note is named {title!r} ({other.slug})")
        return note

    def _existing(
        self, kind: str, title: str, source: str | None, notes: dict[str, Note]
    ) -> Note | None:
        if kind == "paper" and source:
            for note in notes.values():
                if note.kind == "paper" and note.meta.get("source") == source:
                    return note
        note = self.resolve(title, notes)
        if note is None:
            return None
        if note.kind != kind:
            if kind == "paper":
                return None  # A paper may share a topic's name; it gets its own slug.
            raise CairnError(f"a {note.kind} named {note.title!r} already exists ({note.slug})")
        if kind == "paper" and source and note.meta.get("source") not in (None, source):
            return None  # Same title, different paper.
        return note

    def _new_slug(self, title: str, notes: dict[str, Note]) -> str:
        base = slug = slugify(title)
        n = 2
        while slug in notes:
            slug, n = f"{base}-{n}", n + 1
        return slug

    def _create_topic(self, name: str, notes: dict[str, Note]) -> Note:
        title = name.strip().removeprefix("[[").removesuffix("]]").strip()
        slug = self._new_slug(title, notes)
        today = date.today().isoformat()
        path = self.dir / FOLDERS["topic"] / f"{slug}.md"
        _write(
            path, dump({"title": title, "kind": "topic", "created": today, "updated": today}, "")
        )
        notes[slug] = parse(path)
        return notes[slug]


def _snippet(body: str, terms: list[str], width: int = 240) -> str:
    low = body.casefold()
    at = min((i for i in (low.find(t) for t in terms) if i >= 0), default=0)
    start = max(0, at - width // 3)
    return " ".join(body[start : start + width].split())
