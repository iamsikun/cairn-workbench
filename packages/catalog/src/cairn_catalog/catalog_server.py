#!/usr/bin/env python3
"""Serve a paginated catalog backed by read-only SQLite queries on localhost."""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import threading
import webbrowser
from contextlib import closing
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import discovery, entities, insights, paths, personalize, preferences, publication_status

ROOT = paths.data_dir()
SAVING = threading.Lock()
PERSONAL_CACHE = {}  # the twelve-month window, kept between saves


def warm_preferences():
    """Refresh catalog-personal.js at start-up and keep its window, so the first save is quick."""
    try:
        with SAVING:
            personalize.run(ROOT, cache=PERSONAL_CACHE)
    except Exception as exc:  # the catalog still works; saving reports its own errors
        print(f"Preferences not refreshed: {exc}", flush=True)


def save_preferences(change):
    """Apply one change from a page to the preferences file and regenerate catalog-personal.js."""
    with SAVING:
        path = personalize.PREFERENCES
        prefs = personalize.load_preferences(path)
        topics = personalize.cairn_topics()
        preferences.save(path, preferences.apply(prefs, change, topics))
        keep = {}
        report = personalize.run(ROOT, path, topics, keep=keep, cache=PERSONAL_CACHE)
        return {"personal": keep["personal"], "warnings": report["warnings"]}


def integer(value, default=0, maximum=200):
    return max(0, min(int(value or default), maximum))


def papers_query(
    con,
    query="",
    journal="",
    year="",
    issue="",
    limit=30,
    offset=0,
    start_date=None,
    end_date=None,
    basis="issue",
    include_uncertain=False,
    stage="",
    entry_type="",
):
    if basis == "first":
        return discovery.first_date_query(
            con,
            query,
            journal,
            year,
            issue,
            limit,
            offset,
            start_date,
            end_date,
            include_uncertain,
            stage,
            entry_type,
        )
    if basis not in ["issue", "online", "print"]:
        raise ValueError("Invalid date basis")
    where, params = [], []
    stage_where = publication_status.where(stage)
    if stage_where:
        where.append(stage_where)
    events = bool(start_date or end_date or basis != "issue")
    join = " LEFT JOIN publication_events ev ON ev.paper_id=p.id AND ev.basis=?" if events else ""
    leading = [basis] if events else []
    if start_date or end_date:
        lo, hi, _ = entities.period_bounds(start_date=start_date, end_date=end_date)
        where.append(
            "ev.date_lower<=? AND ev.date_upper>=?"
            if include_uncertain
            else "ev.date_lower>=? AND ev.date_upper<=?"
        )
        params.extend([hi, lo] if include_uncertain else [lo, hi])
    if query.strip():
        normalized_doi = re.sub(
            r"^(?:https?://(?:dx\.)?doi.org/|doi:\s*)", "", query.strip(), flags=re.I
        ).lower()
        words = re.findall(r"[^\W_]+", query, flags=re.UNICODE)
        if not words:
            return {"total": 0, "items": []}
        if re.match(r"^10\.\d{4,9}/", normalized_doi):
            where.append("p.id IN (SELECT paper_id FROM paper_dois WHERE doi=?)")
            params.append(normalized_doi)
        else:
            where.append("p.id IN (SELECT paper_id FROM paper_search WHERE paper_search MATCH ?)")
            params.append(" AND ".join('"' + w + '"' for w in words))
    for field, value in [
        ("journal_id", journal),
        ("year", year),
        ("issue_id", issue),
        ("entry_type", entry_type),
    ]:
        if value:
            where.append("p." + field + "=?")
            params.append(value)
    suffix = " WHERE " + " AND ".join(where) if where else ""
    total = con.execute(
        "SELECT COUNT(*) FROM papers p" + join + suffix, [*leading, *params]
    ).fetchone()[0]
    date_select = (
        "ev.date AS publication_date,ev.precision AS date_precision,ev.date_lower,ev.date_upper"
        if events
        else "p.date AS publication_date,p.date_precision"
    )
    selected = (
        "SELECT p.id,p.title,"
        + date_select
        + ",p.doi,p.journal_id,p.authors_json,p.volume,p.issue,json_extract(p.record_json,'$.volume_series') AS volume_series,json_extract(p.record_json,'$.publication_unit') AS publication_unit,json_extract(p.record_json,'$.article_number') AS article_number,p.pages,p.entry_type,p.publication_status,p.publication_status_evidence,p.abstract IS NOT NULL AS has_abstract FROM papers p"
        + join
        + suffix
        + " ORDER BY publication_date DESC,p.title,p.id LIMIT ? OFFSET ?"
    )
    rows = con.execute(
        "SELECT p.*,j.title AS journal FROM ("
        + selected
        + ") p JOIN journals j ON j.id=p.journal_id ORDER BY p.publication_date DESC,p.title,p.id",
        [*leading, *params, limit, offset],
    )
    items = []
    for row in rows:
        item = dict(row)
        item["authors"] = json.loads(item.pop("authors_json"))
        if start_date or end_date:
            item["period_membership"] = (
                "certain" if item["date_lower"] >= lo and item["date_upper"] <= hi else "uncertain"
            )
        item.pop("date_lower", None)
        item.pop("date_upper", None)
        items.append(item)
    entities.add_author_links(con, items)
    return {"total": total, "items": items}


INSIGHTS = {}  # computed once per server process


def api(path, args):
    get = lambda key, default="": args.get(key, [default])[0]
    if get("version"):
        report = json.loads((ROOT / "browser-build.json").read_text())
        if get("version") != report.get("version"):
            raise ValueError("The catalog was refreshed. Reload this page to use the new edition.")
    limit, offset = integer(get("limit"), 30), integer(get("offset"), 0, 1000000)
    with closing(entities.connect(True)) as con:
        if path == "/api/recent":
            if not get("start_date") or not get("end_date"):
                raise ValueError("Choose both dates for What’s New.")
            return discovery.recent_query(
                con,
                get("start_date"),
                get("end_date"),
                limit,
                offset,
                get("group_by"),
                get("journal_offsets"),
                get("field"),
                get("seen"),
                get("new_only"),
            )
        if path == "/api/insights":
            if "insights" not in INSIGHTS:
                INSIGHTS["insights"] = insights.build(con)
            return INSIGHTS["insights"]
        if path == "/api/meta":
            registry = discovery.journal_fields()
            return {
                "journals": [
                    {
                        **dict(r),
                        "field": registry[r["id"]]["field"],
                        "group": registry[r["id"]]["group"],
                    }
                    for r in con.execute(
                        "SELECT id,title,abbreviation FROM journals ORDER BY title"
                    )
                ],
                "fields": discovery.fields(),
                "years": [
                    r[0]
                    for r in con.execute(
                        "SELECT DISTINCT year FROM papers WHERE year IS NOT NULL ORDER BY year DESC"
                    )
                ],
                "papers": con.execute("SELECT COUNT(*) FROM papers").fetchone()[0],
                "issues": con.execute("SELECT COUNT(*) FROM issues").fetchone()[0],
                "entities": json.loads((ROOT / "entity-coverage.json").read_text()),
                "last_quarter": entities.period_bounds()[2],
                "snapshot_date": json.loads((ROOT / "coverage.json").read_text()).get(
                    "as_of", "unknown"
                ),
            }
        if path == "/api/entities":
            return entities.entity_search(get("kind", "author"), get("query"), limit, offset, con)
        if path == "/api/publications":
            return entities.publication_query(
                get("kind", "author"),
                get("entity"),
                get("period", "last-quarter"),
                get("basis", "issue"),
                get("as_of") or None,
                get("include_uncertain") == "1",
                limit,
                offset,
                con,
                get("start_date") or None,
                get("end_date") or None,
                get("stage"),
            )
        if path == "/api/papers":
            return papers_query(
                con,
                get("query"),
                get("journal"),
                get("year"),
                get("issue"),
                limit,
                offset,
                get("start_date") or None,
                get("end_date") or None,
                get("basis", "issue"),
                get("include_uncertain") == "1",
                get("stage"),
                get("entry_type"),
            )
        if path == "/api/issues":
            where, params = [], []
            for field in ["journal_id", "year"]:
                value = get("journal" if field == "journal_id" else field)
                if value:
                    where.append(field + "=?")
                    params.append(value)
            suffix = " WHERE " + " AND ".join(where) if where else ""
            return {
                "items": [
                    dict(r)
                    for r in con.execute(
                        "SELECT id,journal_id,volume,issue,year,date,json_extract(record_json,'$.date_precision') AS date_precision,json_extract(record_json,'$.volume_series') AS volume_series,json_extract(record_json,'$.publication_unit') AS publication_unit,entry_count FROM issues"
                        + suffix
                        + " ORDER BY date DESC,volume DESC,issue LIMIT 1000",
                        params,
                    )
                ]
            }
        if path == "/api/paper":
            row = con.execute("SELECT record_json FROM papers WHERE id=?", (get("id"),)).fetchone()
            if not row:
                raise LookupError("Paper not found")
            record = json.loads(row[0])
            record["author_entities"] = [
                dict(r)
                for r in con.execute(
                    "SELECT a.position,a.observed_name,a.author_id,e.identity_status FROM authorships a JOIN author_entities e ON e.id=a.author_id WHERE a.paper_id=? ORDER BY a.position",
                    (record["id"],),
                )
            ]
            record["institution_entities"] = [
                dict(r)
                for r in con.execute(
                    "SELECT DISTINCT i.id,i.display_name,i.identity_status FROM affiliations a JOIN institution_entities i ON i.id=a.institution_id WHERE a.paper_id=? ORDER BY i.display_name",
                    (record["id"],),
                )
            ]
            return record
    raise LookupError("Unknown endpoint")


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def do_GET(self):
        request = urlparse(self.path)
        if request.path == "/":
            self.send_response(302)
            self.send_header("Location", "/catalog.html")
            self.end_headers()
            return
        if request.path.startswith("/api/"):
            status = 200
            try:
                result = api(request.path, parse_qs(request.query))
            except ValueError as exc:
                status, result = 400, {"error": str(exc)}
            except LookupError as exc:
                status, result = 404, {"error": str(exc)}
            except sqlite3.Error:
                status, result = (
                    500,
                    {
                        "error": "The catalog database is unavailable; rebuild the indexes and retry."
                    },
                )
            data = json.dumps(result, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(data)
            return
        super().do_GET()

    def do_POST(self):
        # Only pages served by this app may save, so other sites cannot change preferences.
        port = self.server.server_address[1]
        origin = self.headers.get("Origin")
        if urlparse(self.path).path != "/api/preferences":
            self.send_error(404)
            return
        status = 200
        try:
            if (
                origin not in (f"http://127.0.0.1:{port}", f"http://localhost:{port}")
                or self.headers.get("Content-Type", "").split(";")[0] != "application/json"
            ):
                status, result = (
                    403,
                    {"error": "Preferences can only be changed from the catalog pages."},
                )
            else:
                length = int(self.headers.get("Content-Length") or 0)
                if not 0 < length <= 65536:
                    raise ValueError("Invalid request")
                result = save_preferences(json.loads(self.rfile.read(length)))
        except (ValueError, json.JSONDecodeError) as exc:
            status, result = 400, {"error": str(exc)}
        except LookupError as exc:
            status, result = 404, {"error": str(exc)}
        except (OSError, sqlite3.Error) as exc:
            status, result = 500, {"error": f"Could not save preferences: {exc}"}
        data = json.dumps(result, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def end_headers(self):
        # Preferences change while the app runs; never reuse a stale catalog-personal.js.
        if urlparse(self.path).path.endswith("catalog-personal.js"):
            self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def list_directory(self, path):
        self.send_error(404, "Choose a catalog file")
        return None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--open", action="store_true", help="open the catalog in the browser")
    args = parser.parse_args(argv)
    url = f"http://127.0.0.1:{args.port}/catalog.html"
    # Local only. Endpoints never mutate the database or Cairn notes; POST /api/preferences edits the preferences file.
    try:
        server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    except OSError:
        if not args.open:
            raise
        webbrowser.open(url)  # the app is already running
        return
    print(f"Catalog: {url}", flush=True)
    threading.Thread(target=warm_preferences, daemon=True).start()
    if args.open:
        webbrowser.open(url)
    server.serve_forever()
