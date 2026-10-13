#!/usr/bin/env python3
"""Build a small offline catalog with immutable, lazily loaded companion assets."""

import base64
import gzip
import json
import re
import shutil
import sqlite3
import tempfile
import unicodedata
import uuid
from collections import OrderedDict, defaultdict
from contextlib import closing
from pathlib import Path

from . import first_seen, insights, paths
from .discovery import first_publication

ROOT = paths.data_dir()
PAGES = {
    "catalog.html": "home",
    "search.html": "search",
    "authors.html": "author",
    "institutions.html": "institution",
    "explore.html": "home",
}
ASSET_DIR = re.compile(r"catalog-assets-[0-9a-f]{16}")
SUMMARY_CHUNK, ENTITY_CHUNK = 5000, 2000
# Hash-sharded bundles always exist, so the page needs no list of bundle names.
BUCKETS = [f"{n:02x}" for n in range(256)]
# List rows carry only what result lists, filters and bylines read; details-* keep the full record.
SUMMARY_FIELDS = [
    "id",
    "title",
    "journal_id",
    "journal",
    "authors",
    "author_count",
    "author_ids",
    "author_pos",
    "date",
    "date_precision",
    "published_print",
    "published_online",
    "year",
    "volume",
    "volume_series",
    "issue",
    "article_number",
    "issue_id",
    "entry_type",
    "publication_status",
    "publication_status_evidence",
    "first_date",
    "first_precision",
    "first_lower",
    "first_upper",
    "first_source",
    "first_seen",
]
SUMMARY_DICTS = {
    "journal_id",
    "journal",
    "date_precision",
    "entry_type",
    "publication_status",
    "publication_status_evidence",
    "first_precision",
    "first_source",
    "volume_series",
    "first_seen",
}


def bucket(value):
    result = 0
    for ch in value:
        result = (result * 31 + ord(ch)) & 0xFFFFFFFF
    return f"{result % 256:02x}"


def tokens(value):
    value = "".join(
        c
        for c in unicodedata.normalize("NFKD", value)
        if not unicodedata.category(c).startswith("M")
    ).lower()
    return set(re.findall(r"[^\W_]+", value, re.UNICODE))


def dump(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def columnar(rows, fields, dict_fields=()):
    """One array per field; repeated strings are stored once per bundle."""
    columns, dicts = {}, {}
    for field in fields:
        values = [r.get(field) for r in rows]
        if field in dict_fields:
            table = {}
            values = [None if v is None else table.setdefault(v, len(table)) for v in values]
            dicts[field] = list(table)
        columns[field] = values
    return {"columns": columns, "dicts": dicts}


def summary_row(p):
    credits = p["author_entities"]
    positions = [c["position"] for c in credits]
    return {
        **p,
        "author_ids": [c["author_id"] for c in credits],
        "author_pos": None if positions == list(range(1, len(positions) + 1)) else positions,
    }


def js_order(value):
    """Sort strings by UTF-16 code units, as JavaScript comparison does."""
    return (value or "").encode("utf-16-be")


def shard_key(word):
    return word[:2]


def hex_key(key):
    return "-".join(f"{ord(c):x}" for c in key)


def year_bounds(p):
    years = [
        v[:4]
        for v in [
            p["date"],
            p["published_online"],
            p["published_print"],
            p["first_lower"],
            p["first_upper"],
        ]
        if v
    ]
    return (min(years) + "-01-01", max(years) + "-12-31") if years else (None, None)


def prune_assets(root, keep):
    """Remove superseded asset editions and the retired single-file export."""
    root = Path(root)
    removed = []
    for path in root.iterdir():
        if path.is_dir() and ASSET_DIR.fullmatch(path.name) and path.name != keep:
            shutil.rmtree(path)
            removed.append(path.name)
    legacy = root / "catalog-data.js"
    if legacy.exists():
        legacy.unlink()
        removed.append(legacy.name)
    return sorted(removed)


def build(root=ROOT, source_root=ROOT):
    root, source_root = Path(root), Path(source_root)
    version = uuid.uuid4().hex[:16]
    asset_name = "catalog-assets-" + version
    assets = root / asset_name
    assets.mkdir()
    sizes = {}
    snapshot = json.loads((root / "coverage.json").read_text())["as_of"]
    first_seen.update(root, source_root, snapshot)

    def bundle(name, value):
        raw = dump(value).encode()
        data = base64.b64encode(gzip.compress(raw, compresslevel=6, mtime=0)).decode()
        script = f"window.CairnBundles.register({json.dumps(version)},{json.dumps(name)},{json.dumps(data)});\n"
        (assets / (name + ".js")).write_text(script, encoding="utf-8")
        sizes[name] = len(script.encode())

    fields = [
        "id",
        "title",
        "journal_id",
        "journal",
        "authors",
        "doi",
        "date",
        "date_precision",
        "published_print",
        "published_online",
        "year",
        "volume",
        "volume_series",
        "publication_unit",
        "issue",
        "article_number",
        "pages",
        "issue_id",
        "cairn_slug",
        "entry_type",
        "publication_status",
        "publication_status_evidence",
    ]
    papers = []
    with closing(sqlite3.connect(f"file:{root / 'catalog.sqlite'}?mode=ro", uri=True)) as con:
        con.row_factory = sqlite3.Row
        credits, affiliations = defaultdict(list), defaultdict(list)
        seen = dict(con.execute("SELECT paper_id,first_seen FROM paper_first_seen"))
        for r in con.execute(
            "SELECT a.*,e.identity_status FROM authorships a JOIN author_entities e ON e.id=a.author_id ORDER BY a.paper_id,a.position"
        ):
            credits[r["paper_id"]].append(
                {k: r[k] for k in ["position", "observed_name", "author_id", "identity_status"]}
            )
        for r in con.execute(
            "SELECT DISTINCT a.paper_id,i.* FROM affiliations a JOIN institution_entities i ON i.id=a.institution_id"
        ):
            r = dict(r)
            affiliations[r.pop("paper_id")].append(r)
        postings, doi_ids = defaultdict(list), defaultdict(list)
        recent_month, recent_uncertain = defaultdict(list), defaultdict(list)
        # Deep records dominate memory. Spool them in source order by bucket and
        # cap open descriptors with a small LRU; serialize one bucket at a time.
        with tempfile.TemporaryDirectory(prefix=".browser-details-", dir=root) as spool_dir:
            spool_dir = Path(spool_dir)
            open_spools = OrderedDict()

            def write_detail(bucket_key, paper_id, detail):
                handle = open_spools.pop(bucket_key, None)
                if handle is None:
                    handle = (spool_dir / (bucket_key + ".jsonl")).open("a", encoding="utf-8")
                open_spools[bucket_key] = handle
                if len(open_spools) > 64:
                    _, oldest = open_spools.popitem(last=False)
                    oldest.close()
                handle.write(dump([paper_id, detail]) + "\n")

            try:
                with (root / "papers.jsonl").open(encoding="utf-8") as handle:
                    for line in handle:
                        r = json.loads(line)
                        p = {k: r.get(k) for k in fields}
                        p.update(first_publication(r))
                        p.update(
                            author_count=len(r.get("authors") or []),
                            authors=(r.get("authors") or [])[:10],
                            author_entities=credits[r["id"]][:10],
                            first_seen=seen.get(r["id"]),
                        )
                        index = len(papers)
                        papers.append(p)
                        for token in tokens(
                            " ".join(
                                [
                                    r["title"],
                                    " ".join(r["authors"]),
                                    r.get("abstract") or "",
                                    r["journal"],
                                ]
                            )
                        ):
                            postings[token].append(index)
                        for doi in [r.get("doi"), *(r.get("alternate_dois") or [])]:
                            if doi:
                                doi_ids[doi.lower()].append(index)
                        key = bucket(r["id"])
                        detail = {
                            **r,
                            "author_entities": credits[r["id"]],
                            "institution_entities": affiliations[r["id"]],
                        }
                        write_detail(key, r["id"], detail)
                        if p["first_lower"] and r["entry_type"] in ["article", "article_or_other"]:
                            lo, hi = p["first_lower"], p["first_upper"]
                            uncertain_precision = p["first_precision"] in {
                                "year",
                                "provider_day_unverified",
                                "provider_date_unverified",
                                "range",
                            }
                            if lo[:7] == hi[:7] and not uncertain_precision:
                                recent_month[lo[:7]].append(p)
                            else:
                                for year in range(int(lo[:4]), int(hi[:4]) + 1):
                                    recent_uncertain[str(year)].append(p)
            finally:
                for handle in open_spools.values():
                    handle.close()
                open_spools.clear()

            for key in BUCKETS:
                value, path = {}, spool_dir / (key + ".jsonl")
                if path.exists():
                    with path.open(encoding="utf-8") as handle:
                        for line in handle:
                            paper_id, detail = json.loads(line)
                            value[paper_id] = detail
                bundle("details-" + key, value)
        del credits, affiliations, seen
        for month, rows in recent_month.items():
            bundle(
                "recent-" + month,
                columnar([summary_row(p) for p in rows], SUMMARY_FIELDS, SUMMARY_DICTS),
            )
        for year, rows in recent_uncertain.items():
            bundle(
                "recent-" + year + "-uncertain",
                columnar([summary_row(p) for p in rows], SUMMARY_FIELDS, SUMMARY_DICTS),
            )
        # Journal-contiguous, date-ordered rows let a journal, period or match set
        # select a few chunks. Every index-based structure is remapped to this order.
        order = sorted(
            range(len(papers)),
            key=lambda i: (
                papers[i]["journal_id"],
                papers[i]["first_lower"] or papers[i]["date"] or "",
                i,
            ),
        )
        moved = [0] * len(order)
        for new, old in enumerate(order):
            moved[old] = new
        papers = [papers[i] for i in order]
        del order
        summary_chunks = []
        start = 0
        while start < len(papers):
            journal = papers[start]["journal_id"]
            end = start
            while (
                end < len(papers)
                and end - start < SUMMARY_CHUNK
                and papers[end]["journal_id"] == journal
            ):
                end += 1
            rows = papers[start:end]
            spans = [b for b in map(year_bounds, rows) if b[0]]
            name = f"summaries-{journal}-{sum(c[3] == journal for c in summary_chunks) + 1:04d}"
            bundle(name, columnar([summary_row(p) for p in rows], SUMMARY_FIELDS, SUMMARY_DICTS))
            summary_chunks.append(
                [
                    name,
                    start,
                    end - start,
                    journal,
                    min((b[0] for b in spans), default=None),
                    max((b[1] for b in spans), default=None),
                ]
            )
            start = end
        index_parts = defaultdict(dict)
        for token, ids in postings.items():
            index_parts[bucket(token)][token] = sorted(moved[i] for i in ids)
        del postings
        for key in BUCKETS:
            bundle("search-" + key, index_parts.get(key, {}))
        del index_parts
        doi_parts = defaultdict(dict)
        for doi, ids in doi_ids.items():
            doi_parts[bucket(doi)][doi] = sorted(moved[i] for i in ids)
        for key in BUCKETS:
            bundle("dois-" + key, doi_parts.get(key, {}))
        del doi_ids, doi_parts, moved
        bundle(
            "issues",
            [json.loads(line) for line in (root / "issues.jsonl").read_text().splitlines()],
        )
        pi = {p["id"]: i for i, p in enumerate(papers)}
        entity_config = {}
        for kind in ["author", "institution"]:
            if kind == "author":
                rows = [
                    dict(r)
                    for r in con.execute(
                        "SELECT e.*,d.family_name,d.given_names,d.sort_key,d.surname_source FROM author_entities e JOIN author_directory d ON d.author_id=e.id ORDER BY e.id"
                    )
                ]
                aliases = con.execute("SELECT DISTINCT author_id,name FROM author_aliases")
                identifiers = list(
                    con.execute("SELECT author_id,identifier FROM author_identifiers")
                )
                relations = con.execute("SELECT DISTINCT author_id,paper_id FROM authorships")
            else:
                rows = [
                    dict(r) for r in con.execute("SELECT * FROM institution_entities ORDER BY id")
                ]
                aliases = con.execute("SELECT institution_id,name FROM institution_aliases")
                identifiers = []
                relations = con.execute("SELECT DISTINCT institution_id,paper_id FROM affiliations")
            by_id = {r["id"]: r for r in rows}
            for r in rows:
                r.update(aliases=[], identifiers=[], paper_indices=[])
            for identity, name in aliases:
                by_id[identity]["aliases"].append(name)
            for identity, identifier in identifiers:
                by_id[identity]["identifiers"].append(identifier)
            for identity, paper_id in relations:
                by_id[identity]["paper_indices"].append(pi[paper_id])
            del by_id
            # Ordinals follow the directory's display order, so a page is a contiguous range.
            if kind == "author":
                rows.sort(key=lambda r: (js_order(r["sort_key"]), js_order(r["id"])))
            else:
                rows.sort(
                    key=lambda r: (
                        -r["publication_count"],
                        js_order(r["display_name"]),
                        js_order(r["id"]),
                    )
                )
            fields = list(dict.fromkeys(k for r in rows[:1000] for k in r))
            dict_fields = {"identity_status", "surname_source", "type", "country_code"}
            for start in range(0, len(rows), ENTITY_CHUNK):
                bundle(
                    f"{kind}s-{start // ENTITY_CHUNK + 1:04d}",
                    columnar(rows[start : start + ENTITY_CHUNK], fields, dict_fields),
                )
            ids, names = defaultdict(dict), defaultdict(lambda: defaultdict(list))
            count = len(rows)
            slots = max((len(set([r["display_name"], *r["aliases"]])) for r in rows), default=1)
            slots = 1 << max(0, slots - 1).bit_length()
            for ordinal, r in enumerate(rows):
                for identifier in {r["id"], r.get("openalex_id"), *r["identifiers"]} - {None}:
                    ids[bucket(identifier)][identifier] = ordinal
                # One posting per name keeps "every query word matches the same name" exact.
                for slot, name in enumerate(dict.fromkeys([r["display_name"], *r["aliases"]])):
                    for word in tokens(name or ""):
                        names[shard_key(word)][word].append(ordinal * slots + slot)
            del rows
            for key in BUCKETS:
                bundle(f"{kind}-ids-{key}", ids.get(key, {}))
            del ids
            # Small prefixes share a file per first character; large ones stand alone.
            files, groups = {}, defaultdict(dict)
            for key, words in names.items():
                size = sum(len(w) + 8 * len(v) for w, v in words.items())
                files[key] = hex_key(key) if size > 200000 else hex_key(key[0]) + "-s"
                for word, values in words.items():
                    # Ascending postings are stored as gaps.
                    groups[files[key]][word] = [values[0]] + [
                        b - a for a, b in zip(values, values[1:], strict=False)
                    ]
            del names
            for file, value in groups.items():
                bundle(f"{kind}-names-{file}", value)
            bundle(f"{kind}-name-shards", files)
            entity_config[kind] = {"count": count, "chunk": ENTITY_CHUNK, "slots": slots}
        # Discovery summaries load only on field and people views.
        bundle("insights", insights.build(con, snapshot))
        registry = {j["id"]: j for j in paths.journals(source_root)}
        journals = [
            {**dict(r), "field": registry[r["id"]]["field"], "group": registry[r["id"]]["group"]}
            for r in con.execute("SELECT id,title,abbreviation FROM journals ORDER BY title")
        ]
        meta = {
            "journals": journals,
            "fields": json.loads((paths.ASSETS / "fields.json").read_text(encoding="utf-8")),
            "papers": len(papers),
            "issues": con.execute("SELECT count(*) FROM issues").fetchone()[0],
            "entities": json.loads((root / "entity-coverage.json").read_text()),
            "snapshot_date": snapshot,
        }
    for name in ["periods.js", "offline-runtime.js", "catalog-ui.js", "catalog.css"]:
        shutil.copyfile(paths.ASSETS / name, assets / name)
    recent_periods = {}
    for month in recent_month:
        recent_periods.setdefault(month[:4], {"months": [], "uncertain": False})["months"].append(
            month[5:7]
        )
    for year in recent_uncertain:
        recent_periods.setdefault(year, {"months": [], "uncertain": False})["uncertain"] = True
    for value in recent_periods.values():
        value["months"] = sorted(set(value["months"]))
    config = {
        "version": version,
        "assets": asset_name + "/",
        "meta": meta,
        "recent_years": sorted(recent_periods),
        "recent_periods": recent_periods,
        "summary_chunks": summary_chunks,
        "entities": entity_config,
    }
    template = (paths.ASSETS / "browser-template.html").read_text()
    config_text = dump(config).replace("<", "\\u003c")
    for filename, page in PAGES.items():
        html = (
            template.replace("__PAGE__", page)
            .replace("__CONFIG__", config_text)
            .replace("__ASSETS__", asset_name + "/")
        )
        temp = root / (filename + ".tmp")
        temp.write_text(html, encoding="utf-8")
        temp.replace(root / filename)
    current_year, current_month = map(int, meta["snapshot_date"][:7].split("-"))
    serial = current_year * 12 + current_month - 1
    home_months = [f"{n // 12:04d}-{n % 12 + 1:02d}" for n in range(serial - 3, serial + 1)]
    home_shards = ["recent-" + month for month in home_months]
    home_shards.extend(
        "recent-" + year + "-uncertain" for year in {month[:4] for month in home_months}
    )
    initial = (
        (root / "catalog.html").stat().st_size
        + sum(
            (assets / n).stat().st_size
            for n in ["catalog.css", "catalog-ui.js", "offline-runtime.js", "periods.js"]
        )
        + sum(sizes.get(name, 0) for name in home_shards)
    )
    report = {
        "version": version,
        "assets": asset_name,
        "papers": len(papers),
        "issues": meta["issues"],
        "html_mb": round((root / "catalog.html").stat().st_size / 1e6, 3),
        "initial_year_payload_bytes": initial,
        "asset_bytes": sum(p.stat().st_size for p in assets.iterdir()),
        "summary_chunks": len(summary_chunks),
        "largest_summary_chunk_bytes": max((sizes[c[0]] for c in summary_chunks), default=0),
        "self_contained": False,
        "requires_server": False,
        "snapshot_date": meta["snapshot_date"],
    }
    (root / "browser-build.json").write_text(json.dumps(report, indent=2) + "\n")
    # Entrypoints now reference only this edition; superseded editions are removed.
    report["pruned"] = prune_assets(root, asset_name)
    print(json.dumps(report), flush=True)
    return report
