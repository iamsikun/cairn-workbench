"""Publication chronology shared by the recent feed and browser exports."""

import json

from . import entities, paths

FEED_KEYS = {
    "id",
    "title",
    "authors",
    "author_count",
    "author_entities",
    "journal",
    "journal_id",
    "publication_date",
    "date_precision",
    "publication_status",
    "publication_status_evidence",
    "volume",
    "volume_series",
    "publication_unit",
    "issue",
    "article_number",
    "entry_type",
    "period_membership",
    "first_source",
    "first_lower",
    "first_upper",
    "first_seen",
    "issue_id",
}


def fields():
    """Ordered disciplines; each journal belongs to exactly one."""
    return json.loads((paths.ASSETS / "fields.json").read_text(encoding="utf-8"))


def journal_fields():
    return {j["id"]: j for j in paths.journals(paths.data_dir())}


def parse_seen(seen):
    """Per-field "last caught up" snapshot dates from the reader's browser."""
    try:
        seen = json.loads(seen or "{}")
    except (ValueError, TypeError) as error:
        raise ValueError("Invalid seen dates") from error
    if not isinstance(seen, dict) or any(type(v) is not str or len(v) != 10 for v in seen.values()):
        raise ValueError("Invalid seen dates")
    return seen


def is_new(paper, field, seen):
    return field in seen and (paper.get("first_seen") or "") > seen[field]


def issue_summaries(rows):
    """Issues represented in the window, newest first."""
    issues = {}
    for p in rows:
        if p.get("publication_status") != "issue_assigned" or not p.get("issue_id"):
            continue
        entry = issues.setdefault(
            p["issue_id"],
            dict(
                issue_id=p["issue_id"],
                journal_id=p["journal_id"],
                volume=p.get("volume"),
                issue=p.get("issue"),
                volume_series=p.get("volume_series"),
                total=0,
                date="",
            ),
        )
        entry["total"] += 1
        entry["date"] = max(entry["date"], p.get("first_date") or "")
    return sorted(
        sorted(issues.values(), key=lambda i: i["issue_id"]), key=lambda i: i["date"], reverse=True
    )


def first_publication(record):
    """Bound the earliest known event without inventing date components."""
    events = []
    for value, precision, source in [
        (record.get("published_online"), None, "crossref:published-online"),
        (record.get("published_print"), None, "crossref:published-print"),
        (
            record.get("date"),
            record.get("date_precision"),
            record.get("field_sources", {}).get("date"),
        ),
    ]:
        bounds = entities.date_bounds(value, precision)
        if bounds:
            events.append((bounds[0], bounds[1], value, bounds[2], source))
    if not events:
        return dict(
            first_date=None,
            first_lower=None,
            first_upper=None,
            first_precision=None,
            first_source=None,
        )
    lower, upper = min(e[0] for e in events), min(e[1] for e in events)
    exact = next((e for e in events if e[:2] == (lower, upper)), None)
    value = exact[2] if exact else lower[:4]
    if exact and exact[3] == "provider_date_unverified":
        value = value[:4]
    return dict(
        first_date=value,
        first_lower=lower,
        first_upper=upper,
        first_precision=exact[3] if exact else "range",
        first_source=exact[4] if exact else "earliest recorded publication events",
    )


def journal_pages(rows, journals, offsets, seen=None, field_of=None):
    """Group the complete ordered feed, then page each journal independently."""
    seen, field_of = seen or {}, field_of or journal_fields()
    try:
        offsets = json.loads(offsets or "{}")
    except (ValueError, TypeError) as error:
        raise ValueError("Invalid journal offsets") from error
    if not isinstance(offsets, dict) or any(
        type(v) is not int or not 0 <= v <= 9007199254740991 for v in offsets.values()
    ):
        raise ValueError("Invalid journal offsets")
    grouped = {}
    for paper in rows:
        grouped.setdefault(paper["journal_id"], []).append(paper)
    result = []
    for journal in sorted(journals, key=lambda j: (j["title"], j["id"])):
        papers = grouped.get(journal["id"], [])
        if not papers:
            continue
        offset = min(offsets.get(journal["id"], 0) // 10, (len(papers) - 1) // 10) * 10
        info = field_of.get(journal["id"], {})
        field = info.get("field")
        result.append(
            dict(
                journal_id=journal["id"],
                journal=journal["title"],
                total=len(papers),
                offset=offset,
                items=papers[offset : offset + 10],
                field=field,
                abbreviation=info.get("abbreviation"),
                new_total=sum(is_new(p, field, seen) for p in papers),
                issues=issue_summaries(papers),
            )
        )
    return result


def field_overview(rows, seen, field_of):
    """One summary per discipline: counts, issues in the window and the newest headlines."""
    result = []
    for field in fields():
        papers = [p for p in rows if field_of[p["journal_id"]]["field"] == field["id"]]
        journals = {}
        for p in papers:
            j = journals.setdefault(
                p["journal_id"],
                dict(
                    journal_id=p["journal_id"],
                    journal=p["journal"],
                    abbreviation=field_of[p["journal_id"]]["abbreviation"],
                    total=0,
                    new_total=0,
                ),
            )
            j["total"] += 1
            j["new_total"] += is_new(p, field["id"], seen)
        result.append(
            dict(
                field=field["id"],
                label=field["label"],
                total=len(papers),
                new_total=sum(j["new_total"] for j in journals.values()),
                journals=sorted(
                    journals.values(), key=lambda j: (-j["total"], j["journal"], j["journal_id"])
                ),
                issues=issue_summaries(papers)[:8],
                items=papers[:5],
            )
        )
    return result


def recent_query(
    con,
    start_date,
    end_date,
    limit=30,
    offset=0,
    group_by="",
    journal_offsets="",
    field="",
    seen="",
    new_only="",
):
    if group_by not in ("", "date", "journal", "field"):
        raise ValueError("Invalid recent-publications grouping")
    field_of = journal_fields()
    if field and field not in {f["id"] for f in fields()}:
        raise ValueError("Unknown field")
    seen = parse_seen(seen)
    lower, upper, _ = entities.period_bounds(start_date=start_date, end_date=end_date)
    candidates = con.execute(
        """
        SELECT p.record_json FROM papers p JOIN (
            SELECT paper_id,MIN(date_lower) lo,MIN(date_upper) hi
            FROM publication_events GROUP BY paper_id
        ) e ON e.paper_id=p.id
        WHERE e.lo<=? AND e.hi>=? AND p.entry_type IN ('article','article_or_other')
    """,
        (upper, lower),
    )
    rows, uncertain = [], 0
    for row in candidates:
        p = json.loads(row[0])
        p.update(first_publication(p))
        if p["first_lower"] < lower or p["first_upper"] > upper:
            uncertain += 1
            continue
        p.update(
            publication_date=p["first_date"],
            date_precision=p["first_precision"],
            period_membership="certain",
        )
        rows.append(p)
    first_seen = (
        dict(con.execute("SELECT paper_id,first_seen FROM paper_first_seen"))
        if con.execute("SELECT 1 FROM sqlite_master WHERE name='paper_first_seen'").fetchone()
        else {}
    )
    for p in rows:
        p["first_seen"] = first_seen.get(p["id"])
    if field:
        rows = [p for p in rows if field_of[p["journal_id"]]["field"] == field]
    if new_only == "1":
        rows = [p for p in rows if is_new(p, field_of[p["journal_id"]]["field"], seen)]
    rows.sort(key=lambda p: (p["title"], p["id"]))
    rows.sort(key=lambda p: p["first_date"] or "", reverse=True)
    if group_by == "field":
        overview = field_overview(rows, seen, field_of)
        entities.add_author_links(con, [p for f in overview for p in f["items"]])
        summary = lambda p: {k: v for k, v in p.items() if k in FEED_KEYS}
        return {
            "total": len(rows),
            "uncertain_count": uncertain,
            "fields": [{**f, "items": [summary(p) for p in f["items"]]} for f in overview],
        }
    groups = (
        journal_pages(
            rows, con.execute("SELECT id,title FROM journals"), journal_offsets, seen, field_of
        )
        if group_by == "journal"
        else None
    )
    items = (
        [p for group in groups for p in group["items"]]
        if groups is not None
        else rows[offset : offset + limit]
    )
    entities.add_author_links(con, items)
    summary = lambda p: {k: v for k, v in p.items() if k in FEED_KEYS}
    result = {"total": len(rows), "uncertain_count": uncertain}
    if groups is not None:
        result["groups"] = [{**g, "items": [summary(p) for p in g["items"]]} for g in groups]
    else:
        result["items"] = [summary(p) for p in items]
    return result


def first_date_query(
    con,
    query="",
    journal="",
    year="",
    issue="",
    limit=30,
    offset=0,
    start_date=None,
    end_date=None,
    include_uncertain=False,
    stage="",
    entry_type="",
):
    """Historical search using the same conservative earliest-publication bounds."""
    import re

    from . import publication_status

    lower, upper, _ = entities.period_bounds(start_date=start_date, end_date=end_date, period="all")
    clauses, params = [], []
    for field, value in [
        ("journal_id", journal),
        ("year", year),
        ("issue_id", issue),
        ("entry_type", entry_type),
    ]:
        if value:
            clauses.append("p." + field + "=?")
            params.append(value)
    if stage:
        condition = publication_status.where(stage)
        if condition:
            clauses.append(condition)
    if query.strip():
        doi = re.sub(
            r"^(?:https?://(?:dx\.)?doi.org/|doi:\s*)", "", query.strip(), flags=re.I
        ).lower()
        if re.match(r"^10\.\d{4,9}/", doi):
            clauses.append("p.id IN (SELECT paper_id FROM paper_dois WHERE doi=?)")
            params.append(doi)
        else:
            words = re.findall(r"[^\W_]+", query, flags=re.UNICODE)
            if not words:
                return {"total": 0, "items": []}
            clauses.append("p.id IN (SELECT paper_id FROM paper_search WHERE paper_search MATCH ?)")
            params.append(" AND ".join('"' + w + '"' for w in words))
    if start_date or end_date:
        clauses.append(
            "p.id IN (SELECT paper_id FROM publication_events GROUP BY paper_id HAVING MIN(date_lower)<=? AND MIN(date_upper)>=?)"
        )
        params.extend([upper, lower])
    sql = "SELECT record_json FROM papers p" + (
        " WHERE " + " AND ".join(clauses) if clauses else ""
    )
    rows = []
    for row in con.execute(sql, params):
        p = json.loads(row[0])
        p.update(first_publication(p))
        certain = True
        if start_date or end_date:
            if not p["first_lower"] or p["first_lower"] > upper or p["first_upper"] < lower:
                continue
            certain = p["first_lower"] >= lower and p["first_upper"] <= upper
            if not certain and not include_uncertain:
                continue
        p.update(
            publication_date=p["first_date"],
            date_precision=p["first_precision"],
            period_membership="certain" if certain else "uncertain",
        )
        rows.append(p)
    rows.sort(key=lambda p: (p["title"], p["id"]))
    rows.sort(key=lambda p: p["first_date"] or "", reverse=True)
    items = rows[offset : offset + limit]
    entities.add_author_links(con, items)
    allowed = {
        "id",
        "title",
        "authors",
        "author_count",
        "author_entities",
        "journal",
        "journal_id",
        "publication_date",
        "date_precision",
        "publication_status",
        "publication_status_evidence",
        "volume",
        "volume_series",
        "publication_unit",
        "issue",
        "article_number",
        "entry_type",
        "period_membership",
    }
    return {
        "total": len(rows),
        "items": [{k: v for k, v in p.items() if k in allowed} for p in items],
    }
