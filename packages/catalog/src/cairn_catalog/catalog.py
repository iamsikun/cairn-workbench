#!/usr/bin/env python3
"""Harvest public journal metadata, build a catalog, and materialize Cairn notes.

Run with the system Python (requests, PyYAML and beautifulsoup4), or use the
installed Cairn Python for the import command. Network harvests are checkpointed.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import gc
import gzip
import hashlib
import html
import json
import os
import re
import sqlite3
import time
import unicodedata
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from . import journal_membership, paths, publication_status

ROOT = paths.data_dir()
WORKSPACE = paths.workspace()
COLLECTION = paths.collection()
AS_OF = datetime.now(ZoneInfo("America/Chicago")).date().isoformat()
JOURNALS = paths.journals(ROOT)


def now():
    return datetime.now(UTC).isoformat(timespec="seconds")


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


class Client:
    def __init__(self, interval):
        import requests

        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "CairnJournalCatalog/1.0 (public bibliographic metadata; local research catalog)",
                "Accept": "application/json",
            }
        )
        self.interval = interval
        self.last = 0
        self.unavailable = None
        self.unavailable_until = 0

    def get(self, url, params=None):
        if self.unavailable and time.monotonic() < self.unavailable_until:
            raise RuntimeError(self.unavailable)
        self.unavailable = None
        for attempt in range(8):
            time.sleep(max(0, self.interval - (time.monotonic() - self.last)))
            self.last = time.monotonic()
            try:
                r = self.session.get(url, params=params, timeout=90)
                if r.status_code == 429 or r.status_code >= 500:
                    retry_after = float(r.headers.get("Retry-After", 0) or 0)
                    if r.status_code == 429 and retry_after > 60:
                        self.unavailable = (
                            f"HTTP 429 from {url}; Retry-After {retry_after:g} seconds. "
                            + r.text[:400]
                        )
                        self.unavailable_until = time.monotonic() + retry_after
                        raise RuntimeError(self.unavailable)
                    delay = min(
                        60, max(float(r.headers.get("Retry-After", 0) or 0), 2 ** (attempt + 1))
                    )
                    print(f"Retry {r.status_code}: {url} in {delay:g}s", flush=True)
                    time.sleep(delay)
                    continue
                if r.status_code >= 400:
                    raise RuntimeError(f"HTTP {r.status_code} from {url}: {r.text[:400]}")
                return r
            except self._retry_errors() as e:
                if attempt == 7:
                    raise
                print(f"Retry {type(e).__name__}: {url}", flush=True)
                time.sleep(min(60, 2 ** (attempt + 1)))
        raise RuntimeError(f"Retries exhausted: {url}")

    @staticmethod
    def _retry_errors():
        import requests

        return (requests.ConnectionError, requests.Timeout)


def harvest_service(service, refresh=False, only=None, root=None, journals=None, client=None):
    root = Path(root or ROOT)
    client = client or Client(1.0 if service == "crossref" else 0.3)
    for j in journals if journals is not None else JOURNALS:
        if only and j["id"] not in only:
            continue
        folder = root / "raw" / service / j["id"]
        folder.mkdir(parents=True, exist_ok=True)
        state_path = folder / "state.json"
        state = (
            json.loads(state_path.read_text())
            if state_path.exists() and not refresh
            else {"pages": 0, "retrieved": 0, "cursor": "*", "complete": False, "started_at": now()}
        )
        if state.get("complete"):
            print(f"{service} {j['id']}: cached {state['retrieved']:,}", flush=True)
            continue
        if not state.get("cursor"):
            state["cursor"] = "*"
        try:
            if service == "crossref":
                profile = client.get(f"https://api.crossref.org/journals/{j['issns'][0]}").json()
                atomic_json(folder / "journal.json", profile)
                url = "https://api.crossref.org/works"
                params = {
                    "filter": ",".join("issn:" + i for i in j["issns"]),
                    "rows": 1000,
                    "select": "DOI,title,author,abstract,volume,issue,page,article-number,ISSN,container-title,published,published-print,published-online,issued,URL,resource,publisher,type,created,indexed,update-to,relation,license",
                }
                item_key, meta_key, count_key, cursor_key, page_size = (
                    "items",
                    "message",
                    "total-results",
                    "next-cursor",
                    1000,
                )
            else:
                profile = client.get(
                    f"https://api.openalex.org/sources/issn:{j['issns'][0]}"
                ).json()
                atomic_json(folder / "journal.json", profile)
                url = "https://api.openalex.org/works"
                source_ids = j.get("openalex_source_ids") or [profile["id"].rsplit("/", 1)[-1]]
                source_ids = [str(s).rsplit("/", 1)[-1] for s in source_ids]
                params = {
                    "filter": "primary_location.source.id:" + "|".join(source_ids),
                    "per-page": 200,
                    "select": "id,doi,title,publication_year,publication_date,authorships,biblio,abstract_inverted_index,primary_location,type,ids,is_retracted",
                }
                if os.environ.get("OPENALEX_API_KEY"):
                    params["api_key"] = os.environ["OPENALEX_API_KEY"]
                item_key, meta_key, count_key, cursor_key, page_size = (
                    "results",
                    "meta",
                    "count",
                    "next_cursor",
                    200,
                )
            while True:
                params["cursor"] = state["cursor"]
                result = client.get(url, params).json()
                meta = result[meta_key]
                items = meta[item_key] if service == "crossref" else result[item_key]
                state["source_total"] = meta[count_key]
                state["last_request_url"] = url
                page = state["pages"] + 1
                # Retain exactly the selected API response, with retrieval provenance.
                payload = {
                    "source": service,
                    "journal_id": j["id"],
                    "retrieved_at": now(),
                    "request": {
                        "url": url,
                        "params": {k: v for k, v in params.items() if k != "api_key"},
                    },
                    "response": result,
                }
                dest = folder / f"page-{page:05d}.json.gz"
                tmp = dest.with_suffix(".tmp")
                with gzip.open(tmp, "wt", encoding="utf-8") as f:
                    json.dump(payload, f, ensure_ascii=False)
                tmp.replace(dest)
                state["pages"] = page
                state["retrieved"] += len(items)
                state["cursor"] = meta.get(cursor_key)
                state["complete"] = len(items) < page_size or not state["cursor"]
                state["updated_at"] = now()
                state.pop("error", None)
                atomic_json(state_path, state)
                if page == 1 or page % 10 == 0 or state["complete"]:
                    print(
                        f"{service} {j['id']}: {state['retrieved']:,}/{state['source_total']:,} ({page} pages)",
                        flush=True,
                    )
                if state["complete"]:
                    break
        except Exception as e:
            state["error"] = f"{type(e).__name__}: {e}"
            atomic_json(state_path, state)
            print(f"FAILED {service} {j['id']}: {state['error']}", flush=True)


def harvest(args):
    atomic_json(ROOT / "journals.json", JOURNALS)
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(harvest_service, s, args.refresh, args.journal) for s in args.service
        ]
        for f in futures:
            f.result()


def plain(value):
    value = html.unescape(str(value or ""))
    value = re.sub(r"</(?:p|jats:p|div|br|jats:title|title)>|<br\s*/?>", "\n", value, flags=re.I)
    value = re.sub(r"<[^>]+>", "", value)
    return re.sub(r"[ \t]+", " ", value).strip()


def harvest_repec(args):
    """AER's public RePEc contents include papers absent from DOI registries."""
    client = Client(1.2)
    folder = ROOT / "raw" / "repec" / "aer"
    folder.mkdir(parents=True, exist_ok=True)
    base = "https://ideas.repec.org/s/aea/"
    first = client.get(base + "aecrev.html").text
    maximum = max([1] + [int(n) for n in re.findall(r"aecrev(\d+)\.html", first)])
    for page in range(1, maximum + 1):
        dest = folder / f"page-{page:05d}.json.gz"
        if dest.exists() and not args.refresh:
            continue
        url = base + ("aecrev.html" if page == 1 else f"aecrev{page}.html")
        text = first if page == 1 else client.get(url).text
        records = []
        headings = re.split(r"<h3[^>]*>(.*?)</h3>", text, flags=re.I | re.S)
        for heading, block in zip(headings[1::2], headings[2::2], strict=False):
            h = plain(heading)
            match = re.search(r"(\d{4}), Volume ([^,]+), Issue (.+)", h)
            if not match:
                continue
            year, volume, issue = match.groups()
            month = re.search(r"([A-Za-z]+)\s+\d{4}", h)
            months = {
                v: n
                for n, v in enumerate(
                    [
                        "January",
                        "February",
                        "March",
                        "April",
                        "May",
                        "June",
                        "July",
                        "August",
                        "September",
                        "October",
                        "November",
                        "December",
                    ],
                    1,
                )
            }
            date = f"{year}-{months[month[1]]:02d}" if month and month[1] in months else year
            for item in re.findall(
                r'<li\b[^>]*class="list-group-item[^"\n]*"[^>]*>(.*?)(?=<li\b|</ul>|$)',
                block,
                flags=re.I | re.S,
            ):
                a = re.search(
                    r'<a\b[^>]*href="(/a/aea/aecrev/[^"]+)"[^>]*>(.*?)</a>', item, flags=re.I | re.S
                )
                if not a:
                    continue
                before = plain(item[: a.start()]).strip()
                authors_match = re.search(r"<i>by</i>\s*(.*?)(?:</li>|$)", item, flags=re.I | re.S)
                authors = (
                    [plain(n) for n in re.split(r"\s+&(?:amp;)?\s+", authors_match[1])]
                    if authors_match
                    else []
                )
                records.append(
                    {
                        "title": plain(a[2]),
                        "authors": authors,
                        "year": int(year),
                        "date": date,
                        "volume": volume.strip(),
                        "issue": issue.strip(),
                        "pages": before,
                        "url": "https://ideas.repec.org" + a[1],
                        "issue_label": h,
                    }
                )
        with gzip.open(dest, "wt", encoding="utf-8") as f:
            json.dump(
                {
                    "source": "repec",
                    "journal_id": "aer",
                    "retrieved_at": now(),
                    "request": {"url": url},
                    "records": records,
                    "html": text,
                },
                f,
                ensure_ascii=False,
            )
        print(f"repec aer: page {page}/{maximum}, {len(records)} entries", flush=True)
    files = sorted(folder.glob("page-*.json.gz"))
    count = sum(len(json.load(gzip.open(f, "rt"))["records"]) for f in files)
    atomic_json(
        folder / "state.json",
        {
            "complete": len(files) == maximum,
            "pages": len(files),
            "source_total_pages": maximum,
            "retrieved": count,
            "updated_at": now(),
        },
    )


def harvest_publisher(args):
    """Record all currently public AEA issue links for completeness checks."""
    client = Client(1.2)
    text = client.get(JOURNALS[0]["url"]).text
    issues = []
    months = {
        v: n
        for n, v in enumerate(
            [
                "January",
                "February",
                "March",
                "April",
                "May",
                "June",
                "July",
                "August",
                "September",
                "October",
                "November",
                "December",
            ],
            1,
        )
    }
    for path, label in re.findall(
        r"<a\b[^>]*href=['\"](/issues/\d+)['\"][^>]*>(.*?)</a>", text, re.S | re.I
    ):
        label = plain(label)
        m = re.search(r"(\w+) (\d{4}) \(Vol\. (\d+), No\. ([^)]+)\)", label)
        if m:
            month, year, volume, issue = m.groups()
            issues.append(
                {
                    "journal_id": "aer",
                    "year": int(year),
                    "volume": volume,
                    "issue": issue,
                    "date": f"{year}-{months[month]:02d}",
                    "url": "https://www.aeaweb.org" + path,
                    "label": label,
                }
            )
    atomic_json(
        ROOT / "raw" / "publisher" / "aer-issues.json",
        {"source": JOURNALS[0]["url"], "retrieved_at": now(), "issues": issues},
    )
    print(f"AEA publisher issue index: {len(issues)} issues", flush=True)


def norm(value):
    text = unicodedata.normalize("NFKD", plain(value).casefold())
    return re.sub(r"[^a-z0-9]", "", text)


def doi(value):
    value = re.sub(
        r"^(?:https?://(?:dx\.)?doi\.org/|doi:)", "", str(value or "").strip(), flags=re.I
    ).lower()
    return value if value.startswith("10.") and "/" in value else None


def crossref_date(x, key):
    parts = (x.get(key) or {}).get("date-parts", [[]])[0]
    known = []
    for v in parts:
        if v is None:
            break
        known.append(v)
    if not known:
        return None
    return "-".join(f"{int(v):04d}" if i == 0 else f"{int(v):02d}" for i, v in enumerate(known))


def precision(value):
    return ["year", "month", "day"][value.count("-")] if value and value.count("-") < 3 else None


def inverted_abstract(index):
    if not index:
        return None
    words = {int(p): token for token, positions in index.items() for p in positions}
    return " ".join(words[p] for p in sorted(words)) or None


def entry_type(title, provider_type):
    t = title.casefold().strip()
    if re.search(
        r"^(?:front matter|back matter|about (?:the )?authors|editorial board|table of contents|contents|cover|index(?: to| of)?|advertis|masthead|announcement|contributors|errata list)\b",
        t,
    ):
        return "front_or_back_matter"
    if re.search(r"(?:\berratum\b|\berrata\b|\bcorrigendum\b|\bcorrection\b|\bretraction\b)", t):
        return "correction_or_retraction"
    if provider_type == "book-review" or re.search(
        r"^(?:book reviews?|reviews? of books|review:|reviewed work:)", t
    ):
        return "book_review"
    return "article_or_other"  # Do not assert every DOI is an original research article.


def normalized(x, provider, j, provenance):
    r = {
        "schema_version": "1.0",
        "journal_id": j["id"],
        "journal": j["title"],
        "issns": j["issns"],
        "doi": None,
        "alternate_dois": [],
        "title": None,
        "authors": [],
        "author_details": [],
        "abstract": None,
        "volume": None,
        "issue": None,
        "pages": None,
        "article_number": None,
        "date": None,
        "date_precision": None,
        "published_print": None,
        "published_online": None,
        "year": None,
        "url": None,
        "openalex_ids": [],
        "repec_urls": [],
        "archive_urls": [],
        "sources": [provenance],
        "field_sources": {},
        "source_types": [],
        "is_retracted": False,
        "publication_unit": j.get("publication_unit", "issue"),
    }
    if provider == "crossref":
        r["doi"] = doi(x.get("DOI"))
        r["title"] = plain(" ".join(x.get("title") or [])) or None
        for a in x.get("author") or []:
            name = " ".join(v for v in [a.get("given"), a.get("family")] if v) or a.get("name")
            if name:
                r["authors"].append(plain(name))
                r["author_details"].append(
                    {
                        "name": plain(name),
                        "given": a.get("given"),
                        "family": a.get("family"),
                        "orcid": a.get("ORCID"),
                        "affiliations": a.get("affiliation", []),
                    }
                )
        r["abstract"] = plain(x.get("abstract")) or None
        r["volume"], r["issue"], r["pages"], r["article_number"] = [
            str(x[k]).strip() if x.get(k) is not None else None
            for k in ["volume", "issue", "page", "article-number"]
        ]
        r["published_print"], r["published_online"] = (
            crossref_date(x, "published-print"),
            crossref_date(x, "published-online"),
        )
        date_keys = ["published-print", "published", "issued", "published-online"]
        for key in date_keys:
            if crossref_date(x, key):
                r["date"] = crossref_date(x, key)
                r["field_sources"]["date"] = "crossref:" + key
                break
        r["date_precision"] = precision(r["date"])
        r["url"] = ((x.get("resource") or {}).get("primary") or {}).get("URL") or x.get("URL")
        r["source_types"] = [x.get("type")]
        r["licenses"] = x.get("license") or []
        r["relations"] = x.get("relation") or {}
        r["update_to"] = x.get("update-to") or []
    elif provider == "openalex":
        r["doi"], r["title"] = doi(x.get("doi")), plain(x.get("title")) or None
        for a in x.get("authorships") or []:
            person = a.get("author") or {}
            name = person.get("display_name")
            if name:
                r["authors"].append(name)
                r["author_details"].append(
                    {
                        "name": name,
                        "orcid": person.get("orcid"),
                        "openalex_id": person.get("id"),
                        "affiliations": a.get("institutions", []),
                    }
                )
        r["abstract"] = inverted_abstract(x.get("abstract_inverted_index"))
        b = x.get("biblio") or {}
        r["volume"], r["issue"] = b.get("volume") or None, b.get("issue") or None
        r["pages"] = (
            "-".join(dict.fromkeys(str(p) for p in [b.get("first_page"), b.get("last_page")] if p))
            or None
        )
        r["date"] = x.get("publication_date")
        r["date_precision"] = "provider_day_unverified" if r["date"] else None
        r["year"] = x.get("publication_year")
        r["url"] = (x.get("primary_location") or {}).get("landing_page_url")
        r["openalex_ids"] = [x["id"]]
        r["source_types"] = [x.get("type")]
        r["is_retracted"] = bool(x.get("is_retracted"))
    else:
        for key in ["title", "authors", "volume", "issue", "pages", "date", "year", "url"]:
            r[key] = x.get(key)
        r["authors"] = r["authors"] or []
        r["author_details"] = [{"name": n} for n in r["authors"]]
        r["date_precision"] = precision(r["date"])
        if provider == "journal_archive":
            r["doi"] = doi(x.get("doi"))
            r["abstract"] = x.get("abstract") or None
            r["article_number"] = x.get("article_number")
            r["archive_urls"] = [x["url"]]
            r["published_print"] = x.get("published_print")
            r["published_online"] = x.get("published_online")
        else:
            r["repec_urls"] = [x["url"]]
        r["source_types"] = ["journal-article"]
    if r["date"] and not r["year"]:
        r["year"] = int(r["date"][:4])
    boundary = j.get("series_restart_year")
    if boundary and r.get("year"):
        r["volume_series"] = "first" if r["year"] < boundary else "second"
    for k in ["title", "authors", "abstract", "volume", "issue", "pages", "date", "url"]:
        if r.get(k) and k not in r["field_sources"]:
            r["field_sources"][k] = provider
    r["entry_type"] = entry_type(r["title"] or "", r["source_types"][0])
    return r


def raw_records():
    for provider in ["crossref", "repec", "journal_archive", "openalex"]:
        for j in JOURNALS:
            folder = ROOT / "raw" / provider / j["id"]
            state_file = folder / "state.json"
            if not state_file.exists():
                continue
            state = json.loads(state_file.read_text())
            if not state.get("complete") and not (
                state.get("usable_checkpoint") and state.get("incomplete_reason")
            ):
                raise RuntimeError(
                    f"Incomplete harvest: {provider}/{j['id']}. Resume harvesting before building."
                )
            # A refreshed snapshot may contain fewer pages than an older snapshot.
            for f in [folder / f"page-{n:05d}.json.gz" for n in range(1, state["pages"] + 1)]:
                with gzip.open(f, "rt", encoding="utf-8") as h:
                    payload = json.load(h)
                items = (
                    payload["response"]["message"]["items"]
                    if provider == "crossref"
                    else payload["response"]["results"]
                    if provider == "openalex"
                    else payload["records"]
                )
                for x in items:
                    identifier = x.get("DOI") or x.get("id") or x.get("url")
                    provenance = {
                        "provider": provider,
                        "id": identifier,
                        "raw_file": str(f.relative_to(ROOT)),
                        "retrieved_at": payload.get("record_retrieved_at", {}).get(
                            identifier, payload["retrieved_at"]
                        ),
                        "url": ("https://api.crossref.org/works/" + identifier)
                        if provider == "crossref"
                        else identifier,
                    }
                    if provider == "journal_archive":
                        provenance["archive_url"] = payload["request"]["url"]
                    yield provider, j, x, provenance


def apply_abstract_supplements(records):
    """Fill source-missing abstracts from DOI- or catalog-identity-verified supplements."""
    paths = [
        ROOT / "raw" / "semantic_scholar" / "abstracts.jsonl",
        ROOT / "raw" / "repec" / "abstract-supplements.jsonl",
        ROOT / "raw" / "linked_pages" / "abstract-supplements.jsonl",
    ]
    by_doi, by_catalog_id = {}, {}
    for path in paths:
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            item = json.loads(line)
            if not item.get("title") or not item.get("abstract") or not item.get("provider"):
                raise ValueError(f"Incomplete abstract supplement in {path}")
            identifier = doi(item.get("doi"))
            target = by_doi if identifier else by_catalog_id
            key = identifier or item.get("catalog_id")
            if not key:
                raise ValueError(f"Abstract supplement has no DOI or catalog ID in {path}")
            if key in target:
                raise ValueError(f"Duplicate abstract supplement identity: {key}")
            target[key] = (path, item)

    applied = Counter()
    for record in records:
        if record.get("abstract"):
            continue
        match = by_doi.get(record["doi"]) if record.get("doi") else None
        if not match:
            identifiers = [*record.get("openalex_ids", []), *record.get("repec_urls", [])]
            match = next(
                (
                    by_catalog_id[identifier]
                    for identifier in identifiers
                    if identifier in by_catalog_id
                ),
                None,
            )
        if not match:
            continue
        path, item = match
        if norm(record.get("title")) != norm(item["title"]):
            raise ValueError(
                f"Supplement title mismatch for catalog record {record.get('title')!r}"
            )
        if (
            record.get("year")
            and item.get("provider_year")
            and abs(record["year"] - item["provider_year"]) > 1
        ):
            raise ValueError(f"Supplement year mismatch for catalog record {record.get('title')!r}")
        record["abstract"] = item["abstract"]
        record["field_sources"]["abstract"] = item["provider"]
        record["sources"].append(
            {
                "provider": item["provider"],
                "id": item.get("provider_paper_id")
                or ("DOI:" + record["doi"] if record.get("doi") else item.get("catalog_id")),
                "raw_file": str(path.relative_to(ROOT)),
                "retrieved_at": item["retrieved_at"],
                "url": item.get("provider_url"),
            }
        )
        applied[item["provider"]] += 1
    return applied


def firstpage(r):
    return re.split(r"[–—-]", str(r.get("pages") or ""))[0].strip().lower()


def titlekey(r):
    return (r["journal_id"], norm(r["title"]))


def same_paper(a, b):
    if titlekey(a) != titlekey(b) or not a["title"]:
        return False
    if (
        a.get("volume_series")
        and b.get("volume_series")
        and a["volume_series"] != b["volume_series"]
    ):
        return False
    if a["volume"] and b["volume"] and a["volume"] != b["volume"]:
        return False
    if a["issue"] and b["issue"] and a["issue"] != b["issue"]:
        return False
    if (
        a.get("article_number")
        and b.get("article_number")
        and a["article_number"] != b["article_number"]
    ):
        return False
    if firstpage(a) and firstpage(b):
        return firstpage(a) == firstpage(b) and (
            a["volume"] == b["volume"] if a["volume"] and b["volume"] else a["year"] == b["year"]
        )
    # With incomplete bibliography require a distinctive title, nearby date and matching author.
    if len(norm(a["title"])) < 20 or not a["authors"] or not b["authors"]:
        return False
    an, bn = norm(a["authors"][0]), norm(b["authors"][0])
    author_matches = an == bn or (len(an) > 5 and len(bn) > 5 and (an in bn or bn in an))
    return (
        author_matches
        and a["year"] is not None
        and b["year"] is not None
        and abs(a["year"] - b["year"]) <= 1
    )


def rank_doi(d):
    return (d.startswith("10.2307/"), d)


def merge(a, b):
    had_print_date = bool(a.get("published_print"))
    dois = sorted(
        set(d for d in [a["doi"], b["doi"], *a["alternate_dois"], *b["alternate_dois"]] if d),
        key=rank_doi,
    )
    a["doi"], a["alternate_dois"] = (dois[0], dois[1:]) if dois else (None, [])
    for field in [
        "title",
        "authors",
        "author_details",
        "abstract",
        "volume",
        "issue",
        "pages",
        "article_number",
        "published_print",
        "published_online",
        "date",
        "date_precision",
        "year",
        "url",
    ]:
        if not a.get(field) and b.get(field):
            a[field] = b[field]
            if field in b["field_sources"]:
                a["field_sources"][field] = b["field_sources"][field]
    # A print issue date is more useful for a TOC than an online-first date.
    if b.get("published_print") and not had_print_date:
        a["published_print"] = b["published_print"]
        a["date"] = b["published_print"]
        a["date_precision"] = precision(a["date"])
        a["year"] = int(a["date"][:4])
        a["field_sources"]["date"] = "crossref:published-print"
    for field in ["openalex_ids", "repec_urls", "archive_urls", "source_types"]:
        a[field] = list(dict.fromkeys([*a.get(field, []), *b.get(field, [])]))
    if b.get("journal_membership", {}).get("archive_status") == "confirmed":
        a["journal_membership"].update(
            {k: v for k, v in b["journal_membership"].items() if k.startswith("archive_")}
        )
    a["sources"].extend(s for s in b["sources"] if s not in a["sources"])
    a["is_retracted"] = a["is_retracted"] or b["is_retracted"]


def issue_key(r):
    if not r["volume"]:
        return None
    series = ":s" + r["volume_series"] if r.get("volume_series") else ""
    if r.get("publication_unit") == "volume":
        return f"{r['journal_id']}{series}:v{r['volume']}"
    return f"{r['journal_id']}{series}:v{r['volume']}:i{r['issue']}" if r["issue"] else None


def issue_label(record):
    parts = [f"{record['volume_series']} series"] if record.get("volume_series") else []
    parts.append(f"volume {record['volume']}")
    if record.get("issue"):
        parts.append(f"issue {record['issue']}")
    return ", ".join(parts)


def slug(text):
    return re.sub(r"[^\w]+", "-", str(text).casefold()).strip("-_")[:80].rstrip("-") or "untitled"


def stable_slug(prefix, identity):
    return prefix + "-" + hashlib.sha256(identity.encode()).hexdigest()[:20]


def compile_records():
    records, issues, doi_map, title_map = [], {}, {}, defaultdict(list)
    raw_counts, duplicate_count = Counter(), 0
    membership = journal_membership.Gate(ROOT, same_paper, titlekey)
    for provider, j, x, prov in raw_records():
        raw_counts[provider + ":" + j["id"]] += 1
        r = normalized(x, provider, j, prov)
        if not membership.check(x, provider, j, r, prov):
            continue
        if provider == "crossref" and x.get("type") in ["journal", "journal-issue"]:
            if x.get("type") == "journal-issue" and issue_key(r):
                issues.setdefault(issue_key(r), r)
            continue
        if not r["title"]:
            r["title"] = "Untitled entry (" + str(prov["id"]) + ")"
            r["title_missing"] = True
        target = doi_map.get(r["doi"]) if r["doi"] else None
        if target is None:
            candidates = [c for c in title_map[titlekey(r)] if same_paper(records[c], r)]
            if len(candidates) == 1:
                target = candidates[0]
        if target is None:
            target = len(records)
            records.append(r)
            title_map[titlekey(r)].append(target)
        else:
            merge(records[target], r)
            duplicate_count += 1
        for d in [r["doi"], records[target]["doi"], *records[target]["alternate_dois"]]:
            if d:
                doi_map[d] = target
    for provider, count in apply_abstract_supplements(records).items():
        raw_counts[provider + ":abstract_supplements"] = count
    publisher_file = ROOT / "raw" / "publisher" / "aer-issues.json"
    if publisher_file.exists():
        for r in json.loads(publisher_file.read_text())["issues"]:
            key = issue_key(r)
            issues[key] = {**issues.get(key, {}), **r, "publisher_verified": True}
    for r in records:
        # Historic INFORMS DOI syntax explicitly records volume.issue.page.
        if r["doi"] and not r["issue"]:
            m = re.fullmatch(r"10\.1287/(?:mnsc|opre|mksc)\.(\d+)\.(\d+)\.([a-z]?\d+)", r["doi"])
            if m and (not r["volume"] or r["volume"] == m[1]):
                r["volume"], r["issue"] = m[1], m[2]
                r["field_sources"]["issue"] = "publisher_doi_citation_syntax"
        r["id"] = (
            ("doi:" + r["doi"])
            if r["doi"]
            else r["archive_urls"][0]
            if r.get("archive_urls")
            else r["openalex_ids"][0]
            if r["openalex_ids"]
            else r["repec_urls"][0]
        )
        r["source"] = ("doi:" + r["doi"]) if r["doi"] else r["id"]
        r["url"] = "https://doi.org/" + r["doi"] if r["doi"] else r["url"] or r["id"]
        r["cairn_slug"] = stable_slug("paper", r["id"])
        r["issue_id"] = issue_key(r)
        publication_status.annotate(r)
        r["abstract_status"] = "available" if r["abstract"] else "unavailable_in_harvested_sources"
        r["missing_fields"] = [
            k for k in ["authors", "doi", "abstract", "date", "volume", "issue"] if not r.get(k)
        ]
        if r.get("title_missing"):
            r["missing_fields"].append("title")
    grouped = defaultdict(list)
    for r in records:
        if r["issue_id"]:
            grouped[r["issue_id"]].append(r)
    for key, items in grouped.items():
        base = issues.get(key, {})
        representative = items[0]
        dates = [
            r["published_print"] or r["date"] for r in items if r["published_print"] or r["date"]
        ]
        date = base.get("date") or (Counter(dates).most_common(1)[0][0] if dates else None)
        issue_precision = base.get("date_precision") if base.get("date") else None
        if not issue_precision:
            matching = next((r for r in items if (r["published_print"] or r["date"]) == date), None)
            issue_precision = (
                precision(matching["published_print"])
                if matching and matching["published_print"]
                else matching["date_precision"]
                if matching
                else precision(date)
            )
        issues[key] = {
            "id": key,
            "journal_id": representative["journal_id"],
            "journal": representative["journal"],
            "volume": representative["volume"],
            "issue": representative["issue"],
            "date": date,
            "year": int(date[:4]) if date else representative["year"],
            "date_precision": issue_precision,
            "url": base.get("url"),
            "publisher_verified": base.get("publisher_verified", False),
            "entry_count": len(items),
            "abstract_count": sum(bool(r["abstract"]) for r in items),
            "cairn_slug": stable_slug("issue", key),
            "coverage_status": "publisher_issue_confirmed_contents_unverified"
            if base.get("publisher_verified")
            else "reconstructed_from_public_metadata_contents_unverified",
            "publication_unit": representative.get("publication_unit", "issue"),
            "volume_series": representative.get("volume_series"),
        }
        if base.get("doi"):
            issues[key]["doi"] = base["doi"]
    # Preserve publisher/registry issue entries even where no paper was harvested.
    for key, base in list(issues.items()):
        if "entry_count" not in base:
            issues[key] = {
                "id": key,
                "journal_id": base["journal_id"],
                "journal": next(j["title"] for j in JOURNALS if j["id"] == base["journal_id"]),
                "volume": base["volume"],
                "issue": base["issue"],
                "date": base.get("date"),
                "year": base.get("year"),
                "date_precision": base.get("date_precision"),
                "url": base.get("url"),
                "publisher_verified": base.get("publisher_verified", False),
                "entry_count": 0,
                "abstract_count": 0,
                "cairn_slug": stable_slug("issue", key),
                "coverage_status": "issue_known_contents_missing",
            }
    write_jsonl("quarantine.jsonl", membership.quarantine)
    atomic_json(ROOT / "journal-membership-report.json", membership.report(records))
    return records, list(issues.values()), dict(raw_counts), duplicate_count


def sql_database(records, issues, build_graph=True):
    dest = ROOT / "catalog.sqlite"
    temp = ROOT / "catalog.sqlite.tmp"
    temp.unlink(missing_ok=True)
    con = sqlite3.connect(temp)
    con.executescript("""
    PRAGMA foreign_keys=ON;
    CREATE TABLE journals(id TEXT PRIMARY KEY, title TEXT NOT NULL, abbreviation TEXT, issns_json TEXT, start_year INTEGER, publisher_url TEXT);
    CREATE TABLE issues(id TEXT PRIMARY KEY, journal_id TEXT NOT NULL REFERENCES journals(id), volume TEXT, issue TEXT, year INTEGER, date TEXT, entry_count INTEGER, abstract_count INTEGER, coverage_status TEXT, record_json TEXT NOT NULL);
    CREATE TABLE papers(id TEXT PRIMARY KEY, journal_id TEXT NOT NULL REFERENCES journals(id), issue_id TEXT REFERENCES issues(id), title TEXT NOT NULL, date TEXT, date_precision TEXT, year INTEGER, doi TEXT UNIQUE, volume TEXT, issue TEXT, pages TEXT, authors_json TEXT NOT NULL, abstract TEXT, abstract_source TEXT, entry_type TEXT, cairn_slug TEXT UNIQUE NOT NULL, record_json TEXT NOT NULL);
    CREATE TABLE paper_dois(doi TEXT PRIMARY KEY, paper_id TEXT NOT NULL REFERENCES papers(id), is_primary INTEGER NOT NULL);
    CREATE TABLE authors(paper_id TEXT NOT NULL REFERENCES papers(id), position INTEGER NOT NULL, name TEXT NOT NULL, details_json TEXT, PRIMARY KEY(paper_id,position));
    CREATE VIRTUAL TABLE paper_search USING fts5(paper_id UNINDEXED,title,authors,abstract,journal,tokenize='unicode61 remove_diacritics 2');
    CREATE INDEX papers_journal_year ON papers(journal_id,year);
    CREATE INDEX papers_issue ON papers(issue_id);
    CREATE INDEX papers_date ON papers(date);
    CREATE INDEX papers_entry_type ON papers(entry_type);
    CREATE INDEX authors_name ON authors(name);
    CREATE INDEX issues_journal_year ON issues(journal_id,year);
    ALTER TABLE papers ADD COLUMN publication_status TEXT NOT NULL DEFAULT 'unassigned';
    ALTER TABLE papers ADD COLUMN publication_status_evidence TEXT;
    CREATE INDEX papers_publication_status ON papers(publication_status,journal_id,date);
    """)
    for j in JOURNALS:
        con.execute(
            "INSERT INTO journals VALUES(?,?,?,?,?,?)",
            (
                j["id"],
                j["title"],
                j["abbreviation"],
                json.dumps(j["issns"]),
                j["start_year"],
                j["url"],
            ),
        )
    for i in issues:
        con.execute(
            "INSERT INTO issues VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                i["id"],
                i["journal_id"],
                i["volume"],
                i["issue"],
                i["year"],
                i["date"],
                i["entry_count"],
                i["abstract_count"],
                i["coverage_status"],
                json.dumps(i, ensure_ascii=False),
            ),
        )
    for r in records:
        publication_status.annotate(r)
        con.execute(
            "INSERT INTO papers VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                r["id"],
                r["journal_id"],
                r["issue_id"],
                r["title"],
                r["date"],
                r["date_precision"],
                r["year"],
                r["doi"],
                r["volume"],
                r["issue"],
                r["pages"],
                json.dumps(r["authors"], ensure_ascii=False),
                r["abstract"],
                r["field_sources"].get("abstract"),
                r["entry_type"],
                r["cairn_slug"],
                json.dumps(r, ensure_ascii=False),
                r["publication_status"],
                r["publication_status_evidence"],
            ),
        )
        for n, d in enumerate([r["doi"], *r["alternate_dois"]]):
            if d:
                con.execute("INSERT INTO paper_dois VALUES(?,?,?)", (d, r["id"], int(n == 0)))
        for n, name in enumerate(r["authors"], 1):
            details = (
                r["author_details"][n - 1] if n <= len(r["author_details"]) else {"name": name}
            )
            con.execute(
                "INSERT INTO authors VALUES(?,?,?,?)",
                (r["id"], n, name, json.dumps(details, ensure_ascii=False)),
            )
        con.execute(
            "INSERT INTO paper_search VALUES(?,?,?,?,?)",
            (r["id"], r["title"], "; ".join(r["authors"]), r["abstract"] or "", r["journal"]),
        )
    con.commit()
    assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert not con.execute("PRAGMA foreign_key_check").fetchall()
    con.close()
    if build_graph:
        # Publish the database only after the author/institution graph is ready too.
        from .entities import build_entities

        build_entities(db=temp)
        temp.replace(dest)
        return dest
    return temp


def write_jsonl(name, values):
    dest = ROOT / name
    temp = dest.with_suffix(".tmp")
    with temp.open("w", encoding="utf-8") as f:
        for value in values:
            f.write(json.dumps(value, ensure_ascii=False) + "\n")
    temp.replace(dest)


def read_jsonl(path):
    """Yield normalized records from disk without rebuilding a full in-memory list."""
    with Path(path).open(encoding="utf-8") as handle:
        for line in handle:
            yield json.loads(line)


def yaml_note(path, meta, body):
    import yaml

    path.parent.mkdir(parents=True, exist_ok=True)
    previous = path.read_text("utf-8") if path.exists() else None
    if previous:
        created = re.search(r"^created: (.+)$", previous.split("---", 2)[1], re.M)
        if created:
            meta = {**meta, "created": created[1].strip("'\"")}
    content = (
        "---\n"
        + yaml.dump(
            meta,
            Dumper=getattr(yaml, "CSafeDumper", yaml.SafeDumper),
            sort_keys=False,
            allow_unicode=True,
            width=1000,
        )
        + "---\n"
        + body.strip()
        + "\n"
    )
    if previous == content:
        return
    temp = path.with_suffix(".tmp")
    temp.write_text(content, encoding="utf-8")
    temp.replace(path)


def paper_body(r, issue=None):
    authors = wiki_text("; ".join(r["authors"])) or "Unavailable in harvested sources"
    bibliography = wiki_text(issue_label(r)) if r.get("volume") else "Volume / issue unavailable"
    lines = [
        f"# {wiki_text(r['title'])}",
        "",
        f"**Journal:** {wiki_text(r['journal'])}",
        f"**Authors:** {authors}",
        f"**Publication date (print preferred):** {journal_membership.display_date(r['date'], r['date_precision'])}",
        f"**Bibliography:** {bibliography}",
        f"**Pages:** {r['pages'] or 'Unavailable'}",
        f"**DOI:** {r['doi'] or 'Unavailable in harvested sources'}",
        f"**Source:** [{r['url']}]({r['url']})",
    ]
    if r["published_print"]:
        lines.append(f"**Print publication:** {r['published_print']}")
    if r["published_online"]:
        lines.append(f"**Online publication:** {r['published_online']}")
    if r.get("article_number"):
        lines.append(f"**Article number:** {r['article_number']}")
    status, evidence = publication_status.classify(r)
    lines.extend(
        [
            f"**Publication stage:** {publication_status.LABELS[status]}",
            f"**Stage evidence:** {evidence}",
        ]
    )
    membership = r.get("journal_membership")
    if membership:
        lines.extend(
            [
                f"**Journal identity evidence:** {membership['explanation']}",
                f"**Publisher TOC check:** {membership['archive_status']}",
            ]
        )
        if membership.get("archive_url"):
            lines.append(
                f"**Verified publisher listing:** [{membership['archive_url']}]({membership['archive_url']})"
            )
    if issue:
        lines.extend(["", f"**Table of contents:** [[{issue['cairn_slug']}]]"])
    lines.extend(
        [
            "",
            "## Abstract",
            "",
            wiki_text(r["abstract"])
            or "Abstract unavailable in the harvested public sources. An abstract may exist on the publisher's page; none has been generated or inferred.",
            "",
            "## Catalog provenance",
            "",
            f"Entry type: {r['entry_type']} (metadata classification).",
            f"Abstract source: {r['field_sources'].get('abstract') or 'none'}.",
            f"Catalog snapshot: {AS_OF}. Publication dates remain separate from source retrieval dates.",
        ]
    )
    if r["alternate_dois"]:
        lines.extend(
            [
                "",
                "Other DOI registrations for this bibliographic item: "
                + ", ".join(r["alternate_dois"]),
            ]
        )
    lines.extend(["", "Public source records:"])
    seen = set()
    for s in r["sources"]:
        label = f"{s['provider']}: {s['id']}"
        if label not in seen:
            lines.append(f"- [{label}]({s['url']})")
            seen.add(label)
    lines.extend(
        [
            "",
            "## Reading notes",
            "",
            "Catalog metadata only; no reading or interpretation recorded.",
        ]
    )
    return "\n".join(lines)


def wiki_text(value):
    """Escape source prose so literal [[ text cannot become a Cairn link."""
    return str(value or "").replace("[[", "&#91;&#91;")


def paper_meta(r, topic):
    return {
        "title": r["title"],
        "kind": "paper",
        "source": r["source"],
        "doi": r["doi"],
        "alternate_dois": r["alternate_dois"],
        "authors": r["authors"],
        "year": r["year"],
        "url": r["url"],
        "journal": r["journal"],
        "journal_id": r["journal_id"],
        "issns": r["issns"],
        "volume": r["volume"],
        "volume_series": r.get("volume_series"),
        "publication_unit": r.get("publication_unit", "issue"),
        "issue": r["issue"],
        "pages": r["pages"],
        "article_number": r.get("article_number"),
        "publication_date": r["date"],
        "date_precision": r["date_precision"],
        "published_print": r["published_print"],
        "published_online": r["published_online"],
        "abstract_status": r["abstract_status"],
        "abstract_source": r["field_sources"].get("abstract"),
        "catalog_id": r["id"],
        "catalog_issue_id": r["issue_id"],
        "catalog_schema_version": "1.0",
        "publication_status": publication_status.classify(r)[0],
        "publication_status_evidence": publication_status.classify(r)[1],
        "journal_membership": r.get("journal_membership"),
        "topics": [f"[[{topic}]]"],
        "aliases": [
            d
            for d in [
                r["doi"],
                *r["alternate_dois"],
                *r["openalex_ids"],
                *r["repec_urls"],
                *r.get("archive_urls", []),
            ]
            if d
        ],
        "created": AS_OF,
        "updated": AS_OF,
    }


def write_library(records, issues, report):
    library = ROOT / "cairn-library"
    library.mkdir(parents=True, exist_ok=True)
    (library / ".cairn").touch()
    kbdir = library / "research"
    topics = {j["id"]: "journal-" + j["id"] for j in JOURNALS}
    issue_lookup = {i["id"]: i for i in issues}
    grouped, unassigned = defaultdict(list), defaultdict(list)
    expected_papers = set()
    total_entries = report["total_entries"]
    total_abstracts = report["total_abstracts"]
    yaml_note(
        kbdir / "topics/journal-catalog.md",
        {"title": "Journal catalog", "kind": "topic", "created": AS_OF, "updated": AS_OF},
        f"# Journal catalog\n\nA public bibliographic catalog for {len(JOURNALS)} journals. Browse [[journal-catalog-index]]. Metadata coverage and missing fields are documented in the catalog coverage report.",
    )
    for n, r in enumerate(records, 1):
        yaml_note(
            kbdir / "papers" / (r["cairn_slug"] + ".md"),
            paper_meta(r, topics[r["journal_id"]]),
            paper_body(r, issue_lookup.get(r["issue_id"])),
        )
        expected_papers.add(r["cairn_slug"])
        # Issue and unassigned indexes need bibliography/link fields only. Do not
        # retain full records, especially their abstracts and source provenance.
        if r["issue_id"]:
            content = {
                k: r.get(k)
                for k in [
                    "cairn_slug",
                    "title",
                    "authors",
                    "date",
                    "date_precision",
                    "pages",
                    "doi",
                    "abstract_status",
                ]
            }
            grouped[r["issue_id"]].append(content)
        else:
            unassigned[r["journal_id"]].append(
                {k: r.get(k) for k in ["cairn_slug", "title", "date", "doi", "year"]}
            )
        if n % 10000 == 0:
            print(f"Cairn export: {n:,}/{total_entries:,} paper notes", flush=True)
    for i in issues:
        items = sorted(grouped[i["id"]], key=lambda r: natural(r["pages"] or "999999"))
        lines = [
            f"# {wiki_text(i['journal'])} — {wiki_text(issue_label(i))}",
            "",
            f"Date: {journal_membership.display_date(i['date'], i['date_precision'])}. Entries: {i['entry_count']}. Abstracts: {i['abstract_count']}.",
            "",
            f"Coverage: {i['coverage_status']}.",
        ]
        if i.get("url"):
            lines.extend(["", f"[Publisher issue page]({i['url']})"])
        lines.extend(["", "## Contents", ""])
        for r in items:
            lines.append(
                f"- [[{r['cairn_slug']}|{wiki_text(r['title'])}]] — {wiki_text('; '.join(r['authors'])) or 'authors unavailable'}; {journal_membership.display_date(r['date'], r['date_precision'])}; pp. {r['pages'] or '?'}; DOI: {r['doi'] or 'unavailable'}; abstract: {r['abstract_status']}."
            )
        if not items:
            lines.append(
                "No contents were found in the harvested sources; this is an explicit coverage gap."
            )
        yaml_note(
            kbdir / "notes" / (i["cairn_slug"] + ".md"),
            {
                "title": f"{i['journal']} — {issue_label(i)}",
                "kind": "note",
                "catalog_issue_id": i["id"],
                "topics": [f"[[{topics[i['journal_id']]}]]"],
                "created": AS_OF,
                "updated": AS_OF,
            },
            "\n".join(lines),
        )
    index = [
        "# Journal catalog",
        "",
        f"Retrieved {AS_OF}. {total_entries:,} deduplicated entries; {len(issues):,} indexed issues.",
        "",
        "Only records with independent journal identity evidence enter this catalog. Unsupported discoveries are retained outside the main collection in quarantine. Publisher TOC checks remain incomplete; missing abstracts, DOI registrations, issue assignments and historical coverage gaps are explicit.",
        "",
        "## Journals",
        "",
    ]
    for j in JOURNALS:
        jid = j["id"]
        rows = sorted(
            [i for i in issues if i["journal_id"] == jid],
            key=lambda i: (i["year"] or 0, natural(i["volume"]), natural(i["issue"])),
            reverse=True,
        )
        coverage = report["journals"][jid]
        lines = [
            f"# {wiki_text(j['title'])}",
            "",
            f"ISSNs: {', '.join(j['issns'])}. [Publisher archive]({j['url']}).",
            "",
            f"{coverage['entries']:,} entries, {coverage['issues']:,} indexed issues, {coverage['abstracts']:,} abstracts. Observed publication years: {coverage['first_year']}–{coverage['last_year']}.",
            "",
            "Issue contents are reconstructed from public metadata; publisher completeness has not been certified.",
            "",
            "## Issues",
            "",
        ]
        last_year = None
        for i in rows:
            if i["year"] != last_year:
                lines.extend([f"### {i['year'] or 'Year unavailable'}", ""])
                last_year = i["year"]
            lines.append(
                f"- [[{i['cairn_slug']}|{issue_label(i)}]] — {i['date'] or 'date unavailable'}; {i['entry_count']} entries; {i['abstract_count']} abstracts."
            )
        if unassigned[jid]:
            un_slug = "journal-" + jid + "-unassigned"
            lines.extend(
                [
                    "",
                    "## Issue assignment unavailable",
                    "",
                    f"[[{un_slug}|{len(unassigned[jid])} entries without complete volume/issue metadata]]",
                ]
            )
            body = [
                f"# {wiki_text(j['title'])} — issue assignment unavailable",
                "",
                "These entries have not been silently assigned to an issue. They may be online-first papers or metadata gaps.",
                "",
            ]
            for r in sorted(
                unassigned[jid], key=lambda r: (r["year"] or 0, r["title"]), reverse=True
            ):
                body.append(
                    f"- [[{r['cairn_slug']}|{wiki_text(r['title'])}]] — {r['date'] or 'date unavailable'}; DOI: {r['doi'] or 'unavailable'}."
                )
            yaml_note(
                kbdir / "notes" / (un_slug + ".md"),
                {
                    "title": f"{j['title']} — unassigned catalog entries",
                    "kind": "note",
                    "topics": [f"[[{topics[jid]}]]"],
                    "created": AS_OF,
                    "updated": AS_OF,
                },
                "\n".join(body),
            )
        yaml_note(
            kbdir / "topics" / (topics[jid] + ".md"),
            {
                "title": j["title"],
                "kind": "topic",
                "aliases": list(dict.fromkeys([j["abbreviation"], *j.get("aliases", [])])),
                "topics": ["[[journal-catalog]]"],
                "created": AS_OF,
                "updated": AS_OF,
            },
            "\n".join(lines),
        )
        index.append(
            f"- [[{topics[jid]}|{j['title']}]] — {coverage['entries']:,} entries; {coverage['issues']:,} issues; {coverage['abstracts']:,} abstracts."
        )
    yaml_note(
        kbdir / "notes/journal-catalog-index.md",
        {
            "title": "Journal catalog index",
            "kind": "note",
            "topics": ["[[journal-catalog]]"],
            "created": AS_OF,
            "updated": AS_OF,
        },
        "\n".join(index),
    )
    # Also make a conventional Markdown landing page usable without a Cairn renderer.
    body = [
        "# Journal catalog",
        "",
        f"Retrieved {AS_OF}. **{total_entries:,} entries · {len(issues):,} issues · {total_abstracts:,} abstracts.**",
        "",
        "Browse journal → issue → paper in the native Cairn library. Every paper has a Markdown note with YAML metadata, authors, publication dates, DOI (when available), abstract (when available), and source provenance.",
        "",
        "| Journal | Years observed | Entries | Issues | Abstracts |",
        "|---|---:|---:|---:|---:|",
    ]
    graph_path = ROOT / "entity-coverage.json"
    graph = json.loads(graph_path.read_text()) if graph_path.exists() else None
    graph_counts = (
        (
            f" Includes {graph['identified_author_entities']:,} source-identified authors, "
            f"{graph['identified_institutions']:,} identified institutions and flexible publication dates."
        )
        if graph
        else ""
    )
    body[4:4] = [
        f"[Open the saved local paper, author and institution catalog](catalog.html).{graph_counts} [Usage and identity coverage](README.md#authors-institutions-and-publication-periods).",
        "",
    ]
    for j in JOURNALS:
        c = report["journals"][j["id"]]
        body.append(
            f"| [{j['title']}](cairn-library/research/topics/journal-{j['id']}.md) | {c['first_year']}–{c['last_year']} | {c['entries']:,} | {c['issues']:,} | {c['abstracts']:,} |"
        )
    body.extend(
        [
            "",
            "[Coverage and known gaps](COVERAGE.md) · [Storage schema and usage](README.md)",
            "",
            "The complete harvested metadata are also in `papers.jsonl`, `issues.jsonl`, and `catalog.sqlite` (including full-text search). Native Cairn exports are in `cairn-library/`.",
            "",
            "A completed API harvest does not prove every publisher issue or paper is present. See the coverage report before using counts as a complete historical census.",
        ]
    )
    (ROOT / "INDEX.md").write_text("\n".join(body) + "\n", encoding="utf-8")
    # Retire generated entries removed by a later snapshot without deleting them.
    expected_notes = (
        {i["cairn_slug"] for i in issues}
        | {"journal-catalog-index"}
        | {"journal-" + jid + "-unassigned" for jid, rows in unassigned.items() if rows}
    )
    for folder, expected in [("papers", expected_papers), ("notes", expected_notes)]:
        for path in (kbdir / folder).glob("*.md"):
            if path.stem not in expected:
                archived = ROOT / "retired" / AS_OF / folder / path.name
                archived.parent.mkdir(parents=True, exist_ok=True)
                if archived.exists():
                    archived = archived.with_stem(
                        archived.stem + "-" + hashlib.sha256(path.read_bytes()).hexdigest()[:12]
                    )
                path.replace(archived)


def natural(value):
    return tuple(
        (0, int(s)) if s.isdigit() else (1, s.lower()) for s in re.split(r"(\d+)", str(value or ""))
    )


def coverage(records, issues, raw_counts, duplicate_count):
    states = {}
    for f in (ROOT / "raw").glob("*/*/state.json"):
        states[str(f.parent.relative_to(ROOT / "raw"))] = json.loads(f.read_text())
    report = {
        "schema_version": "1.0",
        "as_of": AS_OF,
        "built_at": now(),
        "total_entries": len(records),
        "total_issues": len(issues),
        "total_abstracts": sum(bool(r["abstract"]) for r in records),
        "duplicates_merged": duplicate_count,
        "raw_counts": raw_counts,
        "harvests": states,
        "publisher_archive_completeness_verified": False,
        "journals": {},
    }
    report["journal_membership"] = json.loads((ROOT / "journal-membership-report.json").read_text())
    for j in JOURNALS:
        rows = [r for r in records if r["journal_id"] == j["id"]]
        years = sorted(set(r["year"] for r in rows if r["year"]))
        report["journals"][j["id"]] = {
            "title": j["title"],
            "entries": len(rows),
            "issues": sum(i["journal_id"] == j["id"] for i in issues),
            "abstracts": sum(bool(r["abstract"]) for r in rows),
            "with_doi": sum(bool(r["doi"]) for r in rows),
            "without_issue_assignment": sum(not r["issue_id"] for r in rows),
            "first_year": min(years) if years else None,
            "last_year": max(years) if years else None,
            "missing_years_since_start": sorted(
                set(range(j["start_year"], int(AS_OF[:4]) + 1)) - set(years)
            ),
            "missing_field_counts": {
                k: sum(k in r["missing_fields"] for r in rows)
                for k in ["title", "authors", "doi", "abstract", "date", "volume", "issue"]
            },
            "entry_types": dict(Counter(r["entry_type"] for r in rows)),
        }
    return report


def build(args):
    records, issues, raw_counts, duplicates = compile_records()
    print(
        f"Normalized {len(records):,} entries and {len(issues):,} issues; merged {duplicates:,} source duplicates",
        flush=True,
    )
    report = coverage(records, issues, raw_counts, duplicates)
    atomic_json(ROOT / "coverage.json", report)
    write_jsonl("papers.jsonl", records)
    write_jsonl("issues.jsonl", sorted(issues, key=lambda i: i["id"]))
    temp_db = sql_database(records, issues, build_graph=False)
    del records
    gc.collect()
    from .entities import build_entities

    build_entities(db=temp_db)
    temp_db.replace(ROOT / "catalog.sqlite")
    write_library(read_jsonl(ROOT / "papers.jsonl"), issues, report)
    write_coverage(report)
    print(
        json.dumps(
            {
                k: report[k]
                for k in ["total_entries", "total_issues", "total_abstracts", "duplicates_merged"]
            }
        ),
        flush=True,
    )


def write_coverage(report):
    lines = [
        "# Coverage report",
        "",
        f"Metadata retrieved for the {AS_OF} catalog build.",
        "",
        "This is a public-source catalog, not a certified census of every paper ever published. Complete retrieval of a registry is not equivalent to complete publisher coverage.",
        "",
        "| Journal | Entries | Issues | Abstracts | DOI present | Unassigned |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for j in JOURNALS:
        c = report["journals"][j["id"]]
        lines.append(
            f"| {j['title']} | {c['entries']:,} | {c['issues']:,} | {c['abstracts']:,} | {c['with_doi']:,} | {c['without_issue_assignment']:,} |"
        )
    supplements = {
        name.removesuffix(":abstract_supplements"): count
        for name, count in report["raw_counts"].items()
        if name.endswith(":abstract_supplements")
    }
    if supplements:
        lines.extend(["", "## Supplemental abstract recovery", ""])
        labels = {
            "linked_page_meta": "Other cataloged linked pages",
            "repec_detail": "AER/RePEc detail pages",
            "semantic_scholar": "Semantic Scholar DOI lookup",
        }
        for provider, count in sorted(supplements.items()):
            lines.append(f"- {labels.get(provider, provider)}: {count:,} source abstracts.")
        lines.append(
            "- Matching rules and skipped entries are recorded in recovery reports under `raw/linked_pages/`, `raw/repec/`, and `raw/semantic_scholar/`."
        )
    lines.extend(
        [
            "",
            "## Source retrieval",
            "",
            "| Source / journal | Records retrieved | Source count | Complete API/listing traversal |",
            "|---|---:|---:|---|",
        ]
    )
    for name, s in sorted(report["harvests"].items()):
        lines.append(
            f"| {name} | {s['retrieved']:,} | {s.get('source_total', 'not reported')} | {s.get('complete', False)} |"
        )
    unfinished = [
        (name, state)
        for name, state in sorted(report["harvests"].items())
        if not state.get("complete")
    ]
    if unfinished:
        lines.extend(
            [
                "",
                "### Incomplete source supplements",
                "",
                "OpenAlex's shared daily API budget stopped part of the historical supplement. Confirmed source pages are retained; these traversals remain incomplete and the updater resumes them before recent-publication refreshes.",
                "",
            ]
        )
        for name, state in unfinished:
            lines.append(
                f"- {name}: {state.get('incomplete_reason') or state.get('error') or 'Historical traversal is incomplete.'}"
            )
    lines.extend(
        [
            "",
            "JMLR is parsed directly from its public volume TOCs and article metadata pages, including the current volume discovered through its homepage. Original HTML, record URLs and retrieval timestamps remain in `raw/journal_archive/`. A complete listing traversal describes the captured source snapshot, rather than certifying every historical publisher record.",
        ]
    )
    membership = report["journal_membership"]
    lines.extend(
        [
            "",
            "## Journal membership checks",
            "",
            f"{membership['quarantined_source_records']:,} unsupported source records are kept in `quarantine.jsonl` outside the main catalog and its author/institution graph.",
            f"{membership['publisher_archive_checked_papers']:,} papers have a publisher archive record or exact DOI checked in a publisher TOC. Publisher/archival deposit identity checks do not certify the unreviewed TOCs.",
            membership["note"],
            "",
            "[Machine-readable admission and quarantine report](journal-membership-report.json)",
        ]
    )
    lines.extend(
        [
            "",
            "## Known limitations",
            "",
            "- The AEA public issue index covers 1999 onward; older AER entries are supplemented by OpenAlex and the publisher-supplied RePEc listings (1969 onward). AER's earliest decades remain incompletely verified.",
            "- Crossref, OpenAlex, RePEc, Semantic Scholar, and linked pages may omit papers, issues, authors, and abstracts, especially historical items. The catalog does not invent missing DOIs, abstracts, or issue assignments.",
            "- Abstracts are author/publisher metadata retrieved from Crossref, RePEc detail-page metadata, reviewed linked-page metadata, or Semantic Scholar, or reconstructed exactly from OpenAlex's inverted abstract index. None are AI summaries. Missing abstracts are explicitly marked; some historical papers and front matter never had abstracts.",
            "- OpenAlex dates can contain inferred day/month components. OpenAlex-only dates are marked `provider_day_unverified`; Crossref dates preserve the original year/month/day precision. Online-first and print dates are stored separately.",
            "- Issue identities use journal + volume + issue, without conflating online-first years with issue publication years. Issue dates can differ from a paper's original online publication date.",
            "- Counts include articles, reviews, corrections, and front/back matter as distinct catalog entries. Entry classifications are conservative title-based labels, not a verified research-article census.",
            "- DOI aliases are retained for deduplicated publisher/JSTOR registrations. Matching requires exact normalized titles plus matching bibliography or compatible author/date information; incomplete records can still contain residual duplicates.",
            "- Issue contents are reconstructed from harvested metadata and have not been exhaustively compared with every publisher TOC. Known empty issues and unassigned papers remain visible.",
            "- No subscription full text, login-protected pages, or restricted content was downloaded. Publisher access failures are not bypassed.",
            "",
            "## Historical year gaps",
            "",
        ]
    )
    for j in JOURNALS:
        c = report["journals"][j["id"]]
        lines.append(
            f"- {j['title']}: years with no harvested entries since {j['start_year']}: {', '.join(map(str, c['missing_years_since_start'])) or 'none'}. Having at least one entry does not certify full coverage for that year."
        )
    lines.extend(
        [
            "",
            "## Sources",
            "",
            "- [Crossref REST API](https://www.crossref.org/documentation/retrieve-metadata/rest-api/)",
            "- [OpenAlex API](https://help.openalex.org/api/)",
            "- [Semantic Scholar Academic Graph API](https://api.semanticscholar.org/api-docs/)",
            "- [AEA AER issue archive](https://www.aeaweb.org/journals/aer/issues)",
            "- [AER publisher-supplied RePEc listings](https://ideas.repec.org/s/aea/aecrev.html)",
            "",
            "Raw, selected API responses and RePEc listings are retained under `raw/`. `coverage.json` contains machine-readable field coverage and harvest state.",
        ]
    )
    (ROOT / "COVERAGE.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def search(args):
    con = sqlite3.connect(ROOT / "catalog.sqlite")
    con.row_factory = sqlite3.Row
    conditions, values = [], []
    if args.query:
        conditions.append("p.id IN (SELECT paper_id FROM paper_search WHERE paper_search MATCH ?)")
        values.append(args.query)
    if args.journal:
        conditions.append("p.journal_id = ?")
        values.append(args.journal)
    if args.year:
        conditions.append("p.year = ?")
        values.append(args.year)
    if args.missing_abstract:
        conditions.append("p.abstract IS NULL")
    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    sql = (
        "SELECT p.id,p.journal_id,p.title,p.year,p.volume,p.issue,p.doi,p.cairn_slug FROM papers p"
        + where
        + " ORDER BY p.year DESC,p.title LIMIT ?"
    )
    values.append(args.limit)
    for row in con.execute(sql, values):
        print(json.dumps(dict(row), ensure_ascii=False))
    con.close()


def cairn_imports():
    from cairn.store import KB, parse

    return KB, parse


def open_kb():
    """The configured Cairn collection that selected papers and profiles are imported into."""
    KB, _ = cairn_imports()
    if WORKSPACE is None:
        raise SystemExit("Set `workspace` in the cairn-workbench config or $CAIRN_WORKSPACE.")
    return KB(WORKSPACE, COLLECTION)


def import_paper(args):
    con = sqlite3.connect(ROOT / "catalog.sqlite")
    identifier = doi(args.identifier)
    row = con.execute(
        "SELECT p.record_json FROM papers p LEFT JOIN paper_dois d ON d.paper_id=p.id WHERE p.id=? OR p.cairn_slug=? OR d.doi=? LIMIT 1",
        (args.identifier, args.identifier, identifier),
    ).fetchone()
    if row is None:
        raise SystemExit(
            "Paper not found; use the search command to get its ID, DOI, or Cairn slug."
        )
    r = json.loads(row[0])
    kb = open_kb()
    notes = kb.notes()
    journal = next(j for j in JOURNALS if j["id"] == r["journal_id"])
    topic = kb.resolve(journal["title"], notes)
    if topic is None:
        kb.save(
            kind="topic",
            title=journal["title"],
            body=f"Research published in {journal['title']}. The full public journal catalog is in [[journal-catalog]].",
            aliases=[journal["abbreviation"]],
        )
    sources = {"doi:" + d for d in [r["doi"], *r["alternate_dois"]] if d} | {r["source"]}
    existing = next(
        (n for n in notes.values() if n.kind == "paper" and n.meta.get("source") in sources), None
    )
    if existing is None:
        named = kb.resolve(r["title"], notes)
        if named and named.kind == "paper" and named.meta.get("source") in (None, r["source"]):
            existing = named
    meta = paper_meta(r, "journal-" + r["journal_id"])
    fields = {
        k: v
        for k, v in meta.items()
        if k not in {"title", "kind", "topics", "aliases", "created", "updated"}
    }
    # Preserve the entire existing reading body and unrelated metadata on repeated imports.
    body = existing.body if existing else paper_body(r)
    if existing:
        fields = {
            **{
                k: v
                for k, v in existing.meta.items()
                if k not in {"title", "kind", "topics", "aliases", "created", "updated"}
            },
            **fields,
        }
    result = kb.save(
        kind="paper",
        title=existing.title if existing else r["title"],
        body=body,
        fields=fields,
        topics=list(dict.fromkeys([*(existing.topics if existing else []), journal["title"]])),
        aliases=list(dict.fromkeys([*(existing.aliases if existing else []), *meta["aliases"]])),
        revision=existing.revision if existing else None,
    )
    print(json.dumps(result, ensure_ascii=False))
    con.close()


def validate(args):
    KB, parse = cairn_imports()
    con = sqlite3.connect(ROOT / "catalog.sqlite")
    assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert not con.execute("PRAGMA foreign_key_check").fetchall()
    total = con.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
    report = json.loads((ROOT / "coverage.json").read_text())
    assert total == report["total_entries"]
    assert all(
        json.loads(r[0]).get("journal_membership")
        for r in con.execute("SELECT record_json FROM papers")
    )
    library = ROOT / "cairn-library"
    kb = KB(library, "research")
    files = list((kb.dir / "papers").glob("*.md"))
    assert len(files) == total, (len(files), total)
    known_slugs = {
        p.stem for folder in ["papers", "notes", "topics"] for p in (kb.dir / folder).glob("*.md")
    }
    for n, path in enumerate(files, 1):
        note = parse(path)
        assert note.kind == "paper" and note.meta["title"] and note.meta["source"]
        assert all(s in known_slugs for s in [*note.topics, *note.body_links]), path
        r = json.loads(
            con.execute(
                "SELECT record_json FROM papers WHERE cairn_slug=?", (path.stem,)
            ).fetchone()[0]
        )
        assert note.meta["source"] == r["source"] and note.meta["doi"] == r["doi"]
        assert note.meta["authors"] == r["authors"]
        assert r["abstract"] is None or wiki_text(r["abstract"]) in note.body
        if n % 10000 == 0:
            print(f"Validated {n:,}/{total:,} native Cairn paper notes", flush=True)
    for path in (kb.dir / "notes").glob("*.md"):
        note = parse(path)
        assert all(s in known_slugs for s in [*note.topics, *note.body_links]), path
    assert con.execute("SELECT COUNT(*) FROM paper_search").fetchone()[0] == total
    con.close()
    result = {
        "validated_at": now(),
        "paper_notes": total,
        "issue_notes": report["total_issues"],
        "sqlite_integrity": "ok",
        "foreign_keys": "ok",
        "native_cairn_parse": "all paper and issue files",
        "internal_links": "resolved",
        "abstracts_match_normalized_sources": True,
        "independent_journal_identity_evidence": True,
        "publisher_archive_completeness_verified": False,
    }
    atomic_json(ROOT / "validation.json", result)
    print(json.dumps(result), flush=True)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    h = sub.add_parser("harvest")
    h.add_argument(
        "--service", nargs="+", choices=["crossref", "openalex"], default=["crossref", "openalex"]
    )
    h.add_argument("--journal", nargs="+")
    h.add_argument("--refresh", action="store_true")
    h.set_defaults(func=harvest)
    r = sub.add_parser("harvest-repec")
    r.add_argument("--refresh", action="store_true")
    r.set_defaults(func=harvest_repec)
    sub.add_parser("harvest-publisher").set_defaults(func=harvest_publisher)
    sub.add_parser("build").set_defaults(func=build)
    s = sub.add_parser("search")
    s.add_argument("query", nargs="?", default="")
    s.add_argument("--journal", choices=[j["id"] for j in JOURNALS])
    s.add_argument("--year", type=int)
    s.add_argument("--missing-abstract", action="store_true")
    s.add_argument("--limit", type=int, default=20)
    s.set_defaults(func=search)
    i = sub.add_parser("import-paper")
    i.add_argument("identifier")
    i.set_defaults(func=import_paper)
    sub.add_parser("validate").set_defaults(func=validate)
    args = p.parse_args(argv)
    args.func(args)
