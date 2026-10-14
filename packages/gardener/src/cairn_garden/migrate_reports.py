"""Move garden reports out of the research collection into the report folder.

`cairn-garden migrate-reports --dry-run` lists every file it would move or edit and writes
nothing. Without it, the whole plan is journaled before the first write; an interrupted
migration resumes when run again, and `--rollback JOURNAL` restores every file that has not
been edited since. A file edited after the migration is reported, never overwritten.

What moves: digests and weekly reviews that cairn-garden saved as research notes (matched by
slug and title, not by a `garden-` prefix alone), digests archived in the state folder, and
notes named with `--maintenance`. Report bodies keep their text, front matter, ticks and run
markers; their [[wikilinks]], and research notes' links to moved reports, become relative
Markdown links. Run receipts stay as they are; `report-moves.json` maps old slugs to reports.
"""

from __future__ import annotations

import base64
import contextlib
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path

from . import engine as g
from . import reports


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def _raw(step: dict, key: str) -> bytes:
    return base64.b64decode(step[key])


def _revision(path: Path) -> str | None:
    return g.cairn().revision(path.read_bytes()) if path.exists() else None


def _split(text: str) -> tuple[str, str]:
    """Front matter verbatim, and the body (the same split as cairn.store.parse)."""
    if text.startswith("---\n"):
        header, sep, rest = text[4:].partition("\n---\n")
        if sep:
            return "---\n" + header + "\n---\n", rest
    return "", text


def _rewritten(cfg, path: Path, target: Path, notes, moved) -> bytes:
    header, body = _split(path.read_text("utf-8"))
    return (header + reports.portable(cfg, body, target, notes, moved)).encode("utf-8")


def plan(cfg, maintenance=()) -> dict:
    kb = g.kb_open(cfg)
    notes = kb.notes()
    problems, items = [], []
    for slug in reports.legacy(notes):
        folder = "daily" if slug.startswith("garden-digest-") else "weekly"
        items.append((notes[slug].path, f"{folder}/{slug}.md", notes[slug].title))
    for name in maintenance:
        note = kb.resolve(name)
        if note is None:
            problems.append(f"no research note named {name!r}")
        elif not reports.is_legacy_report(note):
            items.append((note.path, f"maintenance/{note.slug}.md", note.title))
    for path in sorted((g.state_dir(cfg) / "archive").glob("*.md")):
        items.append((path, f"archive/daily/{path.name}", g.cairn().parse(path).title))
    moved = {Path(src).stem: (reports.path_of(cfg, rid), title) for src, rid, title in items}
    remaining = {s: n for s, n in notes.items() if s not in moved}
    steps = []
    for src, rid, _ in items:
        target = reports.path_of(cfg, rid)
        before = src.read_bytes()
        after = _rewritten(cfg, src, target, remaining, moved)
        if target.exists() and target.read_bytes() != after:
            problems.append(f"{target} already exists with different content")
        steps.append(
            {
                "op": "move",
                "from": str(src),
                "to": rid,
                "slug": src.stem,
                "before": _b64(before),
                "before_rev": g.cairn().revision(before),
                "after": _b64(after),
                "after_rev": g.cairn().revision(after),
            }
        )
    for note in remaining.values():
        if not set(note.body_links) & set(moved):
            continue
        before = note.path.read_bytes()
        after = _rewritten(cfg, note.path, note.path, {}, moved)
        steps.append(
            {
                "op": "rewrite",
                "path": str(note.path),
                "before": _b64(before),
                "before_rev": g.cairn().revision(before),
                "after": _b64(after),
                "after_rev": g.cairn().revision(after),
            }
        )
    return {"steps": steps, "problems": problems}


def preview(cfg, maintenance=()) -> dict:
    """The plan without file contents: what would move where, and which notes get new links."""
    proposal = plan(cfg, maintenance)
    return {
        "dry_run": True,
        "reports": str(reports.root(cfg)),
        "moves": [
            {"from": s["from"], "to": s["to"]} for s in proposal["steps"] if s["op"] == "move"
        ],
        "relinked_notes": [s["path"] for s in proposal["steps"] if s["op"] == "rewrite"],
        "problems": proposal["problems"],
    }


def _create(path: Path, data: bytes) -> None:
    """Atomic and exclusive: never replaces a file that appeared meanwhile."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".md")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(tmp, path)
    finally:
        os.unlink(tmp)


def _unlink(path: Path) -> None:
    path.unlink()


def perform(cfg, step: dict) -> None:
    """Idempotent, so an interrupted step can simply be performed again."""
    if step["op"] == "move":
        source, target = Path(step["from"]), reports.path_of(cfg, step["to"])
        if target.exists():
            if _revision(target) != step["after_rev"]:
                raise RuntimeError(f"{target} exists with different content")
        elif _revision(source) == step["before_rev"]:
            _create(target, _raw(step, "after"))
        else:
            raise RuntimeError(f"{source} changed after the plan; run the migration again")
        if source.exists():
            if _revision(source) != step["before_rev"]:
                raise RuntimeError(f"{source} changed during the migration; it was kept")
            _unlink(source)
    else:
        path = Path(step["path"])
        current = _revision(path)
        if current == step["before_rev"]:
            g.cairn()._write(path, _raw(step, "after").decode("utf-8"))
        elif current != step["after_rev"]:
            raise RuntimeError(f"{path} changed after the plan; run the migration again")


def undo(cfg, step: dict) -> str | None:
    """Restore one step; returns a conflict instead of overwriting later edits."""
    if step["op"] == "move":
        source, target = Path(step["from"]), reports.path_of(cfg, step["to"])
        if not target.exists():
            return None
        if _revision(target) != step["after_rev"]:
            return f"{target} was edited after the migration; it stays in the report folder"
        if not source.exists():
            _create(source, _raw(step, "before"))
        elif _revision(source) != step["before_rev"]:
            return f"{source} exists with different content; {target} kept"
        target.unlink()
        return None
    path = Path(step["path"])
    current = _revision(path)
    if current == step["after_rev"]:
        g.cairn()._write(path, _raw(step, "before").decode("utf-8"))
    elif current not in (step["before_rev"], None):
        return f"{path} was edited after the migration; its links stay relative"
    return None


@contextlib.contextmanager
def quiet(cfg):
    """No workflow or engine command may run while files move."""
    with contextlib.ExitStack() as stack:
        try:
            stack.enter_context(g.engine_lock(cfg, "run", blocking=False))
            stack.enter_context(g.engine_lock(cfg, "engine", blocking=False))
        except BlockingIOError:
            raise RuntimeError("a garden workflow is running; try again when it ends") from None
        yield


def unfinished(cfg) -> Path | None:
    for path in sorted(g.HOME.glob("report-migration-*.json")):
        record = json.loads(path.read_text())
        if record.get("status") == "running" and record.get("workspace") == str(
            g.workspace(cfg).resolve()
        ):
            return path
    return None


def seed_index(cfg, moves: dict) -> int:
    """Index the existing run receipts; they themselves stay unchanged."""
    count = 0
    for path in sorted((g.state_dir(cfg) / "runs").glob("*/manifest.json")):
        manifest = g.read_json(path, {})
        if not manifest.get("id") or not manifest.get("mode"):
            continue
        view = dict(manifest)
        if view.get("report") in moves:
            view["report_id"] = moves[view["report"]]
        if not view.get("period") and view.get("started_at"):
            stamp = datetime.fromisoformat(view["started_at"])
            view["period"] = reports.period(view["mode"], stamp)
        reports.record_run(cfg, view)
        count += 1
    return count


def run(cfg, maintenance=()) -> dict:
    journal = unfinished(cfg)
    with quiet(cfg):
        if journal:
            record = json.loads(journal.read_text())
        else:
            proposal = plan(cfg, maintenance)
            if proposal["problems"]:
                return {"migrated": False, **preview(cfg, maintenance)}
            if not proposal["steps"]:
                return {"migrated": False, "steps": 0, "note": "nothing to migrate"}
            journal = g.HOME / f"report-migration-{datetime.now().strftime('%Y%m%dT%H%M%S')}.json"
            index = reports.root(cfg) / reports.INDEX
            record = {
                "workspace": str(g.workspace(cfg).resolve()),
                "reports": str(reports.root(cfg)),
                "status": "running",
                "steps": proposal["steps"],
                "done": 0,
                "moves_before": reports.moves(cfg),
                "index_before": _b64(index.read_bytes()) if index.exists() else None,
            }
            g.atomic_json(journal, record)
        with g.kb_open(cfg).lock():
            for step in record["steps"][record["done"] :]:
                perform(cfg, step)
                record["done"] += 1
                g.atomic_json(journal, record)
        moves = {
            **record["moves_before"],
            **{s["slug"]: s["to"] for s in record["steps"] if s["op"] == "move"},
        }
        g.atomic_json(g.state_dir(cfg) / "report-moves.json", moves)
        indexed = seed_index(cfg, moves)
        record["status"] = "complete"
        g.atomic_json(journal, record)
    return {
        "migrated": True,
        "journal": str(journal),
        "moved": sum(s["op"] == "move" for s in record["steps"]),
        "relinked_notes": sum(s["op"] == "rewrite" for s in record["steps"]),
        "indexed_runs": indexed,
        "next": ["cairn-garden lint", "cairn-garden daily", "cairn-garden weekly"],
    }


def rollback(cfg, journal: Path) -> dict:
    record = json.loads(Path(journal).read_text())
    conflicts = []
    with quiet(cfg), g.kb_open(cfg).lock():
        for step in reversed(record["steps"]):
            problem = undo(cfg, step)
            if problem:
                conflicts.append(problem)
        g.atomic_json(g.state_dir(cfg) / "report-moves.json", record["moves_before"])
        index = Path(record["reports"]) / reports.INDEX
        if record.get("index_before"):
            g.cairn()._write(index, _raw(record, "index_before").decode("utf-8"))
        else:
            index.unlink(missing_ok=True)
        for folder in sorted(Path(record["reports"]).rglob("*"), reverse=True):
            if folder.is_dir() and not any(folder.iterdir()):
                folder.rmdir()
        root = Path(record["reports"])
        if root.is_dir() and not any(root.iterdir()):
            root.rmdir()
        record["status"] = "rolled back" if not conflicts else "rolled back with conflicts"
        record["conflicts"] = conflicts
        g.atomic_json(Path(journal), record)
    return {"rolled_back": True, "journal": str(journal), "problems": conflicts}
