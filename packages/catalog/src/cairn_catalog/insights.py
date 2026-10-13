#!/usr/bin/env python3
"""Per-field discovery summaries: active authors, new names, institutions and rising title terms.

Periods end at the snapshot and use each paper's earliest known publication bounds,
like the What's New feed. Only certain placements count. Author and institution
rankings use source-identified identities; unresolved credits are single bylines,
not people, and are excluded.
"""

import json
import math
import re
import sqlite3
import unicodedata
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

from . import discovery, entities, paths

ROOT = paths.data_dir()
PERIODS = {"3m": 3, "12m": 12}
SPARK_BINS = 8
STOPWORDS = set(
    """
a about above across after against all along also among an and any are as at be been before being between both but by can
could do does during each either for from further had has have how however if in into is it its itself may more most new no
non nor not of off on once one only or other our out over own per same should so some such than that the their them then
there these they this those through to too toward towards two under until up upon us use used using via was we were what
when where whether which while who whom why will with within without would yet
analysis application applications approach approaches based beyond case comment correction effect effects erratum evidence
general generalized introduction new note problem problems properties reply result results role some study theory three
toward using via class classes method methods model models paper part results second first under when large small
your make making improve improving improved better matter matters really what why how versus vs
perspective long studies governed lead area mathbb mathcal mathrm
""".split()
)
# Editorial and discussion pieces repeat a parent title; they are not research topics.
EDITORIAL = re.compile(
    r"^(?:discussion|contribution|reply|rejoinder|comment|comments|correction|corrigendum|erratum|errata|editorial|"
    r"in memoriam|obituary|preface|foreword|announcement|report of|acknowledg)|contribution to the discussion|discussion of",
    re.I,
)


def months_before(day, months):
    return entities.shift_months(date.fromisoformat(day), -months).isoformat()


def period(as_of, months):
    start = date.fromisoformat(months_before(as_of, months)).toordinal() + 1
    return date.fromordinal(start).isoformat(), as_of


def words(title):
    text = "".join(
        c
        for c in unicodedata.normalize("NFKD", title or "")
        if not unicodedata.category(c).startswith("M")
    ).lower()
    text = re.sub(r"<[^>]+>|\$[^$]*\$|\\[a-z]+", " ", text)
    return re.findall(r"[a-z][a-z\-']+[a-z]|[a-z]{3,}", text)


def terms(title):
    """Content unigrams and adjacent bigrams; stopwords break bigrams."""
    found, previous = set(), None
    for word in words(title):
        if word in STOPWORDS or len(word) < 3:
            previous = None
            continue
        found.add(word)
        if previous:
            found.add(previous + " " + word)
        previous = word
    return found


def research_titles(papers):
    """Drop editorial pieces and recurring series labels such as "Frontiers in Operations:"."""
    # Example selection and near-copy suppression consume this order. SQLite may
    # choose a different plan after PRAGMA optimize; identity order stays stable.
    papers = sorted((i, t or "") for i, t in papers if not EDITORIAL.search((t or "").strip()))
    prefixes = Counter(t.split(":", 1)[0].strip().lower() for _, t in papers if ":" in t)
    return [
        (
            i,
            t.split(":", 1)[1]
            if ":" in t and prefixes[t.split(":", 1)[0].strip().lower()] >= 3
            else t,
        )
        for i, t in papers
    ]


def distinct_count(term_sets):
    """Count titles that are not near-copies of an already counted title (Jaccard >= 0.5)."""
    kept = []
    for tokens in term_sets:
        if all(len(tokens & k) / max(1, len(tokens | k)) < 0.5 for k in kept):
            kept.append(tokens)
    return len(kept)


def rising_terms(current, baseline, limit=12):
    """Title terms over-represented in the period relative to the preceding twelve months."""
    current, baseline = research_titles(current), research_titles(baseline)
    n_now, n_base = len(current), len(baseline)
    if not n_now:
        return []
    now, base, examples, holders = Counter(), Counter(), defaultdict(list), defaultdict(list)
    for paper_id, title in current:
        found = terms(title)
        for term in found:
            now[term] += 1
            holders[term].append(frozenset(w for w in found if " " not in w))
            if len(examples[term]) < 3:
                examples[term].append(paper_id)
    for _, title in baseline:
        base.update(terms(title))
    scored = []
    for term, count in now.items():
        if count < 3:
            continue
        count = distinct_count(holders[term])
        if count < 3:
            continue
        # Additive smoothing keeps terms absent from the baseline from dominating.
        lift = (count / n_now) / ((base[term] + 1) / (n_base + 1))
        if lift <= 1.5:
            continue
        scored.append((math.log(lift) * math.sqrt(count), term, count))
    scored.sort(key=lambda x: (-x[0], x[1]))
    chosen = []
    for _score, term, count in scored:
        # Prefer a phrase to its own words when the phrase explains most of the word's rise.
        if " " not in term and any(
            term in c["term"].split() and c["count"] >= 0.6 * count for c in chosen
        ):
            continue
        chosen.append(dict(term=term, count=count, baseline=base[term], examples=examples[term]))
        if len(chosen) >= limit:
            break
    return chosen


def build(con, as_of=None):
    con.row_factory = sqlite3.Row
    as_of = (
        as_of
        or json.loads(
            (
                Path(con.execute("PRAGMA database_list").fetchone()["file"]).with_name(
                    "coverage.json"
                )
            ).read_text()
        )["as_of"]
    )
    field_of = discovery.journal_fields()
    history_start = period(as_of, 24)[0]
    papers = {}
    for r in con.execute(
        """
        SELECT p.id,p.journal_id,p.title,e.lo,e.hi FROM papers p JOIN (
            SELECT paper_id,MIN(date_lower) lo,MIN(date_upper) hi FROM publication_events GROUP BY paper_id
        ) e ON e.paper_id=p.id
        WHERE e.lo>=? AND e.hi<=? AND p.entry_type IN ('article','article_or_other')""",
        (history_start, as_of),
    ):
        papers[r["id"]] = dict(r, field=field_of.get(r["journal_id"], {}).get("field"))
    ids = list(papers)
    con.execute("CREATE TEMP TABLE IF NOT EXISTS insight_papers(id TEXT PRIMARY KEY)")
    con.execute("DELETE FROM insight_papers")
    con.executemany("INSERT INTO insight_papers VALUES(?)", [(i,) for i in ids])
    credits, names = defaultdict(set), {}
    for r in con.execute("""SELECT a.paper_id,a.author_id,e.display_name FROM authorships a JOIN insight_papers t ON t.id=a.paper_id
                            JOIN author_entities e ON e.id=a.author_id WHERE e.identity_status='source_identified' """):
        credits[r["author_id"]].add(r["paper_id"])
        names[r["author_id"]] = r["display_name"]
    by_paper_authors = defaultdict(list)
    for author, paper_ids in credits.items():
        for paper_id in paper_ids:
            by_paper_authors[paper_id].append(author)
    con.execute("CREATE TEMP TABLE IF NOT EXISTS insight_authors(id TEXT PRIMARY KEY)")
    con.execute("DELETE FROM insight_authors")
    con.executemany("INSERT INTO insight_authors VALUES(?)", [(a,) for a in credits])
    # Earliest certain-or-not lower bound across the whole catalog marks a first appearance.
    debut = dict(
        con.execute("""SELECT a.author_id,MIN(e.date_lower) FROM authorships a JOIN insight_authors t ON t.id=a.author_id
                                JOIN publication_events e ON e.paper_id=a.paper_id GROUP BY a.author_id""")
    )
    affiliated, institutions, institution_names = set(), defaultdict(set), {}
    for r in con.execute("""SELECT DISTINCT f.paper_id,f.institution_id,i.display_name FROM affiliations f JOIN insight_papers t ON t.id=f.paper_id
                            JOIN institution_entities i ON i.id=f.institution_id WHERE i.identity_status='source_identified' """):
        affiliated.add(r["paper_id"])
        institutions[r["institution_id"]].add(r["paper_id"])
        institution_names[r["institution_id"]] = r["display_name"]
    by_paper_institutions = defaultdict(list)
    for institution, paper_ids in institutions.items():
        for paper_id in paper_ids:
            by_paper_institutions[paper_id].append(institution)
    con.execute("DROP TABLE insight_papers")
    con.execute("DROP TABLE insight_authors")

    def within(paper_id, start, end):
        p = papers[paper_id]
        return start <= p["lo"] and p["hi"] <= end

    bins = [period(months_before(as_of, 3 * k), 3) for k in reversed(range(SPARK_BINS))]
    referenced = set()
    result = dict(as_of=as_of, periods={}, fields={}, papers={})
    for key, months in PERIODS.items():
        start, end = period(as_of, months)
        previous = period(months_before(as_of, months), months)
        # Rising terms compare with the twelve months before the period.
        baseline = (
            period(start, 12)[0],
            date.fromordinal(date.fromisoformat(start).toordinal() - 1).isoformat(),
        )
        result["periods"][key] = dict(
            start=start,
            end=end,
            previous_start=previous[0],
            previous_end=previous[1],
            baseline_start=baseline[0],
            baseline_end=baseline[1],
        )
        for field in discovery.fields():
            fid = field["id"]
            current = [i for i, p in papers.items() if p["field"] == fid and within(i, start, end)]
            prior = [i for i, p in papers.items() if p["field"] == fid and within(i, *previous)]
            base = [i for i, p in papers.items() if p["field"] == fid and within(i, *baseline)]
            current_set = set(current)
            author_counts = Counter(a for i in current for a in by_paper_authors[i])
            active = []
            for author, count in sorted(
                author_counts.items(), key=lambda x: (-x[1], names[x[0]], x[0])
            ):
                if count < 2 or len(active) >= 15:
                    break
                mine = sorted(credits[author], key=lambda i: (papers[i]["lo"], i))
                latest = [i for i in mine if i in current_set][-1]
                referenced.add(latest)
                active.append(
                    dict(
                        id=author,
                        name=names[author],
                        count=count,
                        journals=Counter(
                            papers[i]["journal_id"] for i in mine if i in current_set
                        ).most_common(),
                        spark=[sum(within(i, *b) for i in mine) for b in bins],
                        latest=latest,
                    )
                )
            newcomers = []
            for author in author_counts:
                first = debut.get(author)
                if not first or first < start:
                    continue
                mine = sorted(
                    (i for i in credits[author] if i in current_set),
                    key=lambda i: (papers[i]["lo"], i),
                )
                newcomers.append(
                    dict(
                        id=author,
                        name=names[author],
                        first=first,
                        papers=len(mine),
                        paper=mine[0],
                        coauthors=len(by_paper_authors[mine[0]]) - 1,
                    )
                )
            newcomers.sort(key=lambda x: (-x["papers"], x["first"], x["name"], x["id"]))
            newcomers = sorted(
                newcomers[:30], key=lambda x: (x["first"], x["name"], x["id"]), reverse=True
            )
            referenced.update(n["paper"] for n in newcomers)
            inst_now = Counter(n for i in current for n in by_paper_institutions[i])
            inst_before = Counter(n for i in prior for n in by_paper_institutions[i])
            top = [
                dict(id=n, name=institution_names[n], count=c, previous=inst_before[n])
                for n, c in sorted(
                    inst_now.items(), key=lambda x: (-x[1], institution_names[x[0]], x[0])
                )[:20]
            ]
            rising = rising_terms(
                [(i, papers[i]["title"]) for i in current], [(i, papers[i]["title"]) for i in base]
            )
            for term in rising:
                referenced.update(term["examples"])
            result["fields"].setdefault(fid, {})[key] = dict(
                papers=len(current),
                previous_papers=len(prior),
                identified_authors=len(author_counts),
                affiliation_coverage=round(sum(i in affiliated for i in current) / len(current), 3)
                if current
                else None,
                active_authors=active,
                new_authors=newcomers,
                institutions=top,
                rising_terms=rising,
            )
    result["papers"] = {
        i: dict(title=papers[i]["title"], journal_id=papers[i]["journal_id"], date=papers[i]["lo"])
        for i in sorted(referenced)
    }
    return result
