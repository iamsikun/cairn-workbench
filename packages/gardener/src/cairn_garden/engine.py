"""Deterministic engine for the kb-gardener skill.

Every subcommand prints JSON. Judgment (what to recommend, how to phrase a digest) belongs to the
agent; this module does the mechanical work: checks, link repair, candidate retrieval, storage
pruning, metrics, applying approved proposals and committing note history.

Run it with `cairn-garden <command>`.
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import json
import os
import re
import secrets
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import tomllib
import urllib.parse
import urllib.request
import uuid
import xml.etree.ElementTree as ET
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from cairn_catalog import paths as catalog_paths

from . import reports

# Shared with the catalog: top-level `workspace` and `collection`, gardener settings in [garden].
CONFIG_FILE = catalog_paths.config_file()
# Runtime state, logs and the private note history, outside the knowledge base.
HOME = Path(
    os.environ.get("CAIRN_GARDEN_STATE")
    or Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state")
    / "cairn-workbench"
    / "garden"
)
# The Zotero extension reads its credential from this fixed path (see bridge/bootstrap.js).
BRIDGE_CREDENTIALS = Path.home() / ".config" / "kb-gardener" / "zotero-local.json"
ZOTERO = os.environ.get("CAIRN_GARDEN_ZOTERO", "http://127.0.0.1:23119/api/users/0")
DEFAULTS = {
    "workspace": None,
    "collection": "research",
    "contact_email": None,
    "agent": "claude",
    "claude_daily_model": "haiku",
    "claude_weekly_model": "sonnet",
    "codex_daily_model": "gpt-6-luna",
    "codex_weekly_model": "gpt-6.1-sol",
    "keep_refreshes": 1,
    "named_backup_days": 14,
    "digest_days_kept": 14,
    "arxiv_categories": [
        "cs.LG",
        "cs.CL",
        "cs.AI",
        "cs.IR",
        "stat.ML",
        "econ.EM",
        "econ.TH",
        "q-fin.GN",
    ],
    "interests": [],
    "exclude_topics": ["research-catalogs"],
    "candidate_limit": 60,
    "discovery_page_limit": 10,
    "timezone": "America/Chicago",
    "agent_timeout_seconds": 1800,
    "html_max_age_days": 8,
    "html_verify_timeout_seconds": 600,
    "zotero_user_id": None,
    "zotero_backend": "auto",
    "zotero_collections": {},
    "zotero_skip_notes": ["journal-catalog", "author-institution-catalog"],
    "zotero_write_limit": 25,
    "reports": "gardening",
}
# References a note must not point to: private or temporary folders and the raw resources folder.
FORBIDDEN = re.compile(
    r"(?:^|[\s(<])(?:/private)?/tmp/|research/resources/|\.codex/attachments/|file://"
)
MD_LINK = re.compile(r"\[([^\]]*)\]\((<[^>]+>|(?:[^()\s]+|\([^()]*\))+)\)")
BARE_PATH = re.compile(
    r"(?:file://)?(?:/private/tmp|/tmp|/Users/[^\s)>`]*?)/[^\s)>`]+|(?:research/resources|\.codex/attachments)/[^\s)>`]+"
)
ZOTERO_KEY = re.compile(r"(?<![A-Z0-9])([A-Z0-9]{8})(?:-[A-Z0-9]{8})?(?:\.txt|-children\.json)")
META_SKIP = {"title", "kind", "topics", "aliases", "created", "updated"}


# Setup -----------------------------------------------------------------------------------------


def config() -> dict:
    cfg = dict(DEFAULTS)
    if CONFIG_FILE.exists():
        values = tomllib.loads(CONFIG_FILE.read_text())
        cfg.update({k: v for k, v in values.items() if k in ("workspace", "collection")})
        cfg.update(values.get("garden") or {})
    for key in ("workspace", "collection"):
        if os.environ.get("CAIRN_" + key.upper()):
            cfg[key] = os.environ["CAIRN_" + key.upper()]
    return cfg


def cairn():
    from cairn import store

    return store


def workspace(cfg) -> Path:
    if not cfg.get("workspace"):
        raise ValueError(f"set `workspace` in {CONFIG_FILE} or $CAIRN_WORKSPACE")
    return Path(cfg["workspace"]).expanduser()


def kb_open(cfg):
    return cairn().KB(workspace(cfg), cfg["collection"])


def catalog_dir() -> Path:
    """The cairn-catalog data folder (its own configuration decides where it is)."""
    return catalog_paths.data_dir()


def workspace_state(cfg) -> Path:
    """Per-workspace state: discovery ledger, run receipts, write gate and locks."""
    root = workspace(cfg).resolve()
    return (
        HOME / "workspaces" / (root.name + "-" + hashlib.sha256(str(root).encode()).hexdigest()[:8])
    )


def state_dir(cfg) -> Path:
    path = workspace_state(cfg)
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_state(cfg) -> dict:
    path = state_dir(cfg) / "state.json"
    return json.loads(path.read_text()) if path.exists() else {}


def save_state(cfg, state: dict) -> None:
    atomic_json(state_dir(cfg) / "state.json", state)


def atomic_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(value, handle, indent=2, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def read_json(path, default):
    return json.loads(path.read_text()) if path.exists() else default


def now(cfg):
    return datetime.now(ZoneInfo(cfg.get("timezone", "America/Chicago")))


@contextlib.contextmanager
def engine_lock(cfg, name="engine", blocking=True):
    # Kernel locks are released on process exit; never steal a live owner's lock.
    with (state_dir(cfg) / (name + ".lock")).open("a+") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def out(data) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False, default=str))


def user_agent() -> str:
    """Crossref and OpenAlex ask polite clients for a contact address (`contact_email`)."""
    email = config().get("contact_email")
    return f"cairn-garden (mailto:{email})" if email else "cairn-garden"


def fetch_json(url: str, timeout: float = 10):
    request = urllib.request.Request(url, headers={"User-Agent": user_agent()})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read())


def fetch_text(url: str, timeout: float = 20) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": user_agent()})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8")


def save_note(kb, note, body: str, **changes):
    """Re-save an existing note with a new body, keeping its metadata, topics and aliases."""
    fields = {k: v for k, v in note.meta.items() if k not in META_SKIP}
    fields.update(changes.pop("fields", {}))
    return kb.save(
        kind=note.kind,
        title=note.title,
        body=body,
        topics=changes.get("topics", note.topics),
        aliases=note.aliases,
        fields=fields,
        revision=note.revision,
    )


def paper_url(meta: dict) -> str | None:
    source = str(meta.get("source") or "")
    url = str(meta.get("url") or "")
    identity = (
        re.sub(r"v\d+$", "", source.lower()) if source.startswith("arxiv:") else source.lower()
    )
    if url and url_id(url) == identity:
        return url  # Keep the inspected version/locator when supplied.
    if source.startswith("doi:"):
        return "https://doi.org/" + source[4:]
    if source.startswith("arxiv:"):
        return "https://arxiv.org/abs/" + source[6:]
    url = meta.get("url")
    return str(url) if url else (source if source.startswith("http") else None)


def norm_title(text: str) -> str:
    return re.sub(r"[\W_]+", " ", str(text).casefold()).strip()


def leaf_terms(cfg, notes) -> list[str]:
    """Specific interests: leaf topics (no narrower topic), their aliases and configured interests."""
    broader = {t for n in notes.values() if n.kind == "topic" for t in n.topics}
    terms = list(cfg["interests"])
    for note in notes.values():
        if note.kind != "topic" or note.slug in broader or note.slug in cfg["exclude_topics"]:
            continue
        terms += [note.title, *note.aliases]
    return list(dict.fromkeys(t for t in terms if len(t) > 2))


# lint ------------------------------------------------------------------------------------------


def forbidden_refs(note) -> list[dict]:
    refs = []
    raw = note.path.read_text("utf-8")
    for number, line in enumerate(raw.splitlines(), 1):
        for match in MD_LINK.finditer(line):
            target = match.group(2).strip("<>")
            if FORBIDDEN.search(target):
                refs.append({"line": number, "target": target, "text": line.strip()[:240]})
        rest = MD_LINK.sub("", line)
        for match in BARE_PATH.finditer(rest):
            if FORBIDDEN.search(match.group(0)):
                refs.append({"line": number, "target": match.group(0), "text": line.strip()[:240]})
    return refs


# A knowledge base may be its own private Git repository, gardened by GitHub Actions.
REPOSITORY_FILES = {".git", ".github", ".gitignore", ".gitattributes", "cairn-workbench.toml"}


def foreign_entries(cfg) -> list[str]:
    """Anything in the workspace besides notes, reports and Cairn's own files: tools, data or state."""
    store = cairn()
    root = workspace(cfg)
    ignored = {".DS_Store"}
    allowed = {store.MARKER, ".cairn.lock", "html", *store.COLLECTIONS, *ignored, *REPOSITORY_FILES}
    allowed.add(reports.root(cfg).relative_to(root).parts[0])
    found = [p.name for p in root.iterdir() if p.name not in allowed]
    for collection in store.COLLECTIONS:
        if (root / collection).is_dir():
            found += [
                f"{collection}/{p.name}"
                for p in (root / collection).iterdir()
                if p.name not in {*store.FOLDERS.values(), *ignored}
            ]
    return sorted(found)


def cmd_lint(args, cfg):
    kb = kb_open(cfg)
    notes = kb.notes()
    inbound: dict[str, int] = {}
    for note in notes.values():
        for slug in {*note.topics, *note.body_links}:
            inbound[slug] = inbound.get(slug, 0) + 1
    report = {
        "notes": len(notes),
        "broken_links": [],
        "orphans": [],
        "empty_topics": [],
        "incomplete_papers": [],
        "forbidden_refs": [],
        "reading_positions": [],
        "report_links": [],
    }
    for note in notes.values():
        if reports.is_legacy_report(note):
            continue
        for slug in note.topics + note.body_links:
            if slug not in notes:
                report["broken_links"].append({"note": note.slug, "target": slug})
        if not note.topics and not note.body_links and not inbound.get(note.slug):
            report["orphans"].append(note.slug)
        if note.kind == "topic" and not note.body.strip():
            report["empty_topics"].append(note.slug)
        if note.kind == "paper":
            missing = [k for k in ("source", "url", "year", "authors") if not note.meta.get(k)]
            if missing or not note.topics:
                report["incomplete_papers"].append(
                    {"note": note.slug, "missing": missing + ([] if note.topics else ["topics"])}
                )
            section = re.search(
                r"^##[^\n]*reading position[^\n]*\n(.*?)(?=^## |\Z)", note.body, re.S | re.M | re.I
            )
            if section:
                report["reading_positions"].append(
                    {
                        "note": note.slug,
                        "updated": str(note.meta.get("updated")),
                        "position": " ".join(section.group(1).split())[:600],
                    }
                )
        for ref in forbidden_refs(note):
            report["forbidden_refs"].append({"note": note.slug, "kind": note.kind, **ref})
    # Reports link notes (and each other) with relative Markdown links; notes may link reports.
    base = reports.root(cfg).resolve()
    for rid, other in {**reports.reports(cfg), reports.INDEX: None}.items():
        path = reports.path_of(cfg, rid)
        if other is None and not path.exists():
            continue
        body = other.body if other else path.read_text("utf-8")
        for target, resolved in reports.local_links(path, body):
            if not resolved.exists():
                report["report_links"].append({"report": rid, "target": target})
    for note in notes.values():
        for target, resolved in reports.local_links(note.path, note.body):
            if resolved.is_relative_to(base) and not resolved.exists():
                report["report_links"].append({"note": note.slug, "target": target})
    report["legacy_reports"] = reports.legacy(notes)
    # The knowledge base holds knowledge only; tools and data belong in cairn-workbench's folders.
    report["foreign_entries"] = foreign_entries(cfg)
    report["summary"] = {k: len(v) for k, v in report.items() if isinstance(v, list)}
    out(report)


# Zotero ----------------------------------------------------------------------------------------

ARXIV_PATTERN = r"(?:\d{4}\.\d{4,5}|[a-z][a-z.-]*/\d{7})"
ARXIV_ID = re.compile(r"(?:arxiv\.org/(?:abs|pdf)/|arxiv[:.]\s*)(" + ARXIV_PATTERN + r")", re.I)
PAPER_URL = re.compile(
    r"https?://(?:(?:dx\.)?doi\.org/(10\.\d{4,9}/[^\s<>\]\|\"`]+)"
    r"|(?:www\.)?arxiv\.org/(?:abs|pdf)/(" + ARXIV_PATTERN + r")(?:v\d+)?(?:\.pdf)?)",
    re.I,
)
SKIP_TYPES = {"attachment", "note", "annotation"}


def zotero_get(path: str, **params):
    query = urllib.parse.urlencode(params)
    return fetch_json(f"{ZOTERO}/{path}" + (f"?{query}" if query else ""), timeout=10)


def zotero_paged(path: str, **params) -> list:
    found, start = [], 0
    while True:
        batch = zotero_get(path, limit=100, start=start, **params)
        found += batch
        if len(batch) < 100:
            return found
        start += 100


def zotero_alive() -> bool:
    try:
        zotero_get("items/top", limit=1)
        return True
    except Exception:
        return False


def zotero_pdf(key: str) -> str | None:
    try:
        children = zotero_get(f"items/{key}/children")
    except Exception:
        return None
    for child in children:
        if child["data"].get("contentType") == "application/pdf":
            return child["key"]
    return None


def item_ids(data: dict) -> set[str]:
    """Identifiers of a Zotero item: DOI and arXiv ID (from DOI, URL, archive ID or Extra)."""
    ids = set()
    doi = urllib.parse.unquote(
        re.sub(
            r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)",
            "",
            str(data.get("DOI", "")).strip().lower(),
        )
    ).strip()
    if doi:
        ids.add("doi:" + doi)
    text = (
        " ".join(str(data.get(k, "")) for k in ("url", "archiveID", "extra"))
        + " "
        + doi.replace("10.48550/arxiv.", "arxiv:")
    )
    ids |= {"arxiv:" + m.group(1).lower() for m in ARXIV_ID.finditer(text)}
    return ids


def url_id(url: str) -> str | None:
    match = PAPER_URL.search(url)
    if not match:
        return None
    if match.group(1):
        doi = (
            urllib.parse.unquote(match.group(1).split("#", 1)[0].split("?", 1)[0])
            .rstrip(".,;")
            .lower()
        )
        while doi.endswith(")") and doi.count(")") > doi.count("("):
            doi = doi[:-1]
        arxiv = re.match(r"10\.48550/arxiv\.(" + ARXIV_PATTERN + r")", doi, re.I)
        return "arxiv:" + arxiv.group(1) if arxiv else "doi:" + doi
    return "arxiv:" + match.group(2).lower()


def note_ids(note) -> set[str]:
    ids = set()
    for value in (note.meta.get("source"), note.meta.get("url"), note.meta.get("doi")):
        if not value:
            continue
        value = str(value)
        if value.startswith("arxiv:"):
            ids.add(re.sub(r"v\d+$", "", value.lower()))
        elif value.startswith("doi:"):
            ids.add(value.lower())
        elif url_id(value):
            ids.add(url_id(value))
        elif value.startswith("10."):
            ids.add("doi:" + value.lower())
    return ids


class ZoteroIndex:
    """The user's Zotero library, read once per run through the local API (read-only)."""

    def __init__(self, items: list, collections: list):
        self.items = {
            i["key"]: i["data"] for i in items if i["data"].get("itemType") not in SKIP_TYPES
        }
        self.collections = {
            c["key"]: {
                "name": c["data"]["name"],
                "parent": c["data"].get("parentCollection") or None,
            }
            for c in collections
        }
        self.by_id: dict[str, str] = {}
        self.duplicates: dict[str, set] = {}
        for key, data in self.items.items():
            for ident in item_ids(data) | {"title:" + norm_title(data.get("title", ""))}:
                if ident == "title:":
                    continue
                if ident in self.by_id and self.by_id[ident] != key:
                    self.duplicates.setdefault(ident, {self.by_id[ident]}).add(key)
                self.by_id.setdefault(ident, key)
        self._pdfs: dict[str, str | None] = {}

    @classmethod
    def load(cls):
        try:
            return cls(zotero_paged("items/top"), zotero_paged("collections"))
        except Exception:
            return None

    def find(self, ids, title: str | None = None) -> str | None:
        ids = set(ids)
        matches = {self.by_id[i] for i in ids if i in self.by_id}
        if any(i in self.duplicates for i in ids) or len(matches) > 1:
            return None
        if matches:
            key = matches.pop()
            actual = item_ids(self.items[key])
            # A match on one identifier does not override another conflicting one.
            for scheme in ("doi:", "arxiv:"):
                wanted = {i for i in ids if i.startswith(scheme)}
                have = {i for i in actual if i.startswith(scheme)}
                if wanted and have and not wanted & have:
                    return None
            return key
        if ids:
            return None  # Title similarity is a discovery lead, not identity evidence.
        ident = "title:" + norm_title(title) if title else ""
        return self.by_id.get(ident) if ident not in self.duplicates else None

    def pdf(self, key: str) -> str | None:
        if key not in self._pdfs:
            self._pdfs[key] = zotero_pdf(key)
        return self._pdfs[key]

    def within(self, key: str) -> set[str]:
        """A collection and all its subcollections."""
        found, frontier = {key}, [key]
        while frontier:
            parent = frontier.pop()
            for child, info in self.collections.items():
                if info["parent"] == parent and child not in found:
                    found.add(child)
                    frontier.append(child)
        return found

    def item_for_key(self, key: str) -> str | None:
        """A top-level item key for an item or attachment key."""
        if key in self.items:
            return key
        try:
            data = zotero_get(f"items/{key}")["data"]
        except Exception:
            return None
        return data.get("parentItem") if data.get("parentItem") in self.items else None


def remote_titles(cfg, idents) -> dict[str, str]:
    """Titles for DOI/arXiv identifiers, cached in the state folder (arXiv in one batch)."""
    path = state_dir(cfg) / "titles.json"
    cache = json.loads(path.read_text()) if path.exists() else {}
    arxiv = [i[6:] for i in idents if i.startswith("arxiv:") and i not in cache]
    for start in range(0, len(arxiv), 50):
        try:
            feed = ET.fromstring(
                fetch_text(
                    "https://export.arxiv.org/api/query?"
                    + urllib.parse.urlencode(
                        {"id_list": ",".join(arxiv[start : start + 50]), "max_results": 50}
                    )
                )
            )
        except Exception:
            break
        ns = {"a": "http://www.w3.org/2005/Atom"}
        for entry in feed.findall("a:entry", ns):
            ident = re.sub(r"v\d+$", "", entry.findtext("a:id", "", ns).rsplit("/", 1)[-1])
            title = " ".join(entry.findtext("a:title", "", ns).split())
            if title and title.lower() != "error":
                cache["arxiv:" + ident] = title
    for ident in [i for i in idents if i.startswith("doi:") and i not in cache][:40]:
        try:
            work = fetch_json(f"https://api.crossref.org/works/{urllib.parse.quote(ident[4:])}")[
                "message"
            ]
            cache[ident] = (work.get("title") or [""])[0]
        except Exception:
            continue
    path.write_text(json.dumps(cache, indent=1, ensure_ascii=False))
    return cache


def resolve_ident(index, ident: str, titles: dict, label: str | None = None) -> str | None:
    """The Zotero item for an identifier: by DOI/arXiv ID, else by the paper's or the link's title."""
    return index.find([ident]) if ident else None


def zotero_link(key: str) -> str:
    return f"zotero://select/library/items/{key}"


def paper_links(note, key: str | None, pdf: str | None) -> str:
    """A paper's source line: its Zotero item and PDF when in Zotero, otherwise its URL."""
    if key:
        return " · ".join(
            [f"[Zotero]({zotero_link(key)})"]
            + ([f"[PDF in Zotero](zotero://open-pdf/library/items/{pdf})"] if pdf else [])
        )
    url = paper_url(note.meta)
    return f"[{note.meta.get('source') or 'link'}]({url})" if url else ""


# fix-links -------------------------------------------------------------------------------------

SOURCE_LINE = re.compile(r"^(\s*(?:[-*]\s*)?)(Local PDF|PDF|Local file|Paper)\s*:\s*(\S.*)$", re.I)


def fix_body(note, index: ZoteroIndex | None, titles: dict | None = None):
    """Repair link spans, retaining labels, annotations, exact versions and ambiguity."""
    edits, unresolved = [], []
    ids = note_ids(note)
    paper_key = index.find(ids) if index and ids and note.kind == "paper" else None
    pdf = index.pdf(paper_key) if paper_key else None
    fenced = False
    lines = []
    for line in note.body.splitlines(keepends=True):
        if line.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
        if fenced or line.lstrip().startswith((">", "```", "~~~")):
            lines.append(line)
            continue
        source = SOURCE_LINE.match(line) if note.kind == "paper" else None

        def resolve(target, primary=False):
            if FORBIDDEN.search(target):
                match = ZOTERO_KEY.search(target)
                key = index.item_for_key(match.group(1)) if match and index else None
                if key:
                    return zotero_link(key)
                if primary and target.split("#")[0].lower().endswith(".pdf"):
                    return zotero_link(paper_key) if paper_key else paper_url(note.meta)
                unresolved.append({"note": note.slug, "target": target})
                return None
            # Replacing an exact version or fragment with an arbitrary PDF loses evidence.
            if (
                re.search(r"v\d+(?:\.pdf)?(?:[#?]|$)", target)
                or urllib.parse.urlsplit(target).fragment
            ):
                return None
            ident = url_id(target)
            key = index.find([ident]) if index and ident else None
            return zotero_link(key) if key else None

        def swap_link(match):
            target = match.group(2).strip("<>")
            new = resolve(target)
            if not new or new == target:
                return match.group(0)
            # Retain labels, even for references to extracted source text.
            replacement = f"[{match.group(1)}]({new})"
            if new in line and not FORBIDDEN.search(target):
                replacement = match.group(1)
            edits.append({"from": match.group(0), "to": replacement})
            return replacement

        def swap_bare(match):
            target = match.group(0).rstrip(".,;")
            # Only an explicitly labelled primary source can use this note's identity.
            primary = bool(source and source.group(3).startswith(target))
            new = resolve(target, primary)
            if not new or new == target:
                return match.group(0)
            if primary and FORBIDDEN.search(target):
                replacement = paper_links(note, paper_key, pdf)
            else:
                replacement = (
                    f"[Zotero]({new})" if new.startswith("zotero:") else f"[Source]({new})"
                )
            edits.append({"from": target, "to": replacement})
            return replacement + match.group(0)[len(target) :]

        # Do not process newly generated links, markdown targets or inline code twice.
        parts, position = [], 0
        for token in re.finditer(r"`+[^`]*`+|" + MD_LINK.pattern, line):
            parts.extend((line[position : token.start()], token.group(0)))
            position = token.end()
        parts.append(line[position:])
        bare = re.compile(BARE_PATH.pattern + "|" + PAPER_URL.pattern)
        new_line = "".join(
            part
            if part.startswith("`")
            else MD_LINK.sub(swap_link, part)
            if part.startswith("[")
            else bare.sub(swap_bare, part)
            for part in parts
        )
        if source and new_line != line and source.group(2).lower() in ("local pdf", "local file"):
            start, end = source.span(2)
            new_line = new_line[:start] + "Paper" + new_line[end:]
        lines.append(new_line)
    return "".join(lines), edits, unresolved, paper_key


def cmd_fix_links(args, cfg):
    kb = kb_open(cfg)
    index = ZoteroIndex.load()
    notes = kb.notes()
    titles = {}
    changes, unresolved = [], []
    for note in notes.values():
        if reports.is_legacy_report(note):
            continue
        body, edits, missing, key = fix_body(note, index, titles)
        unresolved += missing
        if edits and body != note.body:
            entry = {"note": note.slug, "edits": edits, "zotero": key}
            if not args.dry_run:
                entry["saved"] = save_note(kb, note, body)["revision"]
            changes.append(entry)
    out(
        {
            "dry_run": args.dry_run,
            "zotero_available": index is not None,
            "changed": changes,
            "unresolved": unresolved,
        }
    )


# zotero-sync -----------------------------------------------------------------------------------


def zotero_api_key() -> str | None:
    if os.environ.get("ZOTERO_API_KEY"):
        return os.environ["ZOTERO_API_KEY"].strip()
    path = CONFIG_FILE.parent / "zotero.key"
    return path.read_text().strip() if path.exists() else None


def zotero_web(cfg, method: str, path: str, body=None, version=None, write_token=None):
    """The Zotero Web API (the local API cannot write). Needs zotero_user_id and an API key."""
    headers = {
        "Zotero-API-Key": zotero_api_key(),
        "Zotero-API-Version": "3",
        "Content-Type": "application/json",
    }
    if version is not None:
        headers["If-Unmodified-Since-Version"] = str(version)
    if write_token:
        headers["Zotero-Write-Token"] = write_token
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(
        f"https://api.zotero.org/users/{cfg['zotero_user_id']}/{path}",
        data=data,
        headers=headers,
        method=method,
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        text = response.read()
        return json.loads(text) if text else {}


def zotero_writer(cfg):
    """Explicit local configuration never falls back to a different remote library."""
    backend = cfg.get("zotero_backend", "auto")
    if backend not in ("auto", "local", "web"):
        return None, "none", "invalid Zotero backend"
    if backend == "local" or (backend == "auto" and BRIDGE_CREDENTIALS.exists()):
        try:
            from .zotero_local import LocalWriter

            return LocalWriter(cfg, BRIDGE_CREDENTIALS.parent, ZOTERO), "local", None
        except Exception as error:
            return None, "local", str(error)
    available = bool(zotero_api_key() and cfg.get("zotero_user_id"))
    return None, "web", None if available else "Zotero Web API writes are unconfigured"


def sync_local(writer, additions, creations, metadata, ledger, path, reserve, cfg):
    done, failed = [], []
    for add in additions:
        if not reserve():
            break
        try:
            result = writer.request("add", key=add["item"], collections=add["add"])
            result = writer.verify(result, add["add"], zotero_get)
            done.append(
                {
                    "operation": "add",
                    "item": result["key"],
                    "status": "added" if result["changed"] else "already present",
                    "to": add["collections"],
                    "verified": True,
                    "before_collections": result["before_collections"],
                    "collections": result["collections"],
                }
            )
        except Exception as error:
            failed.append({"item": add["item"], "error": str(error)})
    for new in creations:
        ident = new["id"]
        if not new["verified"]:
            failed.append({"id": ident, "error": "identifier not externally verified; not created"})
            continue
        receipt = ledger["creations"].get(ident)
        if receipt and receipt.get("backend") != "local":
            failed.append(
                {
                    "id": ident,
                    "error": "prior Web API creation must be reconciled before changing backends",
                }
            )
            continue
        if not receipt:
            receipt = {
                "backend": "local",
                "status": "pending",
                "at": now(cfg).isoformat(),
                "requested_key": "".join(
                    secrets.choice("23456789ABCDEFGHIJKLMNPQRSTUVWXYZ") for _ in range(8)
                ),
            }
            ledger["creations"][ident] = receipt
        if not reserve():
            break
        try:
            # Retry the same durable key. The bridge reconciles identities and keys in one transaction.
            result = writer.request(
                "create",
                key=receipt["requested_key"],
                identity=ident,
                data=metadata[ident],
                collections=new["targets"],
            )
            result = writer.verify(result, new["targets"], zotero_get, identity=ident, ids=item_ids)
            receipt.update(status="confirmed", key=result["key"])
            atomic_json(path, ledger)
            done.append(
                {
                    "operation": "create" if result["created"] else "add",
                    "id": ident,
                    "created": ident if result["created"] else None,
                    "title": metadata[ident]["title"],
                    "key": result["key"],
                    "status": "created"
                    if result["created"]
                    else "added"
                    if result["changed"]
                    else "already present",
                    "in": new["collections"],
                    "verified": True,
                    "before_collections": result["before_collections"],
                    "collections": result["collections"],
                }
            )
        except Exception as error:
            failed.append({"id": ident, "error": str(error)})
    return done, failed


def topic_collections(cfg, notes, index: ZoteroIndex) -> dict[str, str]:
    """The Zotero collection that mirrors each topic note.

    Precedence: `zotero_collections` in the config, a collection the topic note links to, then a
    collection whose name matches the topic's title or an alias (singular/plural ignored).
    """

    def norm(name):
        return re.sub(r"s\b", "", norm_title(name))

    by_name: dict[str, list[str]] = {}
    for key, info in index.collections.items():
        by_name.setdefault(norm(info["name"]), []).append(key)
    mapping = {}
    for note in notes.values():
        if note.kind != "topic":
            continue
        explicit = cfg.get("zotero_collections", {}).get(note.slug)
        linked = re.search(
            r"zotero://select/library/collections/([A-Z0-9]{8})|collection key `?([A-Z0-9]{8})",
            note.body,
        )
        named = next(
            (
                by_name[norm(n)]
                for n in [note.title, *note.aliases]
                if len(by_name.get(norm(n), [])) == 1
            ),
            [None],
        )
        key = explicit or (linked and (linked.group(1) or linked.group(2))) or named[0]
        if key in index.collections:
            mapping[note.slug] = key
    return mapping


def collection_for(slug: str, notes, mapping: dict, seen=None) -> str | None:
    """A topic's own collection, or the nearest broader topic's."""
    if slug in mapping:
        return mapping[slug]
    seen = seen or set()
    note = notes.get(slug)
    for broader in note.topics if note else []:
        if broader not in seen:
            found = collection_for(broader, notes, mapping, seen | {slug})
            if found:
                return found
    return None


def remote_metadata(ident: str) -> dict | None:
    """Bibliographic fields for a paper that is not in Zotero yet."""
    try:
        if ident.startswith("arxiv:"):
            feed = ET.fromstring(
                fetch_text(f"https://export.arxiv.org/api/query?id_list={ident[6:]}")
            )
            ns = {"a": "http://www.w3.org/2005/Atom"}
            entry = feed.find("a:entry", ns)
            title = " ".join(entry.findtext("a:title", "", ns).split()) if entry is not None else ""
            if not title or title.lower() == "error":
                return None
            returned = url_id(entry.findtext("a:id", "", ns))
            if returned != ident:
                return None
            return {
                "itemType": "preprint",
                "title": title,
                "repository": "arXiv",
                "archiveID": f"arXiv:{ident[6:]}",
                "url": f"https://arxiv.org/abs/{ident[6:]}",
                "DOI": f"10.48550/arXiv.{ident[6:]}",
                "date": entry.findtext("a:published", "", ns)[:10],
                "abstractNote": " ".join(entry.findtext("a:summary", "", ns).split()),
                "creators": [
                    creator(a.findtext("a:name", "", ns)) for a in entry.findall("a:author", ns)
                ],
            }
        work = fetch_json(f"https://api.crossref.org/works/{urllib.parse.quote(ident[4:])}")[
            "message"
        ]
        if str(work.get("DOI", "")).lower() != ident[4:].lower():
            return None
        parts = (work.get("issued", {}).get("date-parts") or [[None]])[0]
        return {
            "itemType": "journalArticle",
            "title": (work.get("title") or [""])[0],
            "DOI": ident[4:],
            "url": f"https://doi.org/{ident[4:]}",
            "publicationTitle": (work.get("container-title") or [""])[0],
            "date": "-".join(str(p) for p in parts if p),
            "creators": [
                {
                    "creatorType": "author",
                    "firstName": a.get("given", ""),
                    "lastName": a.get("family", a.get("name", "")),
                }
                for a in work.get("author", [])
            ],
        }
    except Exception:
        return None


def creator(name: str) -> dict:
    first, _, last = name.strip().rpartition(" ")
    return {"creatorType": "author", "firstName": first, "lastName": last or name}


def note_metadata(note) -> dict:
    ident = next(iter(note_ids(note)), "")
    data = {
        "itemType": "preprint" if ident.startswith("arxiv:") else "journalArticle",
        "title": note.title,
        "url": paper_url(note.meta) or "",
        "date": str(note.meta.get("year") or ""),
        "creators": [creator(str(a)) for a in note.meta.get("authors") or []],
    }
    if ident.startswith("arxiv:"):
        data.update(
            {
                "repository": "arXiv",
                "archiveID": f"arXiv:{ident[6:]}",
                "DOI": f"10.48550/arXiv.{ident[6:]}",
            }
        )
    elif ident.startswith("doi:"):
        data["DOI"] = ident[4:]
    return data


def cited_sources(note, notes, index):
    """One resolver for web links, repaired Zotero links, and paper wikilinks."""
    ids, keys = set(), set()
    if note.kind == "paper":
        ids |= note_ids(note)
    ids |= {url_id(m.group(0)) for m in PAPER_URL.finditer(note.body)} - {None}
    for match in re.finditer(
        r"zotero://(?:select|open-pdf)/library/items/([A-Z0-9]{8})", note.body
    ):
        key = index.item_for_key(match.group(1))
        if key:
            keys.add(key)
    for slug in note.body_links:
        other = notes.get(slug)
        if other and other.kind == "paper":
            ids |= note_ids(other)
    return ids, keys


def remote_zotero_index(cfg):
    items, start = [], 0
    while True:
        batch = zotero_web(cfg, "GET", f"items/top?limit=100&start={start}")
        items.extend(batch)
        if len(batch) < 100:
            return ZoteroIndex(items, [])
        start += 100


def cmd_zotero_sync(args, cfg):
    kb = kb_open(cfg)
    notes, index = kb.notes(), ZoteroIndex.load()
    if index is None:
        out(
            {
                "zotero_available": False,
                "can_write": False,
                "dry_run": args.dry_run,
                "backend": cfg.get("zotero_backend"),
                "done": [],
                "failed": [],
                "note": "Local Zotero library is unavailable",
            }
        )
        return
    mapping = topic_collections(cfg, notes, index)
    wanted, unmapped = {}, set()
    for note in notes.values():
        if reports.is_legacy_report(note) or note.slug in cfg.get("zotero_skip_notes", []):
            continue
        homes = [note.slug] if note.kind == "topic" else note.topics
        targets = {c for c in (collection_for(t, notes, mapping) for t in homes) if c}
        ids, keys = cited_sources(note, notes, index)
        if not targets and (ids or keys):
            unmapped.add(note.slug)
            continue
        for ident in sorted(ids):
            key = index.find([ident])
            if key:
                keys.add(key)
            else:
                entry = wanted.setdefault(ident, {"targets": set(), "notes": set()})
                entry["targets"] |= targets
                entry["notes"].add(note.slug)
        for key in keys:
            entry = wanted.setdefault("item:" + key, {"targets": set(), "notes": set()})
            entry["targets"] |= targets
            entry["notes"].add(note.slug)
    additions, creations, metadata = [], [], {}
    for ident, entry in sorted(wanted.items()):
        if not entry["targets"]:
            continue
        if ident.startswith("item:"):
            key = ident[5:]
            have = set(index.items[key].get("collections", []))
            missing = sorted(t for t in entry["targets"] if not index.within(t) & have)
            if missing:
                additions.append(
                    {
                        "item": key,
                        "title": index.items[key].get("title"),
                        "add": missing,
                        "collections": [index.collections[c]["name"] for c in missing],
                        "cited_in": sorted(entry["notes"]),
                    }
                )
        else:
            # Neither a note nor a cached title is proof that this identifier exists.
            data = remote_metadata(ident)
            metadata[ident] = data
            creations.append(
                {
                    "id": ident,
                    "title": data.get("title") if data else None,
                    "verified": bool(data and ident in item_ids(data)),
                    "targets": sorted(entry["targets"]),
                    "cited_in": sorted(entry["notes"]),
                    "collections": [index.collections[c]["name"] for c in sorted(entry["targets"])],
                }
            )
    writer, backend, write_error = zotero_writer(cfg)
    can_write = write_error is None
    path = state_dir(cfg) / "zotero-writes.json"
    ledger = read_json(path, {"days": {}, "creations": {}})
    day = now(cfg).date().isoformat()
    used = ledger["days"].get(day, 0)
    allowance = max(0, cfg["zotero_write_limit"] - used)
    budget = min(allowance, args.limit if args.limit is not None else allowance)
    done, failed = [], []

    def reserve():
        nonlocal budget
        if budget <= 0:
            return False
        budget -= 1
        ledger["days"][day] = ledger["days"].get(day, 0) + 1
        atomic_json(path, ledger)  # Reserve before sending: unknown outcomes consume budget.
        return True

    def add_membership(key, targets):
        current = zotero_web(cfg, "GET", f"items/{key}")
        before = set(current["data"].get("collections", []))
        after = before | set(targets)
        if after == before:
            return "already present"
        if not reserve():
            return "daily budget exhausted"
        zotero_web(
            cfg, "PATCH", f"items/{key}", {"collections": sorted(after)}, version=current["version"]
        )
        return "added"

    if not args.dry_run and can_write and backend == "local":
        done, failed = sync_local(
            writer, additions, creations, metadata, ledger, path, reserve, cfg
        )
    if not args.dry_run and can_write and backend == "web":
        for add in additions:
            try:
                status = add_membership(add["item"], add["add"])
                done.append({"item": add["item"], "status": status, "to": add["collections"]})
            except Exception as error:
                failed.append({"item": add["item"], "error": str(error)})
        remote = None
        for new in creations:
            ident = new["id"]
            if not new["verified"]:
                failed.append(
                    {"id": ident, "error": "identifier not externally verified; not created"}
                )
                continue
            try:
                if remote is None:
                    remote = remote_zotero_index(cfg)
                receipt = ledger["creations"].get(ident)
                key = remote.find([ident]) or (receipt or {}).get("key")
                if key:
                    status = add_membership(key, new["targets"])
                    ledger["creations"][ident] = {"key": key, "status": "confirmed"}
                    atomic_json(path, ledger)
                    done.append({"id": ident, "key": key, "status": status})
                    continue
                if receipt:  # Unknown POST outcome: reconcile; never blindly recreate.
                    failed.append(
                        {
                            "id": ident,
                            "error": "pending creation not yet reconciled; no repeat POST",
                        }
                    )
                    continue
                if ident in index.duplicates or ident in remote.duplicates:
                    failed.append(
                        {"id": ident, "error": "ambiguous duplicate identity; resolve in Zotero"}
                    )
                    continue
                if budget <= 0:
                    break
                data = {**metadata[ident], "collections": new["targets"]}
                receipt = {
                    "status": "pending",
                    "token": uuid.uuid4().hex,
                    "at": now(cfg).isoformat(),
                }
                ledger["creations"][ident] = receipt
                reserve()  # Persists both the pending creation and daily attempt count.
                result = zotero_web(cfg, "POST", "items", [data], write_token=receipt["token"])
                if result.get("failed"):
                    raise RuntimeError(json.dumps(result["failed"]))
                successful = next(iter(result.get("successful", {}).values()), {})
                key = successful.get("key") or next(iter(result.get("success", {}).values()), None)
                if not key:
                    raise RuntimeError("creation response has no key; reconcile before retrying")
                receipt.update(key=key, status="confirmed")
                atomic_json(path, ledger)
                done.append(
                    {"created": ident, "title": data["title"], "key": key, "in": new["collections"]}
                )
            except Exception as error:
                failed.append({"id": ident, "error": str(error)})
    out(
        {
            "zotero_available": True,
            "can_write": can_write,
            "dry_run": args.dry_run,
            "backend": backend,
            "bridge": writer.status if writer else None,
            "topic_collections": {s: index.collections[k]["name"] for s, k in mapping.items()},
            "to_add": additions,
            "to_create": creations,
            "done": done,
            "failed": failed,
            "daily_writes_used": ledger["days"].get(day, 0),
            "daily_write_limit": cfg["zotero_write_limit"],
            "unmapped_notes": sorted(unmapped),
            "duplicates": [
                {"id": i, "items": sorted(keys)}
                for i, keys in index.duplicates.items()
                if not i.startswith("title:")
            ],
            "note": write_error,
        }
    )


# new-papers ------------------------------------------------------------------------------------


def fts_query(terms: list[str]) -> str:
    phrases = ['"' + re.sub(r'["*^:()]', " ", t).strip() + '"' for t in terms]
    return " OR ".join(p for p in phrases if p != '""')


def catalog_candidates(cfg, terms, since: str, limit: int, offset=0) -> dict:
    db = catalog_dir() / "catalog.sqlite"
    if not db.exists() or not terms:
        return {"available": db.exists(), "complete": True, "new_total": 0, "candidates": []}
    # Inclusive date overlap is intentional: the catalog ledger has day precision.
    with contextlib.closing(sqlite3.connect(f"file:{db}?mode=ro", uri=True)) as con:
        recent = (now(cfg).date() - timedelta(days=120)).isoformat()
        cap = limit * cfg.get("discovery_page_limit", 10)
        rows = con.execute(
            "SELECT p.id,p.title,p.authors_json,p.abstract,p.doi,p.date,j.title,f.first_seen "
            "FROM paper_search s JOIN papers p ON p.id=s.paper_id "
            "JOIN paper_first_seen f ON f.paper_id=p.id JOIN journals j ON j.id=p.journal_id "
            "WHERE paper_search MATCH ? AND f.first_seen >= ? AND p.entry_type='article_or_other' "
            "AND (p.date IS NULL OR p.date >= ?) ORDER BY f.first_seen,p.id LIMIT ? OFFSET ?",
            (fts_query(terms), since[:10], recent, cap + 1, offset),
        ).fetchall()
    return {
        "available": True,
        "complete": len(rows) <= cap,
        "next_offset": offset + cap if len(rows) > cap else None,
        "candidates": [
            {
                "source": "catalog",
                "id": r[0],
                "title": r[1],
                "authors": json.loads(r[2])[:6],
                "abstract": (r[3] or "")[:1200],
                "url": f"https://doi.org/{r[4]}" if r[4] else None,
                "doi": r[4],
                "date": r[5],
                "venue": r[6],
                "first_seen": r[7],
            }
            for r in rows[:cap]
        ],
    }


def arxiv_candidates(cfg, terms, since: str, limit: int, offset=0) -> dict:
    if not terms or not cfg["arxiv_categories"]:
        return {"available": True, "complete": True, "candidates": []}
    cats = " OR ".join(f"cat:{c}" for c in cfg["arxiv_categories"])
    words = " OR ".join('abs:"' + t.replace('"', "") + '"' for t in terms[:25])
    found = []
    ns = {"a": "http://www.w3.org/2005/Atom"}
    for _ in range(cfg.get("discovery_page_limit", 10)):
        query = urllib.parse.urlencode(
            {
                "search_query": f"({cats}) AND ({words})",
                "sortBy": "submittedDate",
                "sortOrder": "descending",
                "max_results": limit,
                "start": offset,
            }
        )
        try:
            feed = ET.fromstring(fetch_text(f"https://export.arxiv.org/api/query?{query}"))
            entries = feed.findall("a:entry", ns)
            if any(e.findtext("a:title", "", ns).strip().lower() == "error" for e in entries):
                raise ValueError("arXiv returned an error entry")
        except Exception as error:
            return {"available": False, "complete": False, "error": str(error), "candidates": found}
        for entry in entries:
            published = entry.findtext("a:published", "", ns)
            if published[:10] < since[:10]:
                return {"available": True, "complete": True, "candidates": found}
            link = entry.findtext("a:id", "", ns).replace("http://", "https://")
            found.append(
                {
                    "source": "arxiv",
                    "id": url_id(link),
                    "title": " ".join(entry.findtext("a:title", "", ns).split()),
                    "authors": [
                        a.findtext("a:name", "", ns) for a in entry.findall("a:author", ns)
                    ][:6],
                    "abstract": " ".join(entry.findtext("a:summary", "", ns).split())[:1200],
                    "url": re.sub(r"v\d+$", "", link),
                    "date": published[:10],
                }
            )
        offset += len(entries)
        if len(entries) < limit:
            return {"available": True, "complete": True, "candidates": found}
    return {"available": True, "complete": False, "next_offset": offset, "candidates": found}


def zotero_recent(since: str, limit: int = 50, offset=0, pages=10) -> dict:
    found = []
    for _ in range(pages):
        try:
            items = zotero_get(
                "items/top", sort="dateAdded", direction="desc", limit=limit, start=offset
            )
        except Exception as error:
            return {"available": False, "complete": False, "error": str(error), "candidates": found}
        for item in items:
            data = item["data"]
            if data.get("dateAdded", "")[:10] < since[:10]:
                return {"available": True, "complete": True, "candidates": found}
            if data.get("itemType") in SKIP_TYPES:
                continue
            found.append(
                {
                    "source": "zotero",
                    "id": item["key"],
                    "title": data.get("title"),
                    "authors": [
                        f"{c.get('firstName', '')} {c.get('lastName', c.get('name', ''))}".strip()
                        for c in data.get("creators", [])
                    ][:6],
                    "abstract": (data.get("abstractNote") or "")[:1200],
                    "doi": data.get("DOI"),
                    "url": data.get("url")
                    or (f"https://doi.org/{data['DOI']}" if data.get("DOI") else None),
                    "zotero": zotero_link(item["key"]),
                    "date": data.get("dateAdded", "")[:10],
                }
            )
        offset += len(items)
        if len(items) < limit:
            return {"available": True, "complete": True, "candidates": found}
    return {"available": True, "complete": False, "next_offset": offset, "candidates": found}


def known_sources(notes) -> tuple[set, set]:
    sources = set().union(*(note_ids(n) for n in notes.values() if n.kind == "paper"))
    titles = {norm_title(n.title) for n in notes.values() if n.kind == "paper"}
    return sources, titles


def candidate_identity(candidate):
    if candidate.get("doi"):
        return url_id("https://doi.org/" + candidate["doi"])
    return url_id(candidate.get("url") or "") or (
        candidate["id"]
        if str(candidate["id"]).startswith("arxiv:")
        else f"{candidate['source']}:{candidate['id']}"
    )


def rekey_discoveries(ledger):
    """Migrate cached identities without losing delivery or review receipts."""
    updated = {}
    for entry in ledger["candidates"].values():
        ident = candidate_identity(entry["candidate"])
        entry["identity"] = entry["candidate"]["identity"] = ident
        previous = updated.get(ident)
        if previous:
            sources = sorted(set(previous["sources"] + entry["sources"]))
            discovered = min(previous["discovered_at"], entry["discovered_at"])
            reviewed = max(previous.get("reviewed_at", ""), entry.get("reviewed_at", ""))
            if previous.get("status") == "delivered":
                entry = {**entry, **previous}
            entry.update(sources=sources, discovered_at=discovered, reviewed_at=reviewed)
        updated[ident] = entry
    ledger["candidates"] = updated
    return ledger


def cmd_new_papers(args, cfg):
    notes = kb_open(cfg).notes()
    state = load_state(cfg)
    since = (
        args.since or state.get("last_digest") or (now(cfg).date() - timedelta(days=2)).isoformat()
    )
    terms, sources = leaf_terms(cfg, notes), known_sources(notes)[0]
    limit = args.limit or cfg["candidate_limit"]
    path = state_dir(cfg) / "discoveries.json"
    ledger = rekey_discoveries(read_json(path, {"candidates": {}, "sources": {}}))
    stamp = now(cfg).isoformat()
    status = {}
    for source in ("catalog", "arxiv", "zotero"):
        progress = ledger["sources"].get(source, {}) if args.record else {}
        resume = progress.get("pending") or {}
        start = resume.get("since") or progress.get("cursor") or since
        # Broad overlap covers late announcements, date precision and local sync delay.
        window = (
            date.fromisoformat(start[:10]) - timedelta(days=5 if source == "arxiv" else 1)
        ).isoformat()
        if resume:
            window = resume["window"]
        offset = resume.get("offset", 0)
        try:
            if source == "catalog":
                result = catalog_candidates(cfg, terms, window, limit, offset=offset)
            elif source == "arxiv":
                result = arxiv_candidates(cfg, terms, window, limit, offset=offset)
            else:
                result = zotero_recent(
                    window, offset=offset, pages=cfg.get("discovery_page_limit", 10)
                )
        except Exception as error:
            result = {"available": False, "complete": False, "error": str(error), "candidates": []}
        for candidate in result["candidates"]:
            ident = candidate_identity(candidate)
            if not ident:
                continue
            entry = ledger["candidates"].setdefault(
                ident,
                {"identity": ident, "discovered_at": stamp, "status": "discovered", "sources": []},
            )
            if source not in entry["sources"]:
                entry["sources"].append(source)
            entry["candidate"] = {
                **entry.get("candidate", {}),
                **candidate,
                "identity": ident,
                "already_in_kb": ident in sources,
            }
            entry["last_seen_at"] = stamp
        if args.record and result.get("available"):
            if result.get("complete", True):
                ledger["sources"][source] = {
                    "cursor": resume.get("started_at", stamp),
                    "last_success_at": stamp,
                }
            else:
                ledger["sources"][source] = {
                    **progress,
                    "pending": {
                        "since": start,
                        "window": window,
                        "offset": result.get("next_offset", offset),
                        "started_at": resume.get("started_at", stamp),
                    },
                }
        elif args.record and not progress:
            ledger["sources"][source] = {"cursor": since}
        # A failed source keeps its own cursor and pending page. Other sources can proceed.
        status[source] = {k: v for k, v in result.items() if k != "candidates"}
    if args.record:
        atomic_json(path, ledger)  # Discovery is durable, but delivery is not acknowledged here.
    result = {"since": since, "interest_terms": terms, "pending_total": 0}
    for source in status:
        entries = [
            entry
            for entry in ledger["candidates"].values()
            if source in entry["sources"]
            and (
                (entry.get("status") != "delivered" and entry["identity"] not in sources)
                if args.record
                else entry["discovered_at"][:10] >= since[:10]
            )
        ]
        # Prefer never-reviewed discoveries, then rotate the least recently reviewed backlog.
        entries.sort(key=lambda e: (e["discovered_at"], e["identity"]), reverse=True)
        entries.sort(key=lambda e: e.get("reviewed_at", ""))
        result[source] = {
            **status[source],
            "candidates": [e["candidate"] for e in entries[:limit]],
            "pending_count": len(entries),
            "truncated": len(entries) > limit,
        }
        result["pending_total"] += len(entries)
    out(result)


def acknowledge_digest(cfg, note, selected, reviewed=()):
    """Delivery is acknowledged only for verified citations in a persisted digest."""
    path = state_dir(cfg) / "discoveries.json"
    ledger = read_json(path, {"candidates": {}, "sources": {}})
    for ident in selected:
        entry = ledger["candidates"].get(ident)
        if entry is None:
            raise ValueError(f"unknown discovery identity: {ident}")
        c = entry["candidate"]
        if not any(link and link in note.body for link in (c.get("url"), c.get("zotero"))):
            raise ValueError(f"digest has no source citation for {ident}")
    for ident in selected:
        ledger["candidates"][ident].update(
            status="delivered", delivered_at=now(cfg).isoformat(), digest=reports.ident(cfg, note)
        )
    for ident in reviewed:
        if ident in ledger["candidates"]:
            ledger["candidates"][ident]["reviewed_at"] = now(cfg).isoformat()
    atomic_json(path, ledger)


# zotero-gaps -----------------------------------------------------------------------------------


def cmd_zotero_gaps(args, cfg):
    """Items in Zotero collections linked from topic notes that have no Cairn paper note yet."""
    kb = kb_open(cfg)
    notes = kb.notes()
    if not zotero_alive():
        out({"zotero_available": False})
        return
    sources, titles = known_sources(notes)
    report = []
    for note in notes.values():
        keys = re.findall(
            r"zotero://select/library/collections/([A-Z0-9]{8})|collection key `?([A-Z0-9]{8})",
            note.body,
        )
        for key in dict.fromkeys(a or b for a, b in keys):
            missing, start = [], 0
            while True:
                try:
                    batch = zotero_get(f"collections/{key}/items/top", limit=100, start=start)
                except Exception:
                    break
                for item in batch:
                    data = item["data"]
                    doi = str(data.get("DOI", "")).lower()
                    if ("doi:" + doi) in sources or norm_title(data.get("title", "")) in titles:
                        continue
                    missing.append(
                        {
                            "key": item["key"],
                            "title": data.get("title"),
                            "year": str(data.get("date", ""))[:4],
                            "url": data.get("url")
                            or (f"https://doi.org/{data['DOI']}" if data.get("DOI") else None),
                            "zotero": f"zotero://select/library/items/{item['key']}",
                        }
                    )
                if len(batch) < 100:
                    break
                start += 100
            report.append({"topic": note.slug, "collection": key, "missing_notes": missing})
    out({"zotero_available": True, "collections": report})


# snapshot --------------------------------------------------------------------------------------


def cmd_snapshot(args, cfg):
    """A compact map of the knowledge base for the agent: notes, links, recent changes."""
    kb = kb_open(cfg)
    notes = kb.notes()
    since = (date.today() - timedelta(days=args.days)).isoformat()
    backlinks: dict[str, list[str]] = {}
    for note in notes.values():
        for slug in {*note.topics, *note.body_links}:
            backlinks.setdefault(slug, []).append(note.slug)
    rows = []
    for note in notes.values():
        if reports.is_legacy_report(note) and not args.include_garden:
            continue
        rows.append(
            {
                "slug": note.slug,
                "kind": note.kind,
                "title": note.title,
                "aliases": note.aliases,
                "topics": note.topics,
                "links": note.body_links,
                "backlinks": backlinks.get(note.slug, []),
                "source": note.meta.get("source"),
                "year": note.meta.get("year"),
                "updated": str(note.meta.get("updated")),
                "recent": str(note.meta.get("updated")) >= since,
                "headings": re.findall(r"^#{2,3} (.+)$", note.body, re.M)[:30],
                "chars": len(note.body),
            }
        )
    result = {
        "collection": cfg["collection"],
        "recent_since": since,
        "topics": kb.list_topics(),
        "notes": rows,
    }
    if args.include_garden:
        result["reports"] = [
            {"id": rid, "title": n.title, "updated": str(n.meta.get("updated"))}
            for rid, n in reports.reports(cfg).items()
        ]
    out(result)


# verify ----------------------------------------------------------------------------------------


def cmd_verify(args, cfg):
    """Check that a recommended paper exists, so nothing invented reaches a note."""
    db = catalog_dir() / "catalog.sqlite"
    if args.doi:
        doi = args.doi.lower().removeprefix("https://doi.org/").removeprefix("doi:")
        if db.exists():
            con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            row = con.execute(
                "SELECT p.id, p.title, p.year FROM papers p LEFT JOIN paper_dois d ON d.paper_id = p.id "
                "WHERE p.doi = ? OR d.doi = ? LIMIT 1",
                (doi, doi),
            ).fetchone()
            con.close()
            if row:
                out(
                    {
                        "verified": True,
                        "via": "catalog",
                        "catalog_id": row[0],
                        "title": row[1],
                        "year": row[2],
                        "url": f"https://doi.org/{doi}",
                        "importable": True,
                    }
                )
                return
        try:
            work = fetch_json(f"https://api.crossref.org/works/{urllib.parse.quote(doi)}")[
                "message"
            ]
            out(
                {
                    "verified": True,
                    "via": "crossref",
                    "title": (work.get("title") or [""])[0],
                    "year": (work.get("issued", {}).get("date-parts") or [[None]])[0][0],
                    "url": f"https://doi.org/{doi}",
                }
            )
        except Exception as error:
            out({"verified": False, "doi": doi, "error": str(error)})
    elif args.arxiv:
        ident = re.sub(r"^(arxiv:|https?://arxiv\.org/(abs|pdf)/)", "", args.arxiv, flags=re.I)
        try:
            feed = ET.fromstring(fetch_text(f"https://export.arxiv.org/api/query?id_list={ident}"))
            ns = {"a": "http://www.w3.org/2005/Atom"}
            entry = feed.find("a:entry", ns)
            title = " ".join(
                (entry.findtext("a:title", "", ns) if entry is not None else "").split()
            )
            ok = bool(title) and title.lower() != "error"
            out(
                {
                    "verified": ok,
                    "via": "arxiv",
                    "title": title,
                    "url": f"https://arxiv.org/abs/{ident}",
                    "year": (entry.findtext("a:published", "", ns)[:4] if ok else None),
                }
            )
        except Exception as error:
            out({"verified": False, "arxiv": ident, "error": str(error)})
    else:
        query = urllib.parse.urlencode({"query.bibliographic": args.title, "rows": 3})
        try:
            items = fetch_json(f"https://api.crossref.org/works?{query}")["message"]["items"]
        except Exception as error:
            out({"verified": False, "error": str(error)})
            return
        matches = [
            {
                "title": (i.get("title") or [""])[0],
                "doi": i.get("DOI"),
                "year": (i.get("issued", {}).get("date-parts") or [[None]])[0][0],
            }
            for i in items
        ]
        exact = [m for m in matches if norm_title(m["title"]) == norm_title(args.title)]
        if not exact:  # Preprints often exist only on arXiv.
            query = urllib.parse.urlencode(
                {"search_query": 'ti:"' + args.title.replace('"', "") + '"', "max_results": 3}
            )
            try:
                feed = ET.fromstring(fetch_text(f"https://export.arxiv.org/api/query?{query}"))
                ns = {"a": "http://www.w3.org/2005/Atom"}
                for entry in feed.findall("a:entry", ns):
                    title = " ".join(entry.findtext("a:title", "", ns).split())
                    if norm_title(title) == norm_title(args.title):
                        link = re.sub(
                            r"v\d+$",
                            "",
                            entry.findtext("a:id", "", ns).replace("http://", "https://"),
                        )
                        exact.append(
                            {
                                "title": title,
                                "arxiv": link.rsplit("/", 1)[-1],
                                "url": link,
                                "year": entry.findtext("a:published", "", ns)[:4],
                            }
                        )
            except Exception:
                pass
        out({"verified": bool(exact), "via": "crossref/arxiv title", "matches": exact or matches})


# storage ---------------------------------------------------------------------------------------


def du_bytes(path: Path) -> int:
    try:
        return (
            int(
                subprocess.run(
                    ["du", "-sk", str(path)], capture_output=True, text=True
                ).stdout.split()[0]
            )
            * 1024
        )
    except Exception:
        return 0


def edition_time(run: Path) -> tuple[str, bool] | None:
    """When a run published a new edition (its `previous/` holds the edition it replaced)."""
    for marker, key in (("report.json", "completed_at"), ("publication.json", "published_at")):
        path = run / marker
        if path.exists():
            info = json.loads(path.read_text())
            return info.get(key) or "", info.get("status") == "success"
    return None


def cmd_storage(args, cfg):
    catalog = catalog_dir()
    keep = cfg["keep_refreshes"] if args.keep is None else args.keep
    if not isinstance(keep, int) or keep < 1:
        raise ValueError(
            "keep_refreshes must be at least 1; the last recovery edition is protected"
        )
    if not catalog.exists():
        out({"catalog": False})
        return
    lock = (catalog / "update.lock").open("a")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        out({"skipped": "a catalog refresh holds update.lock"})
        return
    if (catalog / "update-pending.json").exists():
        out(
            {
                "skipped": "update-pending.json exists; an interrupted publication needs recovery first"
            }
        )
        return
    now = datetime.now(UTC)
    grace = timedelta(days=cfg["named_backup_days"])
    runs = [p for p in (catalog / ".refreshes").glob("*") if p.is_dir()]
    if (catalog / ".journal-expansion" / "previous").exists():
        runs.append(catalog / ".journal-expansion")
    editions, delete = [], []
    for run in runs:
        marker = edition_time(run)
        age = now - datetime.fromtimestamp(run.stat().st_mtime, UTC)
        if marker and marker[1] and (run / "previous").exists():
            stamp = (
                marker[0]
                or datetime.fromtimestamp((run / "previous").stat().st_mtime, UTC).isoformat()
            )
            editions.append((stamp, run))
        elif run.name == ".journal-expansion":
            stamp = datetime.fromtimestamp((run / "previous").stat().st_mtime, UTC).isoformat()
            editions.append((stamp, run))
        elif marker and not marker[1] and age > timedelta(days=1):
            delete.append((run, "failed run"))
        elif age > grace:
            delete.append((run, f"unmarked backup older than {grace.days} days"))
    editions.sort(reverse=True)
    # A newer HTML-only publication must not evict the last database recovery.
    full_recoveries = [
        (stamp, run) for stamp, run in editions if (run / "previous/catalog.sqlite").is_file()
    ]
    protected = {run for _, run in editions[:keep] + full_recoveries[:1]}
    for stamp, run in editions:
        if run in protected:
            continue
        targets = [run / "previous", run / "staged"] if run.name == ".journal-expansion" else [run]
        delete += [(t, f"older edition ({stamp[:19]})") for t in targets if t.exists()]
    plan = [{"path": str(p), "reason": why, "bytes": du_bytes(p)} for p, why in delete]
    report = {
        "apply": args.apply,
        "keep": keep,
        "kept": [{"path": str(r), "published": s} for s, r in editions if r in protected],
        "delete": plan,
        "estimated_bytes": sum(p["bytes"] for p in plan),
    }
    if args.apply:
        free_before = shutil.disk_usage(catalog).free
        report["deleted"], report["failed"] = [], []
        for path, _ in delete:
            try:
                if path.is_symlink() or not path.resolve().is_relative_to(catalog.resolve()):
                    raise ValueError("refusing a pruning target outside the catalog")
                shutil.rmtree(path)
                if path.exists():
                    raise OSError("deletion did not remove the target")
                report["deleted"].append(str(path))
            except (OSError, ValueError) as error:
                report["failed"].append({"path": str(path), "error": str(error)})
        report["freed_bytes"] = sum(
            item["bytes"] for item in plan if item["path"] in report["deleted"]
        )
        report["filesystem_free_delta"] = shutil.disk_usage(catalog).free - free_before
        db = catalog / "catalog.sqlite"
        if db.exists():
            con = sqlite3.connect(db)
            pages, free_pages = (
                con.execute("PRAGMA page_count").fetchone()[0],
                con.execute("PRAGMA freelist_count").fetchone()[0],
            )
            con.execute("PRAGMA optimize")
            report["sqlite"] = {
                "freelist_ratio": round(free_pages / max(pages, 1), 4),
                "optimized": True,
                "vacuumed": False,
            }
            if (
                free_pages / max(pages, 1) > 0.10
                and shutil.disk_usage(catalog).free > 2 * db.stat().st_size
            ):
                con.execute("VACUUM")
                report["sqlite"]["vacuumed"] = True
            con.close()
    report["gb"] = {
        k: round(report.get(k, 0) / 2**30, 2) for k in ("estimated_bytes", "freed_bytes")
    }
    out(report)


# html-audit ------------------------------------------------------------------------------------


def validation_status(value):
    statuses, errors = [], []

    def visit(obj):
        if isinstance(obj, dict):
            if isinstance(obj.get("status"), str):
                statuses.append(obj["status"].lower())
            if obj.get("errors_count", 0) or obj.get("errors"):
                errors.append(True)
            if obj.get("sqlite_integrity") == "ok":
                statuses.append("passed")
            for child in obj.values():
                visit(child)
        elif isinstance(obj, list):
            for child in obj:
                visit(child)

    visit(value)
    if errors or any(s in ("failed", "error", "fail") for s in statuses):
        return "failed"
    return "passed" if any(s in ("passed", "success", "ok") for s in statuses) else "unknown"


def node_runtime():
    """Resolve a Node with the actual APIs used by the offline verifier."""
    candidates = [shutil.which("node")]
    candidates += [
        str(p)
        for p in sorted((Path.home() / ".nvm/versions/node").glob("*/bin/node"), reverse=True)
    ]
    candidates += [
        str(Path.home() / ".local/bin/node"),
        "/opt/homebrew/bin/node",
        "/usr/local/bin/node",
    ]
    for binary in dict.fromkeys(candidates):
        if not binary or not os.access(binary, os.X_OK):
            continue
        try:
            probe = subprocess.run(
                [
                    binary,
                    "-e",
                    "process.exit(['Blob','Response','DecompressionStream','atob'].every(k => typeof globalThis[k] !== 'undefined') ? 0 : 1)",
                ],
                capture_output=True,
                timeout=10,
            )
            if probe.returncode == 0:
                return binary
        except (OSError, subprocess.TimeoutExpired):
            continue
    return None


def cmd_html_audit(args, cfg):
    catalog = catalog_dir()
    if not catalog.exists():
        out({"catalog": False})
        return
    pages = {p.name: p.stat().st_size for p in catalog.glob("*.html")}
    referenced, missing_files = set(), set()
    for page in catalog.glob("*.html"):
        text = page.read_text("utf-8", errors="ignore")
        referenced |= set(re.findall(r"(catalog-assets-[0-9a-f]+)", text))
        for target in re.findall(r"(?:src|href)=[\"'](catalog-assets-[^\"'#?]+)", text):
            if not (catalog / target).exists():
                missing_files.add(target)
    asset_dirs = {p.name: du_bytes(p) for p in catalog.glob("catalog-assets-*") if p.is_dir()}
    largest = []
    for name in referenced & set(asset_dirs):
        files = sorted(
            (p for p in (catalog / name).rglob("*") if p.is_file()),
            key=lambda p: p.stat().st_size,
            reverse=True,
        )
        largest += [
            {"file": str(f.relative_to(catalog)), "bytes": f.stat().st_size} for f in files[:10]
        ]
    package = catalog_paths.ASSETS.parent
    sources = [
        catalog_paths.ASSETS / n
        for n in ("browser-template.html", "catalog-ui.js", "catalog.css", "offline-runtime.js")
    ]
    sources += [package / n for n in ("discovery.py", "build_browser.py")]
    newest_source = max((p.stat().st_mtime for p in sources if p.exists()), default=0)
    entrypoints = [
        catalog / n
        for n in (
            "catalog.html",
            "search.html",
            "authors.html",
            "institutions.html",
            "explore.html",
        )
    ]
    stale = [p.name for p in entrypoints if p.exists() and p.stat().st_mtime < newest_source]
    validations = {}
    for path in catalog.glob("*validation.json"):
        try:
            value = json.loads(path.read_text())
            checked = value.get("validated_at") or value.get("checked_at")
            timestamp = (
                datetime.fromisoformat(checked.replace("Z", "+00:00")).timestamp()
                if checked
                else path.stat().st_mtime
            )
            validations[path.name] = {
                "status": validation_status(value),
                "checked_at": checked,
                "age_days": round((time.time() - timestamp) / 86400, 2),
                "stale": time.time() - timestamp > cfg.get("html_max_age_days", 8) * 86400,
                "edition": value.get("edition_id") or value.get("edition"),
            }
        except (ValueError, TypeError, AttributeError) as error:
            validations[path.name] = {"status": "invalid", "error": str(error)}
    verification = None
    if getattr(args, "verify", False):
        node = node_runtime()
        if not node:
            raise ValueError(
                "offline verification needs Node with Blob, Response and DecompressionStream"
            )
        env = {
            **os.environ,
            "CAIRN_CATALOG_DIR": str(catalog),
            "PATH": str(Path(node).parent) + os.pathsep + os.environ.get("PATH", ""),
        }
        result = subprocess.run(
            [sys.executable, "-m", "cairn_catalog", "verify"],
            cwd=catalog,
            capture_output=True,
            text=True,
            env=env,
            timeout=cfg.get("html_verify_timeout_seconds", 600),
        )
        verification = {
            "status": "passed" if result.returncode == 0 else "failed",
            "returncode": result.returncode,
            "node": node,
            "output": (result.stdout + result.stderr)[-2000:],
        }
    out(
        {
            "pages": pages,
            "asset_dirs": asset_dirs,
            "referenced_assets": sorted(referenced),
            "missing_asset_dirs": sorted(referenced - set(asset_dirs)),
            "missing_asset_files": sorted(missing_files),
            "unreferenced_asset_dirs": sorted(set(asset_dirs) - referenced),
            "largest_asset_files": largest,
            "stale_entrypoints": stale,
            "preview_images": [
                {
                    "file": p.name,
                    "stale": p.stat().st_mtime
                    < max((x.stat().st_mtime for x in entrypoints if x.exists()), default=0),
                }
                for p in catalog.glob("*preview*.*")
            ],
            "validation_files": validations,
            "verification": verification,
        }
    )


# metrics ---------------------------------------------------------------------------------------


def proposal_stats(cfg) -> dict:
    stats = {"accepted": 0, "open": 0, "applied": 0, "rejected": 0, "attempted": 0, "failed": 0}
    for note in reports.reports(cfg, "weekly").values():
        stats["accepted"] += len(re.findall(r"^\s*- \[x\]", note.body, re.M | re.I))
        stats["open"] += len(re.findall(r"^\s*- \[ \]", note.body, re.M))
        stats["applied"] += len(re.findall(r"^\s*- \[x\] ✅", note.body, re.M | re.I))
        stats["rejected"] += len(re.findall(r"^\s*- \[-\]", note.body, re.M))
    return stats


def cmd_metrics(args, cfg):
    kb = kb_open(cfg)
    notes = kb.notes()
    real = {s: n for s, n in notes.items() if not reports.is_legacy_report(n)}
    inbound: dict[str, int] = {}
    for note in real.values():
        for slug in {*note.topics, *note.body_links}:
            inbound[slug] = inbound.get(slug, 0) + 1
    links = sum(len(set(n.topics + n.body_links)) for n in real.values())
    row = {
        "at": datetime.now().isoformat(timespec="seconds"),
        "papers": sum(n.kind == "paper" for n in real.values()),
        "topics": sum(n.kind == "topic" for n in real.values()),
        "notes": sum(n.kind == "note" for n in real.values()),
        "links_per_note": round(links / max(len(real), 1), 2),
        "orphans": sum(
            1
            for n in real.values()
            if not n.topics and not n.body_links and not inbound.get(n.slug)
        ),
        "broken_links": sum(
            1 for n in real.values() for s in n.topics + n.body_links if s not in notes
        ),
        "forbidden_refs": sum(len(forbidden_refs(n)) for n in real.values()),
        "proposals": proposal_stats(cfg),
    }
    actions = read_json(state_dir(cfg) / "actions.json", {})
    row["proposals"]["attempted"] = len(actions)
    row["proposals"]["failed"] = sum(a.get("status") == "failed" for a in actions.values())
    path = state_dir(cfg) / "metrics.jsonl"
    history = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
    if not args.dry_run:
        with path.open("a") as handle:
            handle.write(json.dumps(row) + "\n")
    week_ago = (datetime.now() - timedelta(days=7)).isoformat()
    baseline = next((h for h in reversed(history) if h["at"] <= week_ago), None)
    out({"current": row, "week_ago": baseline})


# apply -----------------------------------------------------------------------------------------

ACTION = re.compile(r"^(\s*)- \[[xX]\] (?!✅)(.*?)<!--\s*action:\s*(\{.*\})\s*-->\s*$")


def add_related(kb, slug: str, target: str, reason: str):
    notes = kb.notes()
    note = kb.resolve(slug, notes)
    other = kb.resolve(target, notes)
    if note is None or other is None:
        raise ValueError(f"unknown note {slug if note is None else target}")
    if other.slug in note.body_links:
        return "already linked"
    line = f"- [[{other.slug}]] — {reason}".rstrip(" —")
    body = note.body.rstrip()
    body = (
        re.sub(
            r"(^## Related\n(?:.*\n?)*?)(?=^## |\Z)",
            lambda m: m.group(1).rstrip() + "\n" + line + "\n\n",
            body + "\n",
            count=1,
            flags=re.M,
        )
        if re.search(r"^## Related$", body, re.M)
        else body + "\n\n## Related\n" + line
    )
    save_note(kb, note, body)
    return f"linked {note.slug} -> {other.slug}"


def validate_action(kb, action):
    if not isinstance(action, dict):
        raise ValueError("action must be an object")
    op = action.get("op")
    required = {
        "link": ("from", "to"),
        "retag": ("note", "add"),
        "topic": ("title", "body"),
        "paper": ("title",),
    }
    if op not in required:
        return "manual"
    for field in required[op]:
        if not action.get(field):
            raise ValueError(f"{op} requires {field}")
    for field in ("from", "to", "note"):
        if field in action and kb.resolve(action[field]) is None:
            raise ValueError(f"unknown note: {action[field]}")
    for field in ("add", "topics", "broader", "aliases"):
        if field in action and (
            not isinstance(action[field], list)
            or not all(isinstance(x, str) and x for x in action[field])
        ):
            raise ValueError(f"{field} must be a list of names")
    if op == "paper" and not (action.get("doi") or action.get("source") or action.get("url")):
        raise ValueError("paper requires an identifier or URL")
    if op == "topic":
        existing = kb.resolve(action["title"])
        if existing and existing.kind != "topic":
            raise ValueError("topic title is already used by a non-topic note")
        for seed in action.get("seeds", []):
            if validate_action(kb, {**seed, "op": "paper"}) != "executable":
                raise ValueError("invalid seed")
    return "executable"


def action_id(action):
    return hashlib.sha256(json.dumps(action, sort_keys=True).encode()).hexdigest()[:24]


def run_action(kb, cfg, action: dict) -> str:
    """Journal each step; retries reconcile actual state instead of trusting a success flag."""
    if validate_action(kb, action) != "executable":
        raise ValueError("manual action requires the agent")
    path = state_dir(cfg) / "actions.json"
    ledger = read_json(path, {})
    ident = action_id(action)
    ledger[ident] = {"status": "attempted", "action": action, "at": now(cfg).isoformat()}
    atomic_json(path, ledger)
    try:
        result = perform_action(kb, cfg, action)
    except Exception as error:
        ledger = read_json(path, {})
        ledger[ident].update(status="failed", error=str(error))
        atomic_json(path, ledger)
        raise
    ledger = read_json(path, {})
    ledger[ident].update(status="applied", result=result)
    atomic_json(path, ledger)
    return result


def perform_action(kb, cfg, action):
    op = action["op"]
    if op == "link":
        result = add_related(kb, action["from"], action["to"], action.get("reason", ""))
        if action.get("both"):
            # A backlink explains its direction without asserting an invented inverse.
            reverse = action.get("reverse_reason") or (
                "References this note: " + action.get("reason", "related source")
            )
            add_related(kb, action["to"], action["from"], reverse)
        return result
    if op == "topic":
        existing = kb.resolve(action["title"])
        if existing:
            slug = existing.slug
            topics = list(dict.fromkeys(existing.topics + action.get("broader", [])))
            if topics != existing.topics:
                save_note(kb, existing, existing.body, topics=topics)
        else:
            slug = kb.save(
                kind="topic",
                title=action["title"],
                body=action["body"],
                topics=action.get("broader", []),
                aliases=action.get("aliases"),
            )["slug"]
        done = [f"topic ready: {slug}"]
        for seed in action.get("seeds", []):
            done.append(run_action(kb, cfg, {**seed, "op": "paper", "topics": [slug]}))
        return "; ".join(done)
    if op == "retag":
        note = kb.resolve(action["note"])
        topics = list(dict.fromkeys(note.topics + action["add"]))
        if topics != note.topics:
            save_note(kb, note, note.body, topics=topics)
        return f"retagged {note.slug}"
    if op == "paper":
        source = (
            ("doi:" + action["doi"])
            if action.get("doi")
            else action.get("source") or action.get("url")
        )
        source = cairn().normalize_source(source)
        existing = next(
            (n for n in kb.notes().values() if n.kind == "paper" and source in note_ids(n)), None
        )
        if existing:
            topics = list(dict.fromkeys(existing.topics + action.get("topics", [])))
            if topics != existing.topics:
                save_note(kb, existing, existing.body, topics=topics)
            return f"paper ready: {existing.slug}"
        if action.get("doi") and (catalog_dir() / "catalog.sqlite").exists():
            env = {
                **os.environ,
                "CAIRN_WORKSPACE": str(workspace(cfg)),
                "CAIRN_COLLECTION": cfg["collection"],
            }
            proc = subprocess.run(
                [sys.executable, "-m", "cairn_catalog", "import-paper", action["doi"]],
                capture_output=True,
                text=True,
                env=env,
            )
            if proc.returncode == 0:
                slug = json.loads(proc.stdout.strip().splitlines()[-1])["slug"]
                note = kb.resolve(slug)
                if note is None:
                    raise ValueError("catalog importer wrote outside the configured collection")
                if action.get("topics"):
                    save_note(
                        kb,
                        note,
                        note.body,
                        topics=list(dict.fromkeys(note.topics + action["topics"])),
                    )
                return f"imported {slug} from the catalog"
        url = action.get("url") or paper_url({"source": source})
        body = (
            f"# {action['title']}\n\nProposed by kb-gardener on {now(cfg).date().isoformat()}. Not yet read.\n\n"
            f"{action.get('why', '')}\n\nPaper: [{source}]({url})"
        )
        fields = {
            "source": source,
            "url": url,
            "authors": action.get("authors"),
            "year": action.get("year"),
            "status": "to-read",
        }
        saved = kb.save(
            kind="paper",
            title=action["title"],
            body=body,
            topics=action.get("topics"),
            fields=fields,
        )
        return f"created paper note {saved['slug']}"
    raise ValueError("unknown action")


def approved_lines(body):
    fenced = False
    for line in body.splitlines():
        if line.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
        if not fenced and re.match(r"^\s*- \[[xX]\] (?!✅)", line):
            yield line


def cmd_apply(args, cfg):
    """Run ticked proposals of the weekly reports (or of one named report)."""
    kb = kb_open(cfg)
    if args.note:
        found = reports.find(cfg, args.note)
        names = [reports.ident(cfg, found)] if found else []
    else:
        names = sorted(reports.reports(cfg, "weekly"))
    applied, planned, manual, invalid = [], [], [], []
    for rid in names:
        initial = reports.get(cfg, rid)
        if initial is None:
            continue
        for line in approved_lines(initial.body):
            entry = {"report": rid, "item": line[:200]}
            match = ACTION.match(line)
            if not match:
                manual.append({**entry, "result": "needs agent: no executable action"})
                continue
            try:
                action = json.loads(match.group(3))
                if validate_action(kb, action) == "manual":
                    manual.append({**entry, "result": "needs agent: manual action"})
                    continue
                current = reports.get(cfg, rid)
                if current.body.splitlines().count(line) != 1:
                    raise ValueError("approval changed or is ambiguous; re-review required")
                if args.dry_run:
                    planned.append({**entry, "action": action, "result": "validated; no writes"})
                    continue
                result = run_action(kb, cfg, action)
                # Merge just this status into the current body, with its matching revision.
                for attempt in range(3):
                    current = reports.get(cfg, rid)
                    lines = current.body.splitlines()
                    if lines.count(line) != 1:
                        raise ValueError(
                            "approval changed during application; effects journaled, checklist not overwritten"
                        )
                    replacement = f"{match.group(1)}- [x] ✅ {match.group(2).rstrip()} _(applied {now(cfg).date().isoformat()}: {result})_"
                    lines[lines.index(line)] = replacement
                    try:
                        reports.save(cfg, rid, "\n".join(lines), {}, revision=current.revision)
                        break
                    except cairn().CairnError:
                        if attempt == 2:
                            raise
                applied.append({**entry, "result": result, "action_id": action_id(action)})
            except Exception as error:
                invalid.append({**entry, "result": f"needs agent: {error}"})
    out(
        {
            "applied": applied,
            "planned": planned,
            "needs_agent": manual + invalid,
            "invalid": invalid,
            "dry_run": args.dry_run,
        }
    )


# archive-digests -------------------------------------------------------------------------------


def cmd_archive_digests(args, cfg):
    """Move daily digests older than N days to the reports' archive/daily/ folder.

    A digest that a note or another report links to stays where it is, so links keep working.
    """
    cutoff = (date.today() - timedelta(days=cfg["digest_days_kept"])).isoformat()
    notes = kb_open(cfg).notes()
    moved, retained = [], []
    for rid, note in reports.reports(cfg, "daily").items():
        match = re.match(r"garden-digest-(\d{4}-\d{2}-\d{2})", note.slug)
        if not match or match.group(1) >= cutoff:
            continue
        if reports.referenced(cfg, note, notes):
            retained.append(rid)
            continue
        target = "archive/" + rid
        moved.append({"from": rid, "to": target})
        if args.dry_run:
            continue
        with engine_lock(cfg, "reports"):
            fresh = reports.get(cfg, rid)
            if fresh is None or fresh.revision != note.revision:
                raise ValueError("digest changed during archiving")
            destination = reports.path_of(cfg, target)
            if destination.exists() and destination.read_bytes() != note.path.read_bytes():
                raise ValueError("different archived revision already exists")
            destination.parent.mkdir(parents=True, exist_ok=True)
            note.path.replace(destination)
        reports.relink_index(cfg, rid, target)
    out(
        {
            "cutoff": cutoff,
            "archived": moved,
            "retained_referenced": retained,
            "dry_run": args.dry_run,
        }
    )


# history (git) ---------------------------------------------------------------------------------


def git(cfg, *argv, check=True):
    git_dir = HOME / "history" / (workspace(cfg).name + ".git")
    base = ["git", f"--git-dir={git_dir}", f"--work-tree={workspace(cfg)}"]
    if not git_dir.exists():
        git_dir.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", "--bare", "-q", str(git_dir)], check=True)
        subprocess.run([*base, "config", "core.bare", "false"], check=True)
        subprocess.run([*base, "config", "user.name", "kb-gardener"], check=True)
        subprocess.run([*base, "config", "user.email", "kb-gardener@localhost"], check=True)
    return subprocess.run([*base, *argv], capture_output=True, text=True, check=check)


def cmd_commit(args, cfg):
    """Record note changes in a private history kept outside the workspace.

    The repository lives in the gardener's state folder, so the workspace holds notes only.
    """
    store = cairn()
    paths = [
        f"{c}/{f}"
        for c in store.COLLECTIONS
        for f in store.FOLDERS.values()
        if (workspace(cfg) / c / f).exists()
    ]
    if reports.root(cfg).exists():
        paths.append(reports.root(cfg).relative_to(workspace(cfg)).as_posix())
    git(cfg, "add", "-A", "--", *paths)
    if not git(cfg, "diff", "--cached", "--quiet", check=False).returncode:
        out({"committed": False, "reason": "no note changes"})
        return
    git(cfg, "commit", "-q", "-m", args.message)
    head = git(cfg, "log", "-1", "--stat", "--format=%h %s").stdout
    out({"committed": True, "commit": head.strip()})


# state / config --------------------------------------------------------------------------------


def cmd_mark(args, cfg):
    raise ValueError(
        "Completion requires a saved, verified report; use `cairn-garden daily` or `weekly`"
    )


def cmd_config(args, cfg):
    if args.key:
        value = cfg.get(args.key)
        print(value if not isinstance(value, (list, dict)) else json.dumps(value))
    else:
        out({**cfg, "config_file": str(CONFIG_FILE), "state": load_state(cfg)})


def main(argv=None):
    parser = argparse.ArgumentParser(prog="cairn-garden", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("lint")
    p = sub.add_parser("fix-links")
    p.add_argument("--dry-run", action="store_true")
    p = sub.add_parser("new-papers")
    p.add_argument("--since")
    p.add_argument("--limit", type=int)
    p.add_argument(
        "--record", action="store_true", help="remember these candidates so later runs skip them"
    )
    sub.add_parser("zotero-gaps")
    p = sub.add_parser("zotero-sync")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--limit", type=int)
    p = sub.add_parser("snapshot")
    p.add_argument("--days", type=int, default=7)
    p.add_argument("--include-garden", action="store_true")
    p = sub.add_parser("verify")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--doi")
    g.add_argument("--arxiv")
    g.add_argument("--title")
    p = sub.add_parser("storage")
    p.add_argument("--keep", type=int)
    p.add_argument("--apply", action="store_true")
    p = sub.add_parser("html-audit")
    p.add_argument("--verify", action="store_true")
    p = sub.add_parser("metrics")
    p.add_argument("--dry-run", action="store_true")
    p = sub.add_parser("apply")
    p.add_argument("note", nargs="?")
    p.add_argument("--dry-run", action="store_true")
    p = sub.add_parser("archive-digests")
    p.add_argument("--dry-run", action="store_true")
    p = sub.add_parser("commit")
    p.add_argument("-m", "--message", required=True)
    p = sub.add_parser("mark")
    p.add_argument("what", choices=["digest", "weekly"])
    p = sub.add_parser("config")
    p.add_argument("key", nargs="?")
    args = parser.parse_args(argv)
    cfg = config()
    handler = globals()["cmd_" + args.cmd.replace("-", "_")]
    try:
        with engine_lock(cfg):
            handler(args, cfg)
    except Exception as error:  # Report as JSON so an agent can read and act on the failure.
        out({"error": type(error).__name__, "message": str(error)})
        sys.exit(1)


if __name__ == "__main__":
    main()
