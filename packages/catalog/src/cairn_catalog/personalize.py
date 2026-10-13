#!/usr/bin/env python3
"""Write catalog-personal.js: field tiers, "For you" matches and followed people/institutions.

Reads the catalog preferences and the Cairn topic notes, queries the catalog for the twelve
months up to the snapshot, and writes a small script beside the HTML entrypoints.
It lives outside the versioned asset folder, so editing preferences only needs this
script, not a catalog rebuild.
"""

import json
import re
import sqlite3
from collections import defaultdict
from contextlib import closing
from datetime import UTC, date, datetime
from pathlib import Path

import yaml

from . import discovery, entities, paths

ROOT = paths.data_dir()
PREFERENCES = paths.preferences_file()
OUTPUT = "catalog-personal.js"
TIERS = {"core": 1.0, "skim": 0.5, "mute": 0.0}
WEIGHTS = {"person": 3, "institution": 2, "keyword": 1, "topic": 1}
FOR_YOU_LIMIT = 300
BASES = ("issue", "online", "print")  # every publication_events basis
ROW_KEYS = [
    "id",
    "title",
    "authors",
    "author_count",
    "author_entities",
    "journal_id",
    "journal",
    "publication_date",
    "date_precision",
    "first_seen",
    "first_lower",
    "first_upper",
    "publication_status",
    "volume",
    "volume_series",
    "issue",
    "article_number",
    "issue_id",
    "entry_type",
]
FTS_SYNTAX = re.compile(r'["*()]|\b(?:AND|OR|NOT|NEAR)\b')


def load_preferences(path):
    prefs = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
    return prefs or {}


def topic_notes(directory):
    """Cairn topic notes: title, aliases and broader topics from YAML frontmatter."""
    topics = {}
    for path in sorted(Path(directory).glob("*.md")):
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---"):
            continue
        meta = yaml.safe_load(text.split("---", 2)[1]) or {}
        if meta.get("kind") != "topic":
            continue
        broader = [re.sub(r"^\[\[|\]\]$", "", str(t)) for t in meta.get("topics") or []]
        topics[path.stem] = dict(
            slug=path.stem,
            title=meta.get("title") or path.stem,
            aliases=[str(a) for a in meta.get("aliases") or []],
            broader=broader,
        )
    return topics


def phrase_query(text):
    """A phrase over titles and abstracts; the last word may carry a plural or other suffix."""
    text = str(text).strip()
    if FTS_SYNTAX.search(text):
        return "{title abstract} : (" + text + ")"
    words = re.findall(r"[^\W_]+", text, flags=re.UNICODE)
    if not words:
        return None
    last = words[-1]
    if len(last) > 4 and last.lower().endswith("s") and not last.lower().endswith("ss"):
        words[-1] = last[:-1]
    return '{title abstract} : "' + " ".join(words) + '"*'


def window_rows(con, start, end):
    """Papers whose earliest publication falls certainly inside the window, as in the home feed."""
    # Equivalent to MIN(date_lower)<=end AND MIN(date_upper)>=start per paper: some event overlaps the
    # window and none ends before it. Two covering-index range scans instead of aggregating every event.
    bases = ",".join(f"'{b}'" for b in BASES)
    overlapping = {
        r[0]
        for r in con.execute(
            f"SELECT paper_id FROM publication_events WHERE basis IN ({bases}) AND date_lower<=? AND date_upper>=?",
            (end, start),
        )
    }
    earlier = {
        r[0]
        for r in con.execute(
            f"SELECT paper_id FROM publication_events WHERE basis IN ({bases}) AND date_lower<? AND date_upper<?",
            (start, start),
        )
    }
    rows = {}
    for (record,) in con.execute(
        """SELECT p.record_json FROM json_each(?) c CROSS JOIN papers p ON p.id=c.value
                                    WHERE p.entry_type IN ('article','article_or_other')""",
        (json.dumps(sorted(overlapping - earlier)),),
    ):
        p = json.loads(record)
        p.update(discovery.first_publication(p))
        if p["first_lower"] < start or p["first_upper"] > end:
            continue
        p.update(publication_date=p["first_date"], date_precision=p["first_precision"])
        rows[p["id"]] = p
    return rows


def resolve(kind, entry, con, window):
    """Resolve one followed person or institution without silently pooling namesakes."""
    if isinstance(entry, str):
        entry = {"name": entry}
    label = (
        entry.get("label")
        or entry.get("name")
        or ", ".join(entry.get("ids") or [])
        or entry.get("id")
    )
    ids = list(entry.get("ids") or ([entry["id"]] if entry.get("id") else []))
    table, alias_table, field = (
        ("author_entities", "author_aliases", "author_id")
        if kind == "author"
        else ("institution_entities", "institution_aliases", "institution_id")
    )
    result = dict(
        label=label, name=entry.get("name"), status="resolved", ids=[], candidates=[], name_only=[]
    )
    if ids:
        for value in ids:
            try:
                result["ids"].append(entities.resolve_entity(kind, value, con)["id"])
            except ValueError:
                result.setdefault("missing_ids", []).append(value)
        if not result["ids"]:
            result["status"] = "not_found"
        return result
    name = entities.normalized_name(entry.get("name"))
    exact = [
        dict(r)
        for r in con.execute(
            f"SELECT e.* FROM {table} e WHERE e.id IN (SELECT {field} FROM {alias_table} WHERE normalized_name=?)",
            (name,),
        )
    ]
    identified = [
        e
        for e in exact
        if e["identity_status"] != ("unresolved_credit" if kind == "author" else "unresolved_label")
    ]
    unresolved = [e["id"] for e in exact if e not in identified]
    if len(identified) == 1:
        result["ids"] = [identified[0]["id"]]
    elif len(identified) > 1:
        result["status"] = "needs_choice"
        for e in sorted(identified, key=lambda e: (-e["publication_count"], e["id"])):
            link = "authorships" if kind == "author" else "affiliations"
            latest = con.execute(
                f"""SELECT j.abbreviation,MAX(p.date) FROM {link} a JOIN papers p ON p.id=a.paper_id JOIN journals j ON j.id=p.journal_id
                                     WHERE a.{field}=? GROUP BY j.abbreviation ORDER BY MAX(p.date) DESC LIMIT 1""",
                (e["id"],),
            ).fetchone()
            result["candidates"].append(
                dict(
                    id=e["id"],
                    name=e["display_name"],
                    papers=e["publication_count"],
                    latest_journal=latest[0] if latest else None,
                    latest_date=latest[1] if latest else None,
                )
            )
    elif not unresolved:
        result["status"] = "not_found"
        result["suggestions"] = [
            dict(id=e["id"], name=e["display_name"], papers=e["publication_count"])
            for e in entities.entity_search(kind, entry.get("name") or "", limit=5, con=con)[
                "items"
            ]
        ]
    if kind == "author" and unresolved:
        # Unlinked bylines with exactly this name: shown, but marked as unverified.
        marks = ",".join("?" for _ in unresolved)
        result["name_only"] = sorted(
            {
                r[0]
                for r in con.execute(
                    f"SELECT paper_id FROM authorships WHERE author_id IN ({marks})", unresolved
                )
            }
            & set(window)
        )
        if not identified:
            result["status"] = "name_only"
    return result


def papers_for(kind, ids, con, window):
    if not ids:
        return []
    link, field = (
        ("authorships", "author_id") if kind == "author" else ("affiliations", "institution_id")
    )
    marks = ",".join("?" for _ in ids)
    return sorted(
        {
            r[0]
            for r in con.execute(
                f"SELECT DISTINCT paper_id FROM {link} WHERE {field} IN ({marks})", ids
            )
        }
        & set(window)
    )


def build(con, prefs, topics, snapshot, cache=None):
    con.row_factory = sqlite3.Row
    start = date.fromordinal(
        entities.shift_months(date.fromisoformat(snapshot), -12).toordinal() + 1
    ).isoformat()
    # The app keeps the window between saves; the key changes when a new edition is published.
    key = (start, snapshot, (cache or {}).get("edition"))
    if cache is not None and cache.get("key") == key:
        window = cache["window"]
    else:
        window = window_rows(con, start, snapshot)
        if cache is not None:
            cache.update(key=key, window=window)
    warnings = []
    known_fields = {f["id"]: f for f in discovery.fields()}
    tiers = {f: v["tier"] for f, v in known_fields.items()}
    for field, tier in (prefs.get("fields") or {}).items():
        if field not in known_fields:
            warnings.append(f"Unknown field in preferences: {field}")
        elif tier not in TIERS:
            warnings.append(f'Unknown tier "{tier}" for {field}; use core, skim or mute')
        else:
            tiers[field] = tier
    journal_info = discovery.journal_fields()
    journal_tiers = {}
    for journal, tier in (prefs.get("journals") or {}).items():
        if journal not in journal_info:
            warnings.append(f"Unknown journal id in preferences: {journal}")
        elif tier not in TIERS:
            warnings.append(f'Unknown tier "{tier}" for {journal}; use core, skim or mute')
        else:
            journal_tiers[journal] = tier
    tier_of = lambda p: (
        journal_tiers.get(p["journal_id"]) or tiers[journal_info[p["journal_id"]]["field"]]
    )

    reasons = defaultdict(list)
    for_you = prefs.get("for_you") or {}
    phrases = [("keyword", str(k), str(k)) for k in for_you.get("keywords") or []]
    excluded = set(for_you.get("exclude_topics") or [])
    included = set(for_you.get("include_topics") or [])
    broad = {b for t in topics.values() for b in t["broader"]}
    topic_list = []
    for slug, topic in topics.items():
        status = (
            "off"
            if not for_you.get("cairn_topics", True)
            else "excluded"
            if slug in excluded
            else "broad"
            if slug in broad and slug not in included and not for_you.get("include_broad_topics")
            else "used"
        )
        # Short acronyms (e.g. "RSI") collide with unrelated fields; case variants are one phrase.
        texts = list(
            {
                t.casefold(): t
                for t in reversed([topic["title"], *topic["aliases"]])
                if len(t) >= 4
            }.values()
        )
        topic_list.append(
            dict(
                slug=slug,
                title=topic["title"],
                aliases=topic["aliases"],
                broader=topic["broader"],
                status=status,
                texts=texts,
                papers=set(),
            )
        )
        for text in texts:
            phrases.append(("topic", topic["title"], text))
    active_topics = {t["title"] for t in topic_list if t["status"] == "used"}
    topic_by_title = {t["title"]: t for t in topic_list}
    matched_terms = []
    for kind, label, text in phrases:
        query = phrase_query(text)
        if not query:
            continue
        try:
            hits = [
                r[0]
                for r in con.execute(
                    "SELECT paper_id FROM paper_search WHERE paper_search MATCH ?", (query,)
                )
                if r[0] in window
            ]
        except sqlite3.OperationalError as error:
            warnings.append(f'Could not use keyword "{text}": {error}')
            continue
        if kind == "topic":
            # Unused topics are matched too, so the topic list can show what each would add.
            topic_by_title[label]["papers"].update(hits)
            if label not in active_topics:
                continue
        for paper_id in hits:
            if not any(r["type"] == kind and r["label"] == label for r in reasons[paper_id]):
                reasons[paper_id].append(dict(type=kind, label=label))
        matched_terms.append(dict(type=kind, label=label, text=text, matches=len(hits)))

    follows = {}
    for kind, key in [("author", "people"), ("institution", "institutions")]:
        follows[key] = []
        for entry in prefs.get(key) or []:
            item = resolve(kind, entry, con, window)
            item["papers"] = papers_for(kind, item["ids"], con, window)
            for paper_id in item["papers"]:
                reasons[paper_id].append(
                    dict(type="person" if kind == "author" else "institution", label=item["label"])
                )
            for paper_id in item["name_only"]:
                if paper_id not in item["papers"]:
                    reasons[paper_id].append(
                        dict(type="person", label=item["label"], unverified=True)
                    )
            if item["status"] == "needs_choice":
                warnings.append(
                    f'"{item["label"]}" matches {len(item["candidates"])} identities; add ids: [...] to choose.'
                )
            elif item["status"] == "not_found":
                warnings.append(f'"{item["label"]}" was not found in the catalog.')
            follows[key].append(item)

    scores = {}
    for paper_id, why in reasons.items():
        weight = TIERS[tier_of(window[paper_id])]
        score = sum(WEIGHTS[r["type"]] * (0.5 if r.get("unverified") else 1) for r in why) * weight
        scores[paper_id] = dict(score=round(score, 2), reasons=why)
    # Highest score first; newest first within a score.
    ranked = sorted(
        (i for i, s in scores.items() if s["score"] > 0),
        key=lambda i: (window[i]["first_date"] or "", i),
        reverse=True,
    )
    ranked.sort(key=lambda i: -scores[i]["score"])
    ranked = ranked[:FOR_YOU_LIMIT]
    keep = set(ranked) | {
        i for group in follows.values() for f in group for i in f["papers"] + f["name_only"]
    }
    first_seen = (
        dict(con.execute("SELECT paper_id,first_seen FROM paper_first_seen"))
        if con.execute("SELECT 1 FROM sqlite_master WHERE name='paper_first_seen'").fetchone()
        else {}
    )
    rows = [dict(window[i], first_seen=first_seen.get(i)) for i in sorted(keep)]
    entities.add_author_links(con, rows)
    papers = {}
    for row in rows:
        row["authors"] = row["authors"][:5]
        row["author_entities"] = [
            {"position": a["position"], "author_id": a["author_id"]}
            for a in row["author_entities"]
            if a["position"] <= 5
        ]
        papers[row["id"]] = {k: row.get(k) for k in ROW_KEYS}
    return dict(
        version=1,
        generated=datetime.now(UTC).isoformat(timespec="seconds"),
        snapshot=snapshot,
        window=dict(start=start, end=snapshot),
        tiers=tiers,
        journal_tiers=journal_tiers,
        terms=matched_terms,
        topics=[
            {**{k: v for k, v in t.items() if k != "papers"}, "matches": len(t["papers"])}
            for t in topic_list
        ],
        preferences=dict(
            keywords=[str(k) for k in for_you.get("keywords") or []],
            cairn_topics=bool(for_you.get("cairn_topics", True)),
            include_broad_topics=bool(for_you.get("include_broad_topics")),
        ),
        people=follows["people"],
        institutions=follows["institutions"],
        for_you=ranked,
        scores={i: scores[i] for i in keep if i in scores},
        papers=papers,
        warnings=warnings,
    )


def cairn_topics():
    """Topic notes of the configured Cairn collection; none when no workspace is configured."""
    workspace = paths.workspace()
    return topic_notes(workspace / paths.collection() / "topics") if workspace else {}


def run(root=ROOT, preferences=PREFERENCES, topics=None, keep=None, cache=None):
    root = Path(root)
    prefs = load_preferences(Path(preferences))
    topics = cairn_topics() if topics is None else topics
    snapshot = json.loads((root / "coverage.json").read_text())["as_of"]
    with closing(sqlite3.connect(f"file:{root / 'catalog.sqlite'}?mode=ro", uri=True)) as con:
        if cache is not None:
            cache["edition"] = (root / "catalog.sqlite").stat().st_mtime_ns
        personal = build(con, prefs, topics, snapshot, cache)
    if keep is not None:
        keep["personal"] = personal
    text = (
        "window.CAIRN_PERSONAL="
        + json.dumps(personal, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
        + ";\n"
    )
    temp = root / (OUTPUT + ".tmp")
    temp.write_text(text, encoding="utf-8")
    temp.replace(root / OUTPUT)
    return dict(
        bytes=len(text.encode()),
        for_you=len(personal["for_you"]),
        terms=personal["terms"],
        topics=[t["slug"] for t in personal["topics"] if t["status"] == "used"],
        people={
            p["label"]: dict(
                status=p["status"], papers=len(p["papers"]), name_only=len(p["name_only"])
            )
            for p in personal["people"]
        },
        institutions={
            p["label"]: dict(status=p["status"], papers=len(p["papers"]))
            for p in personal["institutions"]
        },
        warnings=personal["warnings"],
    )
