#!/usr/bin/env python3
"""Author/institution indexes and precise period queries for the journal catalog."""

from __future__ import annotations

import argparse
import calendar
import gzip
import hashlib
import json
import re
import sqlite3
import time
import unicodedata
from collections import Counter, defaultdict
from contextlib import closing
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from . import author_directory, paths, publication_status

ROOT = paths.data_dir()
DB = ROOT / "catalog.sqlite"


def normalized_name(value):
    value = str(value or "").strip()
    if "," in value:
        last, first = value.split(",", 1)
        value = first.strip() + " " + last.strip()
    value = unicodedata.normalize("NFKD", value.casefold())
    value = "".join(c for c in value if not unicodedata.combining(c))
    return " ".join(re.findall(r"[^\W_]+", value, flags=re.UNICODE))


def names_compatible(a, b):
    a, b = normalized_name(a), normalized_name(b)
    if a == b:
        return True
    aa, bb = a.split(), b.split()
    # A shared surname/first initial is usable only within an already matched paper.
    return (
        len(aa) > 1
        and len(bb) > 1
        and aa[-1] == bb[-1]
        and aa[0][0] == bb[0][0]
        and (aa[0] == bb[0] or len(aa[0]) == 1 or len(bb[0]) == 1)
    )


def identifier(value, scheme):
    value = str(value or "").strip()
    if scheme == "orcid":
        m = re.search(r"(\d{4}-\d{4}-\d{4}-\d{3}[\dXx])$", value)
        return "orcid:" + m[1].upper() if m else None
    if scheme == "openalex":
        m = re.search(r"([AI]\d+)$", value)
        return "openalex:" + m[1] if m else None
    if scheme == "ror":
        m = re.search(r"(?:ror\.org/|ror:)([0-9a-z]{9})$", value)
        return "ror:" + m[1] if m else None
    return None


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()[:20]


def connect(readonly=False, db=DB):
    con = (
        sqlite3.connect(f"file:{Path(db).resolve()}?mode=ro", uri=True)
        if readonly
        else sqlite3.connect(db)
    )
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    return con


class IdentityGroups:
    def __init__(self):
        self.parents = {}
        self.orcids = {}
        self.conflicts = []

    def root(self, value):
        if value not in self.parents:
            self.parents[value] = value
            self.orcids[value] = {value} if value.startswith("orcid:") else set()
        if self.parents[value] != value:
            self.parents[value] = self.root(self.parents[value])
        return self.parents[value]

    def join(self, a, b, evidence):
        a, b = self.root(a), self.root(b)
        if a == b:
            return True
        combined = self.orcids[a] | self.orcids[b]
        if len(combined) > 1:
            self.conflicts.append({"left": a, "right": b, "evidence": evidence})
            return False
        # ORCID is the preferred identity when a source associates it with an OpenAlex ID.
        if (not a.startswith("orcid:"), a) > (not b.startswith("orcid:"), b):
            a, b = b, a
        self.parents[b] = a
        self.orcids[a] = combined
        return True


def date_bounds(value, precision=None):
    """Bound partial dates without fabricating a publication day."""
    if not value:
        return None
    try:
        components = [int(v) for v in str(value).split("-")]
        y = components[0]
        date(y, 1, 1)
        if precision == "provider_day_unverified":
            return f"{y:04d}-01-01", f"{y:04d}-12-31", "provider_date_unverified"
        if len(components) == 1:
            return f"{y:04d}-01-01", f"{y:04d}-12-31", "year"
        if len(components) == 2:
            m = components[1]
            last = calendar.monthrange(y, m)[1]
            return f"{y:04d}-{m:02d}-01", f"{y:04d}-{m:02d}-{last:02d}", "month"
        d = date(*components).isoformat()
        return d, d, "day"
    except (ValueError, TypeError, IndexError):
        return None


def shift_months(value, months):
    year, month = divmod(value.year * 12 + value.month - 1 + months, 12)
    return date(year, month + 1, min(value.day, calendar.monthrange(year, month + 1)[1]))


def period_bounds(period="last-quarter", as_of=None, start_date=None, end_date=None):
    """Inclusive date bounds are canonical; named periods are convenient shorthand."""
    anchor = (
        date.fromisoformat(as_of) if as_of else datetime.now(ZoneInfo("America/Chicago")).date()
    )
    if start_date or end_date:
        lo = date.fromisoformat(start_date) if start_date else date.min
        hi = date.fromisoformat(end_date) if end_date else date.max
        if lo > hi:
            raise ValueError("The start date must be on or before the end date.")
        return lo.isoformat(), hi.isoformat(), f"{lo.isoformat()} to {hi.isoformat()}"
    if period == "all":
        return "0001-01-01", "9999-12-31", "All available dates"
    if period in ["this-year", "last-year"]:
        period = str(anchor.year - (period == "last-year"))
    if re.fullmatch(r"\d{4}", period):
        year = int(period)
        return date(year, 1, 1).isoformat(), date(year, 12, 31).isoformat(), str(year)
    rolling = re.fullmatch(r"last-(\d+)-(years?|quarters?)", period)
    if rolling:
        count = int(rolling[1])
        if count < 1:
            raise ValueError("Window length must be positive.")
        months = count * (12 if rolling[2].startswith("year") else 3)
        lo = shift_months(anchor, -months) + timedelta(days=1)
        return (
            lo.isoformat(),
            anchor.isoformat(),
            f"Past {count} {rolling[2]} through {anchor.isoformat()}",
        )
    if ":" in period:
        lo, hi = period.split(":", 1)
        if re.fullmatch(r"\d{4}", lo) and re.fullmatch(r"\d{4}", hi):
            lo, hi = lo + "-01-01", hi + "-12-31"
        return period_bounds(as_of=as_of, start_date=lo, end_date=hi)
    if period == "last-quarter":
        quarter = (anchor.month - 1) // 3
        year = anchor.year
        if quarter == 0:
            year, quarter = year - 1, 4
    else:
        m = re.fullmatch(r"(\d{4})-Q([1-4])", period, flags=re.I)
        if not m:
            raise ValueError(
                "Use all, YYYY, YYYY-Q1, YYYY:YYYY, last-N-years/quarters, or explicit start/end dates."
            )
        year, quarter = int(m[1]), int(m[2])
    month = 3 * (quarter - 1) + 1
    last_month = month + 2
    return (
        date(year, month, 1).isoformat(),
        date(year, last_month, calendar.monthrange(year, last_month)[1]).isoformat(),
        f"{year}-Q{quarter}",
    )


def affiliation_objects(value, provider):
    result = []
    for obj in value or []:
        if isinstance(obj, str):
            obj = {"name": obj}
        name = obj.get("display_name") or obj.get("name")
        if not name:
            continue
        ror = identifier(obj.get("ror"), "ror")
        oa = identifier(obj.get("id"), "openalex")
        for asserted in obj.get("id", []) if isinstance(obj.get("id"), list) else []:
            if isinstance(asserted, dict) and str(asserted.get("id-type", "")).lower() == "ror":
                ror = identifier(asserted.get("id"), "ror")
        result.append(
            {
                "name": name,
                "ror": ror,
                "openalex_id": oa,
                "country_code": obj.get("country_code"),
                "type": obj.get("type"),
                "provider": provider,
            }
        )
    return result


def authors_for_work(work, provider):
    result = []
    if provider == "crossref":
        for a in work.get("author") or []:
            name = " ".join(v for v in [a.get("given"), a.get("family")] if v) or a.get("name")
            if name:
                result.append(
                    {
                        "provider": provider,
                        "name": name,
                        "orcid": identifier(a.get("ORCID"), "orcid"),
                        "openalex_id": None,
                        "affiliations": affiliation_objects(a.get("affiliation"), provider),
                        "raw_affiliations": [],
                    }
                )
    else:
        for a in work.get("authorships") or []:
            person = a.get("author") or {}
            name = person.get("display_name") or a.get("raw_author_name")
            if name:
                result.append(
                    {
                        "provider": provider,
                        "name": name,
                        "orcid": identifier(person.get("orcid"), "orcid"),
                        "raw_orcid": identifier(a.get("raw_orcid"), "orcid"),
                        "openalex_id": identifier(person.get("id"), "openalex"),
                        "affiliations": affiliation_objects(a.get("institutions"), provider),
                        "raw_affiliations": a.get("raw_affiliation_strings") or [],
                    }
                )
    return result


def build_entities(db=DB):
    started = time.perf_counter()
    con = connect(db=db)
    # The graph contains millions of byline credits after physics imports.
    # Keep a useful B-tree cache while writing the staged database.
    con.execute("PRAGMA cache_size=-131072")
    doi_papers = dict(con.execute("SELECT doi,paper_id FROM paper_dois"))
    oa_papers, events = {}, []
    for row in con.execute("SELECT id,date,date_precision,record_json FROM papers"):
        r = json.loads(row["record_json"])
        for oid in r.get("openalex_ids", []):
            oa_papers[oid] = row["id"]
        for kind, value, prec, source in [
            (
                "issue",
                r.get("date"),
                r.get("date_precision"),
                r.get("field_sources", {}).get("date", "unknown"),
            ),
            ("online", r.get("published_online"), None, "crossref:published-online"),
            ("print", r.get("published_print"), None, "crossref:published-print"),
        ]:
            bounds = date_bounds(value, prec)
            if bounds:
                events.append((row["id"], kind, value, bounds[0], bounds[1], bounds[2], source))
    # Raw author enrichment must obey the same admission decision as bibliography.
    # Otherwise a quarantined discovery could re-enter via a shared DOI.
    admitted_sources, membership_gated = set(), set()
    for row in con.execute("SELECT id,record_json FROM papers"):
        record = json.loads(row["record_json"])
        if not record.get("journal_membership"):
            continue  # Older databases/fixtures can still be read.
        membership_gated.add(row["id"])
        for source in record.get("sources", []):
            key = source["id"].lower() if source["provider"] == "crossref" else source["id"]
            admitted_sources.add((row["id"], source["provider"], key))
    credits, paper_credits = {}, defaultdict(list)
    for a in con.execute("SELECT * FROM authors ORDER BY paper_id,position"):
        details = json.loads(a["details_json"] or "{}")
        provider = "openalex" if details.get("openalex_id") else "catalog"
        evidence = {
            "provider": provider,
            "name": a["name"],
            "orcid": identifier(details.get("orcid"), "orcid"),
            "openalex_id": identifier(details.get("openalex_id"), "openalex"),
            "affiliations": affiliation_objects(details.get("affiliations"), provider),
            "raw_affiliations": [],
            "match_basis": "catalog_author_credit",
        }
        c = {
            "paper_id": a["paper_id"],
            "position": a["position"],
            "name": a["name"],
            "evidence": [evidence],
        }
        credits[(a["paper_id"], a["position"])] = c
        paper_credits[a["paper_id"]].append(c)
    matched, unmatched = Counter(), Counter()
    for provider in ["crossref", "openalex"]:
        for folder in sorted((ROOT / "raw" / provider).glob("*")):
            state_file = folder / "state.json"
            if not state_file.exists():
                continue
            state = json.loads(state_file.read_text())
            if not state.get("complete") and not (
                state.get("usable_checkpoint") and state.get("incomplete_reason")
            ):
                raise RuntimeError(f"Incomplete source harvest: {folder}")
            for n in range(1, state["pages"] + 1):
                raw = folder / f"page-{n:05d}.json.gz"
                with gzip.open(raw, "rt", encoding="utf-8") as f:
                    payload = json.load(f)
                items = (
                    payload["response"]["message"]["items"]
                    if provider == "crossref"
                    else payload["response"]["results"]
                )
                for work in items:
                    work_id = work.get("DOI") if provider == "crossref" else work.get("id")
                    d = re.sub(
                        r"^https?://(?:dx\.)?doi\.org/",
                        "",
                        work.get("DOI") or work.get("doi") or "",
                        flags=re.I,
                    ).lower()
                    paper_id = doi_papers.get(d) or oa_papers.get(work_id)
                    if not paper_id or paper_id not in paper_credits:
                        continue
                    source_key = work_id.lower() if provider == "crossref" else work_id
                    if (
                        paper_id in membership_gated
                        and (paper_id, provider, source_key) not in admitted_sources
                    ):
                        continue
                    current = paper_credits[paper_id]
                    observed = authors_for_work(work, provider)
                    # Large physics collaborations can have thousands of credits.
                    # Index the byline once rather than normalize every candidate
                    # for every source author. Keep all candidates to preserve the
                    # existing ambiguity and byline-position rules.
                    by_name, by_family_initial = defaultdict(list), defaultdict(list)
                    for credit in current:
                        name = normalized_name(credit["name"])
                        by_name[name].append(credit)
                        parts = name.split()
                        key = (parts[-1], parts[0][0]) if len(parts) > 1 else ("", name)
                        by_family_initial[key].append(credit)
                    for pos, evidence in enumerate(observed):
                        name = normalized_name(evidence["name"])
                        exact = by_name.get(name, [])
                        if len(exact) == 1:
                            target, basis = exact[0], "same_paper_exact_author_name"
                        elif len(current) == len(observed) and names_compatible(
                            current[pos]["name"], evidence["name"]
                        ):
                            target, basis = (
                                current[pos],
                                "same_paper_byline_position_and_compatible_name",
                            )
                        else:
                            parts = name.split()
                            key = (parts[-1], parts[0][0]) if len(parts) > 1 else ("", name)
                            alternatives = [
                                c
                                for c in by_family_initial.get(key, [])
                                if names_compatible(c["name"], evidence["name"])
                            ]
                            if len(alternatives) != 1:
                                unmatched[provider] += 1
                                continue
                            target, basis = (
                                alternatives[0],
                                "same_paper_unique_compatible_author_name",
                            )
                        evidence.update(
                            {
                                "work_id": work_id,
                                "raw_file": str(raw.relative_to(ROOT)),
                                "match_basis": basis,
                            }
                        )
                        target["evidence"].append(evidence)
                        matched[provider] += 1
        print(
            f"Author evidence recovered from {provider}: {matched[provider]:,} aligned credits; {unmatched[provider]:,} unmatched",
            flush=True,
        )
    groups = IdentityGroups()
    institution_candidates = {}
    for c in credits.values():
        ids = []
        for e in c["evidence"]:
            ids.extend(v for v in [e.get("raw_orcid"), e.get("orcid"), e.get("openalex_id")] if v)
            for i in e["affiliations"]:
                identity = (
                    i["ror"]
                    or i["openalex_id"]
                    or "unresolved-institution:" + digest(normalized_name(i["name"]))
                )
                institution_candidates.setdefault(
                    identity, {**i, "id": identity, "aliases": set()}
                )["aliases"].add(i["name"])
        ids = list(dict.fromkeys(ids))
        for value in ids:
            groups.root(value)
        if ids:
            preferred = sorted(ids, key=lambda x: (not x.startswith("orcid:"), x))[0]
            for other in ids:
                groups.join(
                    preferred, other, {"paper_id": c["paper_id"], "position": c["position"]}
                )
        c["identifiers"] = ids
    # Map an unstructured institution label only when it exactly identifies one known entity.
    named_institutions = defaultdict(set)
    for identity, i in institution_candidates.items():
        if not identity.startswith("unresolved-"):
            for alias in i["aliases"]:
                named_institutions[normalized_name(alias)].add(identity)
    oa_to_ror = defaultdict(set)
    for i in institution_candidates.values():
        if i["openalex_id"] and i["ror"]:
            oa_to_ror[i["openalex_id"]].add(i["ror"])
    institution_map = {}
    for identity, i in institution_candidates.items():
        exact = named_institutions[normalized_name(i["name"])]
        shared_id = oa_to_ror.get(identity, set())
        institution_map[identity] = (
            next(iter(shared_id))
            if len(shared_id) == 1
            else next(iter(exact))
            if identity.startswith("unresolved-") and len(exact) == 1
            else identity
        )
    persons = {}
    affiliation_rows, authorship_rows, alias_rows = [], [], set()
    for c in credits.values():
        roots = sorted(
            {groups.root(v) for v in c["identifiers"]},
            key=lambda x: (not x.startswith("orcid:"), x),
        )
        # Conflicting source identifiers stay outside either person's bibliography.
        conflict = len(roots) > 1
        identity = (
            roots[0]
            if len(roots) == 1
            else "unresolved-author:" + digest(c["paper_id"] + ":" + str(c["position"]))
        )
        p = persons.setdefault(
            identity,
            {
                "id": identity,
                "names": Counter(),
                "status": "identifier_conflict"
                if conflict
                else "source_identified"
                if roots
                else "unresolved_credit",
            },
        )
        for e in c["evidence"]:
            p["names"][e["name"]] += 1
            alias_rows.add((identity, e["name"], normalized_name(e["name"]), e["provider"]))
            for i in e["affiliations"]:
                original = (
                    i["ror"]
                    or i["openalex_id"]
                    or "unresolved-institution:" + digest(normalized_name(i["name"]))
                )
                inst_id = institution_map[original]
                affiliation_rows.append(
                    (
                        c["paper_id"],
                        c["position"],
                        inst_id,
                        e["provider"],
                        "asserted_identifier"
                        if i["ror"] or i["openalex_id"]
                        else "exact_name_to_identifier"
                        if inst_id != original
                        else "unresolved_label",
                        i["name"],
                        json.dumps(
                            {
                                k: v
                                for k, v in e.items()
                                if k in ["work_id", "raw_file", "match_basis"]
                            }
                        ),
                    )
                )
        authorship_rows.append(
            (
                c["paper_id"],
                c["position"],
                identity,
                c["name"],
                "identifier_conflict"
                if conflict
                else "source_identifiers"
                if roots
                else "unresolved_paper_credit",
            )
        )
    # Evidence dictionaries are no longer needed once the SQL rows and identity
    # groups are derived. Release them before bulk insertion to avoid swapping.
    del credits, paper_credits, doi_papers, oa_papers, admitted_sources, membership_gated
    current = observed = payload = work = credit = c = e = by_name = by_family_initial = None
    print(
        f"Writing graph: {len(persons):,} author identities, {len(authorship_rows):,} credits, {len(affiliation_rows):,} affiliation assertions",
        flush=True,
    )
    con.executescript("""
    BEGIN IMMEDIATE;
    DROP TABLE IF EXISTS affiliations;
    DROP TABLE IF EXISTS author_aliases;
    DROP TABLE IF EXISTS author_identifiers;
    DROP TABLE IF EXISTS authorships;
    DROP TABLE IF EXISTS author_directory;
    DROP TABLE IF EXISTS author_entities;
    DROP TABLE IF EXISTS institution_aliases;
    DROP TABLE IF EXISTS institution_entities;
    DROP TABLE IF EXISTS publication_events;
    DROP TABLE IF EXISTS identity_conflicts;
    DROP TABLE IF EXISTS entity_names;
    CREATE TABLE author_entities(id TEXT PRIMARY KEY,display_name TEXT NOT NULL,identity_status TEXT NOT NULL,publication_count INTEGER NOT NULL DEFAULT 0);
    CREATE TABLE author_identifiers(identifier TEXT PRIMARY KEY,author_id TEXT NOT NULL REFERENCES author_entities(id));
    CREATE TABLE author_aliases(author_id TEXT NOT NULL REFERENCES author_entities(id),name TEXT NOT NULL,normalized_name TEXT NOT NULL,provider TEXT NOT NULL,PRIMARY KEY(author_id,name,provider));
    CREATE TABLE authorships(paper_id TEXT NOT NULL REFERENCES papers(id),position INTEGER NOT NULL,author_id TEXT NOT NULL REFERENCES author_entities(id),observed_name TEXT NOT NULL,link_basis TEXT NOT NULL,PRIMARY KEY(paper_id,position));
    CREATE TABLE institution_entities(id TEXT PRIMARY KEY,display_name TEXT NOT NULL,ror TEXT,openalex_id TEXT,country_code TEXT,type TEXT,identity_status TEXT NOT NULL,publication_count INTEGER NOT NULL DEFAULT 0);
    CREATE TABLE institution_aliases(institution_id TEXT NOT NULL REFERENCES institution_entities(id),name TEXT NOT NULL,normalized_name TEXT NOT NULL,PRIMARY KEY(institution_id,name));
    CREATE TABLE affiliations(paper_id TEXT NOT NULL,position INTEGER NOT NULL,institution_id TEXT NOT NULL REFERENCES institution_entities(id),provider TEXT NOT NULL,link_basis TEXT NOT NULL,raw_name TEXT NOT NULL,evidence_json TEXT NOT NULL,FOREIGN KEY(paper_id,position) REFERENCES authorships(paper_id,position),PRIMARY KEY(paper_id,position,institution_id,provider,raw_name));
    CREATE TABLE publication_events(paper_id TEXT NOT NULL REFERENCES papers(id),basis TEXT NOT NULL,date TEXT NOT NULL,date_lower TEXT NOT NULL,date_upper TEXT NOT NULL,precision TEXT NOT NULL,provider TEXT NOT NULL,PRIMARY KEY(paper_id,basis));
    CREATE TABLE identity_conflicts(id INTEGER PRIMARY KEY,details_json TEXT NOT NULL);
    CREATE VIRTUAL TABLE entity_names USING fts5(kind UNINDEXED,entity_id UNINDEXED,name,tokenize='unicode61 remove_diacritics 2');
    CREATE INDEX author_alias_normalized ON author_aliases(normalized_name,author_id);
    CREATE INDEX authorship_author_paper ON authorships(author_id,paper_id);
    CREATE INDEX affiliation_institution_paper ON affiliations(institution_id,paper_id);
    CREATE INDEX institution_alias_normalized ON institution_aliases(normalized_name,institution_id);
    CREATE INDEX publication_event_period ON publication_events(basis,date_lower,date_upper,paper_id);
    CREATE INDEX publication_event_paper ON publication_events(paper_id,basis);
    CREATE INDEX IF NOT EXISTS papers_date ON papers(date);
    CREATE INDEX IF NOT EXISTS papers_entry_type ON papers(entry_type);
    """)
    con.executemany(
        "INSERT INTO author_entities(id,display_name,identity_status) VALUES(?,?,?)",
        [
            (p["id"], max(p["names"], key=lambda n: (p["names"][n], len(n))), p["status"])
            for p in persons.values()
        ],
    )
    con.executemany("INSERT INTO author_aliases VALUES(?,?,?,?)", sorted(alias_rows))
    id_rows = [(v, groups.root(v)) for v in groups.parents if groups.root(v) in persons]
    con.executemany("INSERT INTO author_identifiers VALUES(?,?)", id_rows)
    used_institutions = {a[2] for a in affiliation_rows}
    for identity in sorted(used_institutions):
        i = institution_candidates[identity]
        con.execute(
            "INSERT INTO institution_entities(id,display_name,ror,openalex_id,country_code,type,identity_status) VALUES(?,?,?,?,?,?,?)",
            (
                identity,
                i["name"],
                i["ror"],
                i["openalex_id"],
                i["country_code"],
                i["type"],
                "source_identified"
                if not identity.startswith("unresolved-")
                else "unresolved_label",
            ),
        )
    for identity, i in institution_candidates.items():
        target = institution_map[identity]
        if target in used_institutions:
            con.executemany(
                "INSERT OR IGNORE INTO institution_aliases VALUES(?,?,?)",
                [(target, alias, normalized_name(alias)) for alias in i["aliases"]],
            )
    con.executemany("INSERT INTO authorships VALUES(?,?,?,?,?)", authorship_rows)
    con.execute(
        "INSERT INTO entity_names SELECT DISTINCT 'author',author_id,name FROM author_aliases"
    )
    con.execute(
        "INSERT INTO entity_names SELECT DISTINCT 'institution',institution_id,name FROM institution_aliases"
    )
    con.executemany("INSERT OR IGNORE INTO affiliations VALUES(?,?,?,?,?,?,?)", affiliation_rows)
    con.executemany("INSERT INTO publication_events VALUES(?,?,?,?,?,?,?)", events)
    con.executemany(
        "INSERT INTO identity_conflicts(details_json) VALUES(?)",
        [(json.dumps(c),) for c in groups.conflicts],
    )
    con.execute(
        "UPDATE author_entities SET publication_count=(SELECT COUNT(DISTINCT paper_id) FROM authorships WHERE author_id=author_entities.id)"
    )
    con.execute(
        "UPDATE institution_entities SET publication_count=(SELECT COUNT(DISTINCT paper_id) FROM affiliations WHERE institution_id=institution_entities.id)"
    )
    author_directory.build(con)
    con.commit()
    report = {
        "built_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "scope": "The journals in the local catalog; not all worldwide publications.",
        "author_entities": con.execute("SELECT COUNT(*) FROM author_entities").fetchone()[0],
        "identified_author_entities": con.execute(
            "SELECT COUNT(*) FROM author_entities WHERE identity_status='source_identified'"
        ).fetchone()[0],
        "unresolved_author_credits": con.execute(
            "SELECT COUNT(*) FROM author_entities WHERE identity_status!='source_identified'"
        ).fetchone()[0],
        "authorships": len(authorship_rows),
        "institution_entities": len(used_institutions),
        "identified_institutions": con.execute(
            "SELECT COUNT(*) FROM institution_entities WHERE identity_status='source_identified'"
        ).fetchone()[0],
        "papers_with_affiliations": con.execute(
            "SELECT COUNT(DISTINCT paper_id) FROM affiliations"
        ).fetchone()[0],
        "author_identifier_conflicts": len(groups.conflicts),
        "recovered_evidence": dict(matched),
        "unmatched_source_credits": dict(unmatched),
        "elapsed_seconds": round(time.perf_counter() - started, 2),
        "affiliation_semantics": "Institution on a particular paper's source byline, not an author's current employer.",
        "identity_semantics": "Provider identifiers; same names are not automatically merged into a person. Provider disambiguation may contain errors.",
    }
    assert (
        con.execute("SELECT COUNT(*) FROM authors").fetchone()[0]
        == con.execute("SELECT COUNT(*) FROM authorships").fetchone()[0]
    )
    assert not con.execute("PRAGMA foreign_key_check").fetchall()
    export_entities(con)
    con.close()
    (ROOT / "entity-coverage.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False), flush=True)
    return report


def export_entities(con):
    for filename, table in [
        ("author-entities.jsonl", "author_entities"),
        ("author-directory.jsonl", "author_directory"),
        ("author-identifiers.jsonl", "author_identifiers"),
        ("author-aliases.jsonl", "author_aliases"),
        ("authorships.jsonl", "authorships"),
        ("institution-entities.jsonl", "institution_entities"),
        ("institution-aliases.jsonl", "institution_aliases"),
        ("affiliations.jsonl", "affiliations"),
        ("publication-events.jsonl", "publication_events"),
    ]:
        tmp = ROOT / (filename + ".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            for row in con.execute("SELECT * FROM " + table):
                f.write(json.dumps(dict(row), ensure_ascii=False) + "\n")
        tmp.replace(ROOT / filename)


def entity_search(kind, query="", limit=30, offset=0, con=None):
    own = con is None
    con = con or connect(True)
    query = str(query or "").strip()
    if kind == "author":
        table = "author_entities"
    elif kind == "institution":
        table = "institution_entities"
    else:
        raise ValueError("Entity kind must be author or institution")
    where, params = "", []
    if query:
        tokens = normalized_name(query).split()
        identity = (
            identifier(query, "orcid") or identifier(query, "openalex") or identifier(query, "ror")
        )
        if kind == "author":
            exact = (
                "e.id=? OR e.id IN (SELECT author_id FROM author_identifiers WHERE identifier=?)"
            )
        else:
            exact = "e.id=? OR e.openalex_id=?"
        if identity or query.startswith("unresolved-"):
            where, params = " WHERE " + exact, [identity or query, identity or query]
        elif tokens:
            expression = " AND ".join('"' + t + '"*' for t in tokens)
            where = " WHERE e.id IN (SELECT entity_id FROM entity_names WHERE entity_names MATCH ? AND kind=?)"
            params = [expression, kind]
        else:
            where = " WHERE 0"
    total = con.execute(f"SELECT COUNT(*) FROM {table} e" + where, params).fetchone()[0]
    if kind == "author" and author_directory.exists(con):
        selected = "SELECT e.*,d.family_name,d.given_names,d.sort_key,d.surname_source FROM author_entities e JOIN author_directory d ON d.author_id=e.id"
        order = "d.sort_key,e.id"
    else:
        selected = f"SELECT e.* FROM {table} e"
        con.create_function(
            "author_surname_key", 1, author_directory.inferred_sort_key, deterministic=True
        )
        order = (
            "author_surname_key(e.display_name),e.id"
            if kind == "author"
            else "e.publication_count DESC,e.display_name,e.id"
        )
    rows = con.execute(
        selected + where + " ORDER BY " + order + " LIMIT ? OFFSET ?", [*params, limit, offset]
    ).fetchall()
    if own:
        con.close()
    return {"kind": kind, "query": query, "total": total, "items": [dict(r) for r in rows]}


def add_author_links(con, items):
    """Attach the first ten exact ordered identities to compact result rows."""
    by_id = {item["id"]: item for item in items if item.get("authors")}
    for item in items:
        authors = item.get("authors") or []
        item["author_count"] = item.get("author_count", len(authors))
        item["authors"] = authors[:10]
        item["author_entities"] = []
    ids = list(by_id)
    for start in range(0, len(ids), 400):
        chunk = ids[start : start + 400]
        marks = ",".join("?" for _ in chunk)
        rows = con.execute(
            f"SELECT a.paper_id,a.position,a.author_id,e.display_name,e.identity_status FROM authorships a JOIN author_entities e ON e.id=a.author_id WHERE a.paper_id IN ({marks}) AND a.position<=10 ORDER BY a.paper_id,a.position",
            chunk,
        )
        for row in rows:
            item = by_id[row["paper_id"]]
            names = item["authors"]
            observed = (
                names[row["position"] - 1] if row["position"] <= len(names) else row["display_name"]
            )
            item["author_entities"].append(
                {
                    "position": row["position"],
                    "observed_name": observed,
                    "author_id": row["author_id"],
                    "identity_status": row["identity_status"],
                }
            )
    return items


def resolve_entity(kind, value, con):
    if kind not in ["author", "institution"]:
        raise ValueError("Entity kind must be author or institution")
    table = "author_entities" if kind == "author" else "institution_entities"
    value = (
        identifier(value, "orcid")
        or identifier(value, "openalex")
        or identifier(value, "ror")
        or value
    )
    row = con.execute(f"SELECT * FROM {table} WHERE id=?", (value,)).fetchone()
    if not row and kind == "author":
        row = con.execute(
            "SELECT e.* FROM author_identifiers i JOIN author_entities e ON e.id=i.author_id WHERE i.identifier=?",
            (value,),
        ).fetchone()
    if not row and kind == "institution":
        row = con.execute(
            "SELECT * FROM institution_entities WHERE openalex_id=?", (value,)
        ).fetchone()
    if row:
        return dict(row)
    alias_table, field = (
        ("author_aliases", "author_id")
        if kind == "author"
        else ("institution_aliases", "institution_id")
    )
    exact = [
        dict(r)
        for r in con.execute(
            f"SELECT e.* FROM {table} e WHERE e.id IN (SELECT {field} FROM {alias_table} WHERE normalized_name=?)",
            (normalized_name(value),),
        )
    ]
    result = entity_search(kind, value, limit=20, con=con) if not exact else None
    choices = exact or result["items"]
    if len(choices) == 1 and (exact or result["total"] == 1):
        return choices[0]
    raise ValueError(
        json.dumps(
            {
                "message": "Choose an explicit entity ID; this name is missing or ambiguous.",
                "kind": kind,
                "query": value,
                "candidates": choices[:20],
            },
            ensure_ascii=False,
        )
    )


def entity_profile(con, kind, entity_id):
    """Whole-catalog overview for a profile: papers per year, journals and frequent coauthors."""
    relation, field = (
        ("authorships", "author_id") if kind == "author" else ("affiliations", "institution_id")
    )
    related = f"SELECT DISTINCT paper_id FROM {relation} WHERE {field}=?"
    years = {
        str(y): n
        for y, n in con.execute(
            f"SELECT json_extract(record_json,'$.year') y,COUNT(*) FROM papers WHERE id IN ({related}) AND y IS NOT NULL GROUP BY y",
            (entity_id,),
        )
    }
    journals = [
        list(r)
        for r in con.execute(
            f"SELECT journal_id,COUNT(*) n FROM papers WHERE id IN ({related}) GROUP BY journal_id ORDER BY n DESC,journal_id",
            (entity_id,),
        )
    ]
    coauthors = []
    if kind == "author":
        coauthors = [
            dict(id=r[0], name=r[1], papers=r[2])
            for r in con.execute(
                "SELECT b.author_id,e.display_name,COUNT(DISTINCT a.paper_id) n FROM authorships a JOIN authorships b ON b.paper_id=a.paper_id AND b.author_id<>a.author_id AND b.position<=10 "
                "JOIN author_entities e ON e.id=b.author_id WHERE a.author_id=? AND e.identity_status<>'unresolved_credit' GROUP BY b.author_id ORDER BY n DESC,e.display_name LIMIT 8",
                (entity_id,),
            )
        ]
    return {"years": years, "journals": journals, "coauthors": coauthors}


def publication_query(
    kind,
    value,
    period="last-quarter",
    basis="issue",
    as_of=None,
    include_uncertain=False,
    limit=100,
    offset=0,
    con=None,
    start_date=None,
    end_date=None,
    stage="",
):
    if kind not in ["author", "institution"] or basis not in ["issue", "online", "print"]:
        raise ValueError("Invalid entity kind or date basis")
    own = con is None
    con = con or connect(True)
    try:
        entity = resolve_entity(kind, value, con)
        lower, upper, label = period_bounds(period, as_of, start_date, end_date)
        all_years = period == "all" and not start_date and not end_date
        relation, field = (
            ("authorships", "author_id") if kind == "author" else ("affiliations", "institution_id")
        )
        stage_where = publication_status.where(stage)
        related = (
            f"SELECT DISTINCT rel.paper_id FROM {relation} rel JOIN papers p ON p.id=rel.paper_id WHERE rel.{field}=?"
            + (" AND " + stage_where if stage_where else "")
        )
        certainty = "ev.date_lower>=? AND ev.date_upper<=?"
        overlaps = "ev.date_lower<=? AND ev.date_upper>=?"
        summary = con.execute(
            f"SELECT COUNT(*) AS possible_total,SUM(CASE WHEN {certainty} THEN 1 ELSE 0 END) AS certain_total FROM publication_events ev WHERE ev.basis=? AND ev.paper_id IN ({related}) AND {overlaps}",
            (lower, upper, basis, entity["id"], upper, lower),
        ).fetchone()
        certain = summary["certain_total"] or 0
        possible = summary["possible_total"] - certain
        rows_where = overlaps if include_uncertain else certainty
        date_values = (upper, lower) if include_uncertain else (lower, upper)
        membership_values = (lower, upper)
        if all_years:
            # A complete bibliography includes papers whose publication date is missing.
            certain = con.execute(f"SELECT COUNT(*) FROM ({related})", (entity["id"],)).fetchone()[
                0
            ]
            possible, certainty, rows_where = 0, "1", "1"
            date_values, membership_values = (), ()
        rows = con.execute(
            f"SELECT p.id,p.title,p.journal_id,j.title AS journal,p.doi,p.volume,p.issue,json_extract(p.record_json,'$.volume_series') AS volume_series,json_extract(p.record_json,'$.publication_unit') AS publication_unit,json_extract(p.record_json,'$.article_number') AS article_number,p.pages,p.authors_json,p.cairn_slug,p.entry_type,p.publication_status,p.publication_status_evidence,ev.date AS publication_date,ev.precision AS date_precision,ev.provider AS date_source,CASE WHEN {certainty} THEN 'certain' ELSE 'uncertain' END AS period_membership FROM papers p JOIN journals j ON j.id=p.journal_id LEFT JOIN publication_events ev ON ev.paper_id=p.id AND ev.basis=? WHERE p.id IN ({related}) AND {rows_where} ORDER BY ev.date_lower DESC,p.title,p.id LIMIT ? OFFSET ?",
            (*membership_values, basis, entity["id"], *date_values, limit, offset),
        ).fetchall()
        missing = con.execute(
            f"SELECT COUNT(*) FROM papers p WHERE p.id IN ({related}) AND NOT EXISTS(SELECT 1 FROM publication_events ev WHERE ev.paper_id=p.id AND ev.basis=?)",
            (entity["id"], basis),
        ).fetchone()[0]
        items = []
        for row in rows:
            r = dict(row)
            r["authors"] = json.loads(r.pop("authors_json"))
            items.append(r)
        add_author_links(con, items)
        return {
            "entity": entity,
            "profile": entity_profile(con, kind, entity["id"]),
            "period": label,
            "period_mode": "all" if all_years else "range",
            "start_date": lower,
            "end_date": upper,
            "basis": basis,
            "scope": "The journals in this local catalog",
            "certain_count": certain,
            "uncertain_count": possible,
            "total": certain + (possible if include_uncertain else 0),
            "include_uncertain": include_uncertain,
            "undated_publications_all_years": missing,
            "items": items,
            "affiliation_note": "Paper-level source affiliations; not current employer"
            if kind == "institution"
            else None,
        }
    finally:
        if own:
            con.close()


def import_entity(kind, value):
    from . import catalog

    with closing(connect(True)) as con:
        entity = resolve_entity(kind, value, con)
        result = publication_query(
            kind, entity["id"], period="all", include_uncertain=True, limit=100000, con=con
        )
    kb = catalog.open_kb()
    title = (
        ("Author: " if kind == "author" else "Institution: ")
        + entity["display_name"]
        + " — "
        + entity["id"]
    )
    prior = kb.resolve(title)
    lines = [
        f"# {entity['display_name']}",
        "",
        f"Catalog identity: `{entity['id']}`. Identity status: `{entity['identity_status']}`.",
        "",
        "Scope: publications in the catalog journals. This is a source-identified entity, not a verified complete personal bibliography.",
    ]
    if kind == "institution":
        lines.append(
            "Institution membership is the affiliation attached to each paper's source byline, not the author's present employer."
        )
    lines.extend(["", "## Publications", ""])
    for p in result["items"]:
        path = catalog.ROOT / "cairn-library/research/papers" / (p["cairn_slug"] + ".md")
        lines.append(
            f"- [{p['title']}]({path}) — {p['journal']}; {p['publication_date'] or 'date unavailable'}; DOI: {p['doi'] or 'unavailable'}."
        )
    lines.extend(["", "## Personal notes", "", "No personal interpretation recorded."])
    if prior:
        return {"status": "preserved_existing_note", "slug": prior.slug, "path": str(prior.path)}
    return kb.save(
        kind="note",
        title=title,
        body="\n".join(lines),
        aliases=[entity["id"]],
        topics=["Research catalogs"],
        fields={
            "catalog_entity_id": entity["id"],
            "catalog_entity_kind": kind,
            "identity_status": entity["identity_status"],
        },
    )


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("build")
    s = sub.add_parser("search")
    s.add_argument("kind", choices=["author", "institution"])
    s.add_argument("query", nargs="?", default="")
    s.add_argument("--limit", type=int, default=30)
    q = sub.add_parser("publications")
    q.add_argument("kind", choices=["author", "institution"])
    q.add_argument("entity")
    q.add_argument("--period", default="last-quarter")
    q.add_argument("--basis", choices=["issue", "online", "print"], default="issue")
    q.add_argument("--as-of")
    q.add_argument("--start-date")
    q.add_argument("--end-date")
    q.add_argument(
        "--stage",
        choices=["all", "issue_assigned", "online_first", "pending", "unassigned"],
        default="all",
    )
    q.add_argument("--include-uncertain", action="store_true")
    q.add_argument("--limit", type=int, default=100)
    i = sub.add_parser("import")
    i.add_argument("kind", choices=["author", "institution"])
    i.add_argument("entity")
    args = p.parse_args(argv)
    if args.command == "build":
        build_entities()
        return
    if args.command == "search":
        value = entity_search(args.kind, args.query, args.limit)
    elif args.command == "import":
        value = import_entity(args.kind, args.entity)
    else:
        value = publication_query(
            args.kind,
            args.entity,
            args.period,
            args.basis,
            args.as_of,
            args.include_uncertain,
            args.limit,
            start_date=args.start_date,
            end_date=args.end_date,
            stage=args.stage,
        )
    print(json.dumps(value, ensure_ascii=False, indent=2))
