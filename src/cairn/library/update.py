"""Checkpointed weekly updates; baseline archives never trigger a bulk reading bill."""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Literal

from cairn.library import catalog, discovery, feed, reader, verification
from cairn.library.models import Paper, metadata
from cairn.library.store import commit_unlocked, entities_unlocked
from cairn.records.json import read_json
from cairn.records.models import canonical, digest, new_id, now
from cairn.storage.workspace import Workspace


def inventory(ws: Workspace, scope: str) -> dict[str, list[str]]:
    with ws.lock():
        return {
            record.id: sorted(
                {f.content_hash for f in paper.files if f.availability == "available"}
            )
            for record in entities_unlocked(ws, scope)
            if isinstance(paper := metadata(record), Paper)
        }


def update(
    ws: Workspace,
    *,
    device_id: str | None = None,
    scope: str = "research",
    page_budget: int = 100,
    read_budget: int = 10,
    fetch: discovery.Fetch | None = None,
) -> dict[str, Any]:
    import fcntl
    import os

    from cairn.errors import Blocked, Denied

    with ws.lock():
        if catalog.config_unlocked(ws).scope != scope:
            raise Denied("updates require the configured library scope")
    with ws.fs.parent("library-update.lock") as (fd, name):
        lock_fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600, dir_fd=fd)
    try:
        ws.fs._regular(os.fstat(lock_fd))
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise Blocked("library_update_already_running") from exc
        return _update(
            ws,
            device_id=device_id,
            scope=scope,
            page_budget=page_budget,
            read_budget=read_budget,
            fetch=fetch,
        )
    finally:
        os.close(lock_fd)


def _update(
    ws: Workspace,
    *,
    device_id: str | None = None,
    scope: str = "research",
    page_budget: int = 100,
    read_budget: int = 10,
    fetch: discovery.Fetch | None = None,
) -> dict[str, Any]:
    from cairn.errors import Denied

    if not 0 <= read_budget <= 100 or not 1 <= page_budget <= 1000:
        raise Denied("update budgets out of range")
    pointer = f"receipts/library/updates/{scope}.json"
    with ws.lock():
        state = read_json(ws.fs.read(pointer)) if ws.fs.exists(pointer) else None
    if state is None or state["phase"] == "done":
        before = inventory(ws, scope)
        state = {
            "id": new_id("update"),
            "phase": "scan",
            "before": before,
            "baseline": state is None,
            "issues": [],
            "events": [],
            "at": now().isoformat(),
        }
        with ws.lock(write=True):
            commit_unlocked(ws, {pointer: canonical(state)}, "begin_update")

    def checkpoint() -> None:
        with ws.lock(write=True):
            commit_unlocked(ws, {pointer: canonical(state)}, "update_checkpoint")

    if state["phase"] == "scan":
        report = catalog.scan(ws)
        state["issues"] += [
            f"Library scan: {issue}" for issue in sorted(set(report.issues.values()))
        ]
        state["phase"] = "discover"
        checkpoint()
    if state["phase"] == "discover":
        reports = discovery.discover(ws, page_budget=page_budget, fetch=fetch)
        state["issues"] += [
            f"Publication check {r.journal_id}: {r.issue or 'backfill incomplete'}"
            for r in reports
            if not r.complete
        ]
        state["phase"] = "events"
        checkpoint()
    if state["phase"] == "events":
        current = inventory(ws, scope)
        event_ids = []
        with ws.lock(write=True):
            outputs = {}
            for paper_id, hashes in current.items():
                record, paper = catalog.get_paper(ws, paper_id, scope)
                old = state["before"].get(paper_id)
                kind: (
                    Literal["box_addition", "box_revision", "new_publication", "newly_discovered"]
                    | None
                ) = None
                if hashes and hashes != old and not state["baseline"]:
                    kind = "box_addition" if not old else "box_revision"
                elif old is None and not hashes:
                    recent = bool(
                        paper.published
                        and len(paper.published) >= 10
                        and paper.published[:10] >= (now() - timedelta(days=14)).date().isoformat()
                    )
                    if recent:
                        kind = "new_publication"
                    elif not state["baseline"]:
                        kind = "newly_discovered"
                if kind:
                    event_id = "feed_" + digest(canonical([paper_id, kind, hashes]))[:32]
                    event = feed.FeedEvent(id=event_id, paper_id=paper_id, kind=kind, at=now())
                    path = f"receipts/library/feed_events/{event_id}.json"
                    if not ws.fs.exists(path):
                        outputs[path] = canonical(event)
                    event_ids.append(event_id)
            state["events"] = event_ids
            state["phase"] = "read"
            outputs[pointer] = canonical(state)
            commit_unlocked(ws, outputs, "update_events")
    with ws.lock():
        # Undelivered/pending readings survive missed weeks and read-budget limits.
        events = [
            feed.FeedEvent.model_validate_json(ws.fs.read(path))
            for path in ws.fs.files("receipts/library/feed_events")
        ]
        allowed = {r.id for r in entities_unlocked(ws, scope)}
        events = [event for event in events if event.paper_id in allowed]
    if state["phase"] == "read":
        budget = read_budget
        for event in events:
            if event.reading_requested or event.kind == "newly_discovered" or budget == 0:
                continue
            if device_id is None:
                state["issues"].append("Paper readings pending: no enrolled device selected")
                break
            try:
                reader.enqueue(ws, event.paper_id, device_id, scope=scope)
                event.reading_requested = True
                with ws.lock(write=True):
                    commit_unlocked(
                        ws,
                        {f"receipts/library/feed_events/{event.id}.json": canonical(event)},
                        "feed_read_queued",
                    )
                budget -= 1
            except Exception:
                state["issues"].append(
                    f"Reading pending for {event.paper_id}: source or device unavailable"
                )
        for job in reader.jobs(ws, scope):
            if read_budget == 0:
                break
            if job.status in ("queued", "blocked"):
                reader.run(ws, job.job.id)
                read_budget -= 1
        state["phase"] = "verify"
        checkpoint()
    if state["phase"] == "verify":
        verification.verify(ws, scope)
        state["phase"] = "feed"
        checkpoint()
    # Bound each digest while retaining all durable events. Old completed entries
    # remain in history; pending entries stay represented in subsequent snapshots.
    recent_events = sorted(events, key=lambda event: (event.at, event.id))[-500:]
    if len(events) > 500:
        state["issues"].append(
            f"Digest shows the latest 500 of {len(events)} saved events; "
            "use the catalog and feed history for earlier papers"
        )
    result = feed.save(ws, recent_events, sorted(set(state["issues"])), scope)
    state["phase"] = "done"
    checkpoint()
    return {
        "run": state["id"],
        "baseline": state["baseline"],
        "digest": result.id if result else None,
        "issues": sorted(set(state["issues"])),
        "notification_pending": bool(result and result.notification == "pending"),
    }
