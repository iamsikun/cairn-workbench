#!/usr/bin/env python3
"""Incrementally refresh public metadata, validate a staged build, then publish it."""

from __future__ import annotations

import fcntl
import gzip
import json
import os
import re
import shutil
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from . import build_browser, catalog, entities, paths, personalize, verify_offline

ROOT = paths.data_dir()
CROSSREF_FIELDS = "DOI,title,author,abstract,volume,issue,page,article-number,ISSN,container-title,published,published-print,published-online,issued,URL,resource,publisher,type,created,indexed,update-to,relation,license"
OPENALEX_FIELDS = "id,doi,title,publication_year,publication_date,authorships,biblio,abstract_inverted_index,primary_location,type,ids,is_retracted"


def raw_items(payload, service):
    return (
        payload["response"]["message"]["items"]
        if service == "crossref"
        else payload["response"]["results"]
    )


def cache_version(root):
    """Detect another metadata writer before replacing its live source cache."""
    return {
        str(p.relative_to(root)): (p.stat().st_size, p.stat().st_mtime_ns)
        for p in (root / "raw").rglob("*")
        if p.is_file()
    }


def read_cache(folder, service):
    state = json.loads((folder / "state.json").read_text())
    if not state.get("complete") and not (
        state.get("usable_checkpoint") and state.get("incomplete_reason")
    ):
        raise RuntimeError(f"Incomplete baseline: {folder}")
    records, timestamps = {}, {}
    key = "DOI" if service == "crossref" else "id"
    for n in range(1, state["pages"] + 1):
        with gzip.open(folder / f"page-{n:05d}.json.gz", "rt", encoding="utf-8") as handle:
            payload = json.load(handle)
        for item in raw_items(payload, service):
            identity = item[key]
            records[identity] = item
            timestamps[identity] = payload.get("record_retrieved_at", {}).get(
                identity, payload["retrieved_at"]
            )
    return records, timestamps, state


def upsert(records, timestamps, items, service, retrieved_at):
    added = changed = 0
    key = "DOI" if service == "crossref" else "id"
    for item in items:
        identity = item[key]
        if identity not in records:
            added += 1
        elif records[identity] == item:
            continue
        else:
            changed += 1
        # Replace the provider record, including corrected or removed fields.
        records[identity] = item
        timestamps[identity] = retrieved_at
    return added, changed


def refresh_service(service, root, lower, upper, recent_since, client=None):
    client = client or catalog.Client(1.0 if service == "crossref" else 0.5)
    reports = []
    for journal in catalog.JOURNALS:
        folder = root / "raw" / service / journal["id"]
        baseline_path = folder / "state.json"
        baseline = json.loads(baseline_path.read_text()) if baseline_path.exists() else {}
        if not baseline.get("complete"):
            # Resume incomplete historical supplements before doing a recent refresh.
            # A provider budget failure leaves an explicit, usable checkpoint.
            before = read_cache(folder, service)[0] if baseline.get("usable_checkpoint") else {}
            catalog.harvest_service(
                service, only=[journal["id"]], root=root, journals=[journal], client=client
            )
            state = json.loads(baseline_path.read_text())
            if not state.get("complete"):
                state.update(
                    usable_checkpoint=True,
                    incomplete_reason=state.get("error")
                    or "Historical provider traversal is incomplete.",
                )
                catalog.atomic_json(baseline_path, state)
            after = read_cache(folder, service)[0]
            report = {
                "provider": service,
                "journal": journal["id"],
                "fetched": state.get("retrieved", 0) - baseline.get("retrieved", 0),
                "added": len(after.keys() - before.keys()),
                "changed": sum(after[k] != before[k] for k in after.keys() & before.keys()),
                "cached": len(after),
                "historical_backfill_complete": state.get("complete", False),
            }
            if not state.get("complete"):
                report["warning"] = state["incomplete_reason"]
            reports.append(report)
            print(json.dumps(report), flush=True)
            continue
        records, timestamps, state = read_cache(folder, service)
        if service == "crossref":
            params = {
                "filter": ",".join(
                    [
                        *("issn:" + i for i in journal["issns"]),
                        "from-index-date:" + lower,
                        "until-index-date:" + upper,
                    ]
                ),
                "rows": 1000,
                "select": CROSSREF_FIELDS,
            }
            cursor_key, size = "next-cursor", 1000
        else:
            profile = json.loads((folder / "journal.json").read_text())
            source_ids = journal.get("openalex_source_ids") or [profile["id"].rsplit("/", 1)[-1]]
            source_ids = [str(s).rsplit("/", 1)[-1] for s in source_ids]
            params = {
                "filter": "primary_location.source.id:"
                + "|".join(source_ids)
                + ",from_publication_date:"
                + recent_since,
                "per-page": 200,
                "select": OPENALEX_FIELDS,
            }
            # Updated-date filters require OpenAlex premium; this uses public metadata.
            api_key = os.environ.get("OPENALEX_API_KEY")
            if api_key:
                params["api_key"] = api_key
            cursor_key, size = "next_cursor", 200
        url = (
            "https://api.crossref.org/works"
            if service == "crossref"
            else "https://api.openalex.org/works"
        )
        cursor, visited_pages, added, changed, fetched = "*", set(), 0, 0, 0
        while cursor:
            response = client.get(url, {**params, "cursor": cursor}).json()
            meta = response["message"] if service == "crossref" else response["meta"]
            items = meta["items"] if service == "crossref" else response["results"]
            identities = tuple(item["DOI" if service == "crossref" else "id"] for item in items)
            if identities and identities in visited_pages:
                raise RuntimeError(f"Repeated result page: {service}/{journal['id']}")
            visited_pages.add(identities)
            a, c = upsert(records, timestamps, items, service, catalog.now())
            added += a
            changed += c
            fetched += len(items)
            cursor = meta.get(cursor_key)
            if len(items) < size:
                break
        # Compact the accumulated cache. Record-level retrieval dates remain intact.
        values = list(records.values())
        stored_params = {k: v for k, v in params.items() if k != "api_key"}
        pages = max(1, (len(values) + 999) // 1000)
        for n in range(pages):
            chunk = values[n * 1000 : (n + 1) * 1000]
            response = (
                {"message": {"items": chunk, "total-results": len(values)}}
                if service == "crossref"
                else {"results": chunk, "meta": {"count": len(values)}}
            )
            payload = {
                "source": service,
                "journal_id": journal["id"],
                "retrieved_at": catalog.now(),
                "record_retrieved_at": {
                    item["DOI" if service == "crossref" else "id"]: timestamps[
                        item["DOI" if service == "crossref" else "id"]
                    ]
                    for item in chunk
                },
                "request": {"url": url, "params": stored_params},
                "response": response,
            }
            dest = folder / f"page-{n + 1:05d}.json.gz"
            with gzip.open(dest.with_suffix(".tmp"), "wt", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False)
            dest.with_suffix(".tmp").replace(dest)
        for path in folder.glob("page-*.json.gz"):
            if int(path.name[5:10]) > pages:
                path.unlink()  # Staged generated cache pages only.
        catalog.atomic_json(
            folder / "state.json",
            {
                **state,
                "pages": pages,
                "retrieved": len(values),
                "source_total": len(values),
                "source_total_kind": "accumulated_cache_records",
                "complete": True,
                "cursor": None,
                "updated_at": catalog.now(),
                "refresh_mode": "indexed_changes"
                if service == "crossref"
                else "recent_publications",
                "last_filter": stored_params["filter"],
            },
        )
        report = {
            "provider": service,
            "journal": journal["id"],
            "fetched": fetched,
            "added": added,
            "changed": changed,
            "cached": len(values),
        }
        reports.append(report)
        print(json.dumps(report), flush=True)
    return reports


@contextmanager
def build_at(root, as_of):
    previous = catalog.ROOT, catalog.AS_OF, catalog.JOURNALS, entities.ROOT
    catalog.ROOT, catalog.AS_OF, entities.ROOT = root, as_of, root
    catalog.JOURNALS = paths.journals(root)
    try:
        yield
    finally:
        catalog.ROOT, catalog.AS_OF, catalog.JOURNALS, entities.ROOT = previous


def publish(stage, root, backup):
    """Recoverable replacements; restore the previous edition if any move fails."""
    backup.mkdir(parents=True, exist_ok=True)
    # Immutable asset directories publish first. HTML entrypoints publish last;
    # older directories remain available to already-open offline pages.
    paths = sorted(
        stage.iterdir(), key=lambda p: (p.suffix == ".html", p.name == "catalog.html", p.name)
    )
    moved = []
    try:
        for path in paths:
            live, old = root / path.name, backup / path.name
            moved.append((live, old, path, live.exists()))
            if live.exists():
                live.replace(old)
            path.replace(live)
    except BaseException:
        for live, old, path, had_previous in reversed(moved):
            if live.exists() and not path.exists():
                live.replace(path)
            if had_previous and old.exists():
                old.replace(live)
        raise


def recover_pending(root):
    """Undo an interrupted publication before another refresh touches the live files."""
    pending = root / "update-pending.json"
    if not pending.exists():
        return
    info = json.loads(pending.read_text())
    stage, backup = Path(info["stage"]), Path(info["backup"])
    for name in reversed(info["names"]):
        live, old, staged = root / name, backup / name, stage / name
        if old.exists():
            if live.exists() and not staged.exists():
                live.replace(staged)
            old.replace(live)
        elif name not in info["existing"] and live.exists() and not staged.exists():
            live.replace(staged)
    pending.unlink()


def sync_entrypoints(root):
    """Update only the marked metadata block in the two active Cairn entrypoints."""
    _, parse = catalog.cairn_imports()
    kb = catalog.open_kb()
    coverage = json.loads((root / "coverage.json").read_text())
    graph = json.loads((root / "entity-coverage.json").read_text())
    if os.environ.get("GITHUB_ACTIONS") == "true":
        run_url = (
            f"{os.environ['GITHUB_SERVER_URL']}/{os.environ['GITHUB_REPOSITORY']}"
            f"/actions/runs/{os.environ['GITHUB_RUN_ID']}"
        )
        links = f"[Cloud catalog refresh and diagnostics]({run_url})\n"
    else:
        links = (
            f"[Open the saved local catalog]({root / 'catalog.html'}) · "
            f"[Refresh result]({root / 'update-report.json'})\n"
        )
    block = (
        "<!-- catalog-refresh:start -->\n"
        f"Latest catalog snapshot: **{coverage['as_of']}**. "
        f"**{coverage['total_entries']:,} entries · {coverage['total_issues']:,} issues · {coverage['total_abstracts']:,} source abstracts.** "
        f"{graph['identified_author_entities']:,} source-identified authors; {graph['identified_institutions']:,} identified institutions.\n\n"
        f"{links}"
        "<!-- catalog-refresh:end -->"
    )
    for slug in ["journal-catalog", "author-institution-catalog"]:
        path = kb.dir / "notes" / (slug + ".md")
        if not path.exists():
            continue
        note = parse(path)
        pattern = r"<!-- catalog-refresh:start -->[\s\S]*?<!-- catalog-refresh:end -->"
        body = (
            re.sub(pattern, lambda _: block, note.body)
            if re.search(pattern, note.body)
            else note.body.split("\n", 1)[0] + "\n\n" + block + "\n" + note.body.split("\n", 1)[1]
        )
        if body != note.body:
            fields = {
                k: v
                for k, v in note.meta.items()
                if k not in {"title", "kind", "topics", "aliases", "created", "updated"}
            }
            kb.save(
                kind=note.kind,
                title=note.title,
                body=body,
                topics=note.topics,
                aliases=note.aliases,
                fields=fields,
                revision=note.revision,
            )


def refresh(root=ROOT, rebuild_only=False):
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    with (root / "update.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("Another catalog refresh is already running") from None
        recover_pending(root)
        run = root / ".refreshes" / datetime.now(UTC).strftime("%Y%m%dT%H%M%S-%fZ")
        stage = run / "staged"
        stage.mkdir(parents=True)
        live_cache_version = cache_version(root)
        if (root / "raw").exists():
            shutil.copytree(root / "raw", stage / "raw")
        # Atomic note replacement means unchanged files may share storage safely.
        if (root / "cairn-library").exists():
            shutil.copytree(root / "cairn-library", stage / "cairn-library", copy_function=os.link)
        catalog.atomic_json(stage / "journals.json", paths.journals(root))
        today = datetime.now(ZoneInfo("America/Chicago")).date()
        upper = datetime.now(UTC).date().isoformat()
        state_file = root / "update-state.json"
        state = json.loads(state_file.read_text()) if state_file.exists() else {}
        coverage_file = root / "coverage.json"
        previous = json.loads(coverage_file.read_text()) if coverage_file.exists() else {}
        baseline = state.get("crossref_until", previous.get("as_of", today.isoformat()))
        lower = (date.fromisoformat(baseline) - timedelta(days=14)).isoformat()
        recent = entities.shift_months(today, -24).isoformat()
        report = {
            "started_at": catalog.now(),
            "as_of": today.isoformat(),
            "mode": "rebuild_cached" if rebuild_only else "incremental" if previous else "initial",
            "crossref_from": lower,
            "crossref_until": upper,
            "openalex_publication_since": recent,
            "run_directory": str(run),
            "sources": [],
            "warnings": [],
        }
        try:
            if not rebuild_only:
                with ThreadPoolExecutor(max_workers=2) as pool:
                    futures = [
                        pool.submit(refresh_service, service, stage, lower, upper, recent)
                        for service in ["crossref", "openalex"]
                    ]
                    for future in futures:
                        report["sources"].extend(future.result())
                report["warnings"].extend(
                    s["journal"] + ": " + s["warning"]
                    for s in report["sources"]
                    if s.get("warning")
                )
                # One archive's outage is a warning, as for Crossref, OpenAlex and AEA: it must not
                # discard everything else this refresh harvested.
                if any(j["id"] == "jmlr" for j in catalog.JOURNALS):
                    from .publisher_archives import harvest_jmlr

                    try:
                        harvest_jmlr(stage)
                    except Exception as exc:
                        report["warnings"].append(
                            "JMLR archive unavailable; previous records retained: " + str(exc)
                        )
                with build_at(stage, today.isoformat()):
                    try:
                        catalog.harvest_repec(SimpleNamespace(refresh=True))
                    except Exception as exc:
                        report["warnings"].append(
                            "RePEc unavailable; previous records retained: " + str(exc)
                        )
                    try:
                        catalog.harvest_publisher(SimpleNamespace())
                    except Exception as exc:
                        report["warnings"].append(
                            "AEA issue index unavailable; previous index retained: " + str(exc)
                        )
            with build_at(stage, today.isoformat()):
                catalog.build(SimpleNamespace())
                catalog.validate(SimpleNamespace())
            browser = build_browser.build(stage, source_root=root)
            verified_queries = verify_offline.verify(stage)
            report["offline_verification"] = (
                f"passed; network disabled; {verified_queries} SQLite parity queries"
            )
            report["browser"] = browser
            try:
                # Personal settings are optional; a bad preferences file must not block the refresh.
                report["personalization"] = personalize.run(stage)
            except Exception as exc:
                report["warnings"].append("Personalization skipped: " + str(exc))
            coverage = json.loads((stage / "coverage.json").read_text())
            report["journal_membership"] = coverage["journal_membership"]
            report["entry_change"] = coverage["total_entries"] - previous.get("total_entries", 0)
            report["added_source_records"] = sum(s["added"] for s in report["sources"])
            report["changed_source_records"] = sum(s["changed"] for s in report["sources"])
            backup = run / "previous"
            if cache_version(root) != live_cache_version:
                raise RuntimeError(
                    "The live source cache changed during this staged refresh. The previous edition and checkpoint were preserved; rebuild again to include the newer metadata."
                )
            catalog.atomic_json(
                root / "update-pending.json",
                {
                    "stage": str(stage),
                    "backup": str(backup),
                    "names": [p.name for p in stage.iterdir()],
                    "existing": [p.name for p in stage.iterdir() if (root / p.name).exists()],
                },
            )
            publish(stage, root, backup)
            (root / "update-pending.json").unlink()
            # The published entrypoints reference only the new asset edition.
            report["pruned_assets"] = build_browser.prune_assets(root, browser["assets"])
            if not rebuild_only:
                catalog.atomic_json(
                    state_file,
                    {
                        "last_success_at": catalog.now(),
                        "crossref_until": upper,
                        "snapshot_date": today.isoformat(),
                        "run_directory": str(run),
                    },
                )
            report.update(
                status="success", completed_at=catalog.now(), backup_directory=str(backup)
            )
            if root == ROOT.resolve():
                try:
                    sync_entrypoints(root)
                except Exception as exc:
                    report["warnings"].append("Entry point status update failed: " + str(exc))
        except BaseException as exc:
            report.update(
                status="failed", completed_at=catalog.now(), error=f"{type(exc).__name__}: {exc}"
            )
            catalog.atomic_json(root / "update-report.json", report)
            catalog.atomic_json(run / "report.json", report)
            raise
        catalog.atomic_json(root / "update-report.json", report)
        catalog.atomic_json(run / "report.json", report)
        print(json.dumps(report, indent=2), flush=True)
        return report
