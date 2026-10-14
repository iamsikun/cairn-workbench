"""Garden reports: readable operational Markdown beside the research notes, not among them.

Layout (``[garden] reports``, default ``gardening``, relative to the workspace)::

    gardening/daily/garden-digest-YYYY-MM-DD.md     daily digests
    gardening/weekly/garden-weekly-YYYY-wWW.md      weekly reviews with proposals to tick
    gardening/maintenance/*.md                      maintenance and verification records
    gardening/archive/daily/*.md                    older digests nobody links to
    gardening/index.md                              generated log: one row per run

A report's id is its path inside the folder. Cairn's research search and topics never see
these files; links between reports and notes are relative Markdown links, so they work on
GitHub and in Obsidian alike.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from . import engine as g

FOLDERS = ("daily", "weekly", "maintenance", "archive")
INDEX = "index.md"
LEGACY_SLUG = re.compile(r"garden-(?:digest-\d{4}-\d{2}-\d{2}|weekly-\d{4}-w\d{2})(?:-\d+)?")
LEGACY_TITLE = re.compile(r"Garden (?:digest \d{4}-\d{2}-\d{2}|weekly \d{4}-W\d{2})", re.I)
# Code, fenced blocks and HTML comments (which hold action JSON) keep their wikilinks verbatim.
PROTECTED = re.compile(r"```.*?```|~~~.*?~~~|<!--.*?-->|`[^`\n]*`", re.S)
ROW = re.compile(r"^\|.*\| `([^`]+)` \|$", re.M)
CHECK = re.compile(r"^- \*\*(\w+)\*\*: (.*) <!-- check -->$", re.M)


def root(cfg) -> Path:
    name = Path(cfg.get("reports") or "gardening")
    store = g.cairn()
    if (
        name.is_absolute()
        or ".." in name.parts
        or not name.parts
        or name.parts[0] in store.COLLECTIONS
        or name.parts[0].startswith(".")
    ):
        raise ValueError("`reports` must be a folder inside the workspace, beside the collections")
    return g.workspace(cfg) / name


def title(mode: str, stamp) -> str:
    if mode == "daily":
        return "Garden digest " + stamp.date().isoformat()
    return "Garden weekly " + stamp.strftime("%G-W%V")


def period(mode: str, stamp) -> str:
    return stamp.date().isoformat() if mode == "daily" else stamp.strftime("%G-W%V")


def report_id(mode: str, stamp) -> str:
    return f"{mode}/{g.cairn().slugify(title(mode, stamp))}.md"


def path_of(cfg, rid: str) -> Path:
    path = (root(cfg) / rid).resolve()
    if not path.is_relative_to(root(cfg).resolve()) or path.suffix != ".md":
        raise ValueError(f"not a report id: {rid}")
    return path


def get(cfg, rid: str):
    path = path_of(cfg, rid)
    return g.cairn().parse(path) if path.is_file() else None


def ident(cfg, note) -> str:
    return note.path.resolve().relative_to(root(cfg).resolve()).as_posix()


def reports(cfg, folder: str | None = None) -> dict:
    """Every report by id (the index excluded), optionally inside one folder."""
    base = root(cfg)
    found = {}
    for path in sorted(base.rglob("*.md")) if base.is_dir() else []:
        rid = path.relative_to(base).as_posix()
        if rid == INDEX or rid.split("/")[0] not in FOLDERS:
            continue
        if folder is None or rid.startswith(folder + "/"):
            found[rid] = g.cairn().parse(path)
    return found


def find(cfg, name: str):
    """A report by id, slug or title."""
    if name.endswith(".md"):
        with_id = get(cfg, name)
        if with_id:
            return with_id
    slug = g.cairn().slugify(name.removesuffix(".md").rsplit("/", 1)[-1])
    for note in reports(cfg).values():
        if note.slug == slug or note.title.casefold() == name.casefold():
            return note
    return None


def save(cfg, rid: str, body: str, meta: dict, revision: str | None = None):
    """Create or update a report; an update needs the revision it was read at."""
    store = g.cairn()
    with g.engine_lock(cfg, "reports"):
        path = path_of(cfg, rid)
        current = store.parse(path) if path.exists() else None
        if current is not None and current.revision != revision:
            raise store.CairnError(f"{rid} changed meanwhile; read it again and merge")
        if current is None and revision is not None:
            raise store.CairnError(f"{rid} does not exist")
        today = g.now(cfg).date().isoformat()
        merged = {**(current.meta if current else {}), **meta}
        merged.setdefault("created", today)
        merged["updated"] = today
        store._write(path, store.dump(merged, body))
        return store.parse(path)


# Links ------------------------------------------------------------------------------------------


def relative(target: Path, source: Path) -> str:
    return Path(os.path.relpath(target, source.parent)).as_posix()


def portable(cfg, body: str, source: Path, notes=None, moved=None) -> str:
    """Rewrite [[slug]] links as relative Markdown links to the note or report they name.

    ``moved`` maps legacy report slugs to their report paths (used by the migration).
    """
    notes = g.kb_open(cfg).notes() if notes is None else notes
    moved = moved or {}
    store = g.cairn()

    def swap(match):
        slug = store.slugify(match.group(1))
        label = (match.group(2) or "").strip()
        if slug in moved:
            target, name = moved[slug]
        elif slug in notes:
            target, name = notes[slug].path, notes[slug].title
        else:
            return match.group(0)
        return f"[{label or name}]({relative(target, source)})"

    parts, position = [], 0
    for token in PROTECTED.finditer(body):
        parts.append(store.WIKILINK.sub(swap, body[position : token.start()]))
        parts.append(token.group(0))
        position = token.end()
    parts.append(store.WIKILINK.sub(swap, body[position:]))
    return "".join(parts)


def local_links(path: Path, body: str) -> list[tuple[str, Path]]:
    """Relative Markdown links to .md files, resolved against the file that holds them."""
    found = []
    for match in g.MD_LINK.finditer(body):
        target = match.group(2).strip("<>").split("#", 1)[0]
        if not target.endswith(".md") or re.match(r"^[a-z][a-z0-9+.-]*:", target, re.I):
            continue
        found.append((target, (path.parent / target).resolve()))
    return found


def is_legacy_report(note) -> bool:
    """A digest or weekly review saved as a research note by cairn-garden 0.6.0 or earlier."""
    return bool(
        note.kind == "note"
        and LEGACY_SLUG.fullmatch(note.slug)
        and LEGACY_TITLE.fullmatch(note.title)
    )


def legacy(notes) -> list[str]:
    return sorted(slug for slug, note in notes.items() if is_legacy_report(note))


def moves(cfg) -> dict:
    """Legacy slug -> report id, recorded by `cairn-garden migrate-reports`."""
    return g.read_json(g.state_dir(cfg) / "report-moves.json", {})


def locate(cfg, receipt: dict):
    """The live report a run receipt (report.json) refers to, wherever it lives now."""
    if receipt.get("id"):
        return get(cfg, receipt["id"])
    slug = receipt.get("slug")
    if not slug:
        return None
    if slug in moves(cfg):
        return get(cfg, moves(cfg)[slug])
    return g.kb_open(cfg).resolve(slug)


def referenced(cfg, note, notes=None) -> bool:
    """Whether a research note or another report links to this report."""
    notes = g.kb_open(cfg).notes() if notes is None else notes
    target = note.path.resolve()
    for other in [*notes.values(), *reports(cfg).values()]:
        if other.path.resolve() == target:
            continue
        if note.slug in other.body_links or any(
            p == target for _, p in local_links(other.path, other.body)
        ):
            return True
    return False


# Index ------------------------------------------------------------------------------------------

HEADER = """# Garden log

Generated by cairn-garden; edits are overwritten. One row per run, newest first. A run without a
report link did not deliver a report.
"""


def findings(manifest: dict) -> str:
    if manifest.get("status") in ("failed", "skipped"):
        return " ".join(str(manifest.get("error", "")).split())[:160]
    facts = manifest.get("findings", {})
    parts = [
        f"{facts.get('recommended', 0)} papers recommended",
        f"{facts.get('zotero_writes', 0)} Zotero changes",
    ]
    if manifest.get("mode") == "weekly":
        parts.append(f"{facts.get('applied', 0)} proposals applied")
        parts.append(f"{facts.get('open', 0)} proposals open")
    if manifest.get("warnings"):
        parts.append(f"{len(manifest['warnings'])} warnings: " + "; ".join(manifest["warnings"]))
    return ", ".join(parts)[:400]


def _cell(text) -> str:
    return " ".join(str(text).split()).replace("|", "\\|")


def _render(rows: dict, checks: dict) -> str:
    lines = [HEADER, "## Latest scheduled checks", ""]
    lines += [f"- **{mode}**: {checks[mode]} <!-- check -->" for mode in sorted(checks)] or [
        "- none yet"
    ]
    lines += [
        "",
        "## Runs",
        "",
        "| Date | Mode | Period | Outcome | Findings | Report | Run |",
        "|---|---|---|---|---|---|---|",
    ]
    lines += [rows[key] for key in sorted(rows, reverse=True)]
    return "\n".join(lines) + "\n"


def _update(cfg, change) -> None:
    store = g.cairn()
    with g.engine_lock(cfg, "reports"):
        path = root(cfg) / INDEX
        text = path.read_text("utf-8") if path.exists() else ""
        rows = {m.group(1): m.group(0) for m in ROW.finditer(text)}
        checks = {m.group(1): m.group(2) for m in CHECK.finditer(text)}
        change(rows, checks)
        new = _render(rows, checks)
        if new != text:
            store._write(path, new)


def record_run(cfg, manifest: dict) -> None:
    """Add or replace this run's row, so a run never appears twice."""
    run_id = manifest["id"]
    report = manifest.get("report_id") if manifest.get("status", "").startswith("success") else None
    link = f"[{Path(report).stem}]({report})" if report else "—"
    row = "| " + " | ".join(
        _cell(x)
        for x in (
            str(manifest.get("started_at", ""))[:16].replace("T", " "),
            manifest.get("mode", ""),
            manifest.get("period", ""),
            manifest.get("status", ""),
            findings(manifest),
        )
    )
    row += f" | {link} | `{run_id}` |"

    def change(rows, checks):
        rows[run_id] = row

    _update(cfg, change)


def record_check(cfg, mode: str, outcome: str) -> None:
    """The latest scheduled check that found nothing due; written only when it changes."""

    def change(rows, checks):
        checks[mode] = _cell(outcome)

    _update(cfg, change)


def relink_index(cfg, old: str, new: str) -> None:
    def change(rows, checks):
        for key, row in rows.items():
            rows[key] = row.replace(f"]({old})", f"]({new})")

    _update(cfg, change)
