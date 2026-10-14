#!/usr/bin/env python3
"""Checkpointed public JMLR archive harvester for the catalog updater."""

import gzip
import html
import json
import re
import time
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path

import requests

from .catalog import Client

BASE = "https://jmlr.org/papers/"
CLIENT = Client(0.12)
CLIENT.session.headers["Accept"] = "text/html"
MONTHS = {
    m.lower(): n
    for n, m in enumerate(
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
MONTHS.update({m[:3].lower(): n for m, n in list(MONTHS.items())})


class Tags(HTMLParser):
    def __init__(self):
        super().__init__()
        self.meta = {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag.lower() == "meta" and attrs.get("name", "").startswith("citation_"):
            self.meta.setdefault(attrs["name"], []).append(attrs.get("content", ""))


def plain(value):
    value = re.sub(r"</?(?:p|div|li|h[1-6])\b[^>]*>|<br\b[^>]*>", " ", value or "", flags=re.I)
    value = html.unescape(re.sub(r"<[^>]+>", "", value))
    return re.sub(r"\s+", " ", value).strip()


def stamp():
    return datetime.now(UTC).isoformat(timespec="seconds")


def atomic(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def get(url):
    return CLIENT.get(url).text


def abs_link_and_authors(dd, index_url):
    link = next(
        (
            m
            for m in re.finditer(
                r'<a\b[^>]*href\s*=\s*(?:["\']([^"\']+)["\']|([^\s>]+))[^>]*>(.*?)</a>',
                dd,
                re.I | re.S,
            )
            if "abs" in plain(m.group(3)).lower() and ".html" in (m.group(1) or m.group(2)).lower()
        ),
        None,
    )
    if not link:
        return None, []
    byline = re.search(r"<b>\s*<i>(.*?)</b>", dd, re.I | re.S)
    authors = [plain(x) for x in byline.group(1).split(",") if plain(x)] if byline else []
    url = requests.compat.urljoin(index_url, link.group(1) or link.group(2))
    # A few legacy volume indexes contain a doubled slash before the article
    # slug. It is only a path separator typo; the canonical HTTPS URL resolves.
    parts = requests.utils.urlparse(url)
    path = re.sub(r"/+", "/", parts.path)
    url = requests.utils.urlunparse(("https", "jmlr.org", path, "", parts.query, ""))
    return url, authors


def toc_articles(index, index_url):
    articles = {}
    for chunk in re.split(r"<dt\b[^>]*>", index, flags=re.I)[1:]:
        title_part, sep, dd = chunk.partition("<dd")
        if not sep:
            continue
        dd = dd.split("</dl", 1)[0]
        url, authors = abs_link_and_authors(dd, index_url)
        if url:
            articles[url] = {"title": plain(title_part), "authors": authors}
    return articles


def abstract_text(source_html):
    # Current JMLR pages wrap the full abstract in this paragraph; its closing
    # tag prevents the following links, copyright and footer from being included.
    match = re.search(
        r'<p\b[^>]*class=["\'][^"\']*\babstract\b[^"\']*["\'][^>]*>(.*?)</p\s*>',
        source_html,
        re.I | re.S,
    )
    if match:
        return plain(match.group(1)) or None
    # Older pages label the next paragraph with an Abstract heading.
    heading = re.search(r"<h[1-6]\b[^>]*>\s*Abstract\s*</h[1-6]\s*>", source_html, re.I | re.S)
    if not heading:
        return None
    paragraph = re.search(r"<p\b[^>]*>(.*?)</p\s*>", source_html[heading.end() :], re.I | re.S)
    return plain(paragraph.group(1)) or None if paragraph else None


def record_for(url, source_html, toc, volume):
    parser = Tags()
    parser.feed(source_html)
    meta = parser.meta

    def one(key):
        return (meta.get("citation_" + key) or [None])[0]

    title = one("title") or toc["title"]
    author_meta = meta.get("citation_author", [])
    authors = toc["authors"] or [x for x in author_meta if x]
    raw_date = one("publication_date") or ""
    date = None
    precision = None
    date_match = re.search(r"\b(\d{4})(?:[-/](\d{1,2})(?:[-/](\d{1,2}))?)?\b", raw_date)
    if date_match:
        y, month, day = date_match.groups()
        if month:
            date = f"{y}-{int(month):02d}"
            precision = "month"
        else:
            issue = (one("issue") or "").lower().strip()
            if issue in MONTHS:
                date = f"{y}-{MONTHS[issue]:02d}"
                precision = "month"
            else:
                date = y
                precision = "year"
        if day and month:
            date = f"{y}-{int(month):02d}-{int(day):02d}"
            precision = "day"
    issue_meta = one("issue")
    article_number = str(issue_meta) if issue_meta and str(issue_meta).isdigit() else None
    first, last = one("firstpage"), one("lastpage")
    pages = first + ("-" + last if last and last != first else "") if first else None
    year = int(date[:4]) if date else None
    return {
        "title": title,
        "authors": authors,
        "volume": one("volume") or str(volume),
        "issue": None,
        "article_number": article_number,
        "pages": pages,
        "date": date,
        "date_precision": precision,
        "published_online": date,
        "year": year,
        "url": url,
        "abstract": abstract_text(source_html),
        "doi": None,
        "id": url,
    }


def write_payload(path, payload):
    tmp = path.with_suffix(".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    tmp.replace(path)


def reconcile_cached_payload(payload):
    url = payload["request"]["url"]
    toc = toc_articles(payload["html"]["index"], url)
    html_by_url = {x["url"]: x["html"] for x in payload["html"]["articles"]}
    repaired = []
    for record in payload["records"]:
        source_html = html_by_url.get(record.get("url"))
        toc_record = toc.get(record.get("url"))
        if source_html and toc_record:
            repaired.append(
                record_for(record["url"], source_html, toc_record, record.get("volume"))
            )
        else:
            repaired.append(record)
    payload["records"] = repaired
    return payload


def migrate_volume_files(folder, state):
    """Convert an interrupted earlier run's per-volume files to canonical pages."""
    volume_files = sorted(
        folder.glob("volume-*.json.gz"), key=lambda p: int(re.search(r"(\d+)", p.stem).group(1))
    )
    mapping = state.get("volume_to_page") or {}
    for volume_file in volume_files:
        volume = int(re.search(r"(\d+)", volume_file.stem).group(1))
        if str(volume) in mapping:
            continue
        with gzip.open(volume_file, "rt", encoding="utf-8") as f:
            payload = json.load(f)
        payload = reconcile_cached_payload(payload)
        page_no = max(mapping.values(), default=0) + 1
        write_payload(folder / f"page-{page_no:05d}.json.gz", payload)
        mapping[str(volume)] = page_no
        volume_file.unlink()
    if mapping:
        state["volume_to_page"] = mapping
        state["pages"] = len(mapping)
        state["retrieved"] = sum(
            len(
                json.load(gzip.open(folder / f"page-{n:05d}.json.gz", "rt", encoding="utf-8"))[
                    "records"
                ]
            )
            for n in mapping.values()
        )
        state["updated_at"] = stamp()
        atomic(folder / "state.json", state)


def harvest_jmlr(root: Path, refresh=False):
    """Harvest the public JMLR archive under catalog ``root`` with checkpoints.

    Closed volume TOCs and article pages are reused on routine updates. The
    current volume index is rechecked each run, fetching only newly listed
    article pages. ``refresh=True`` re-fetches all indexed volumes and pages.
    """
    folder = Path(root) / "raw" / "journal_archive" / "jmlr"
    folder.mkdir(parents=True, exist_ok=True)
    state_path = folder / "state.json"
    state = (
        json.loads(state_path.read_text())
        if state_path.exists()
        else {
            "pages": 0,
            "retrieved": 0,
            "complete": False,
            "started_at": stamp(),
            "volume_to_page": {},
        }
    )
    migrate_volume_files(folder, state)
    state["complete"] = False
    state["updated_at"] = stamp()
    atomic(state_path, state)
    root_html = get(BASE)
    volume_links = re.findall(r'href\s*=\s*["\']([^"\']+)["\']', root_html, re.I)
    home_html = get("https://www.jmlr.org/")
    home_links = re.findall(r'href\s*=\s*["\']([^"\']+)["\']', home_html, re.I)
    (folder / "homepage.html").write_text(home_html, encoding="utf-8")
    volumes = sorted(
        {
            int(match.group(1))
            for link in volume_links + home_links
            if (match := re.search(r"(?:^|/)v(\d+)/?$", link, re.I))
        },
        reverse=True,
    )
    if not volumes:
        raise RuntimeError("No JMLR volume links found")
    expected = list(range(1, max(volumes) + 1))
    if sorted(volumes) != expected:
        state.update(
            {"complete": False, "archive_gap_volumes": sorted(set(expected) - set(volumes))}
        )
        atomic(state_path, state)
        raise RuntimeError(f"JMLR volume index has gaps: {state['archive_gap_volumes']}")
    (folder / "index.html").write_text(root_html, encoding="utf-8")
    mapping = state.setdefault("volume_to_page", {})
    cached_records = {}
    for volume, page_no in mapping.items():
        page_path = folder / f"page-{page_no:05d}.json.gz"
        if page_path.exists():
            with gzip.open(page_path, "rt", encoding="utf-8") as f:
                old = json.load(f)
            cached_records[int(volume)] = old
    for volume in sorted(volumes):
        index_url = f"{BASE}v{volume}/"
        is_latest = volume >= max(volumes) - 1
        old_payload = cached_records.get(volume)
        old_count = len(toc_articles(old_payload["html"]["index"], index_url)) if old_payload else 0
        old_complete = bool(old_payload and len(old_payload.get("records", [])) == old_count)
        if old_payload and not refresh and not is_latest and old_complete:
            continue
        index_html = (
            old_payload["html"]["index"]
            if old_payload and not refresh and not is_latest
            else get(index_url)
        )
        articles = toc_articles(index_html, index_url)
        old_html = (
            {x["url"]: x["html"] for x in old_payload.get("html", {}).get("articles", [])}
            if old_payload
            else {}
        )
        records, article_html = [], []
        for url, toc in articles.items():
            source_html = old_html.get(url) if old_payload and not refresh else None
            if source_html is None:
                source_html = get(url)
                time.sleep(0.12)
            records.append(record_for(url, source_html, toc, volume))
            article_html.append({"url": url, "html": source_html})
        payload = {
            "source": "journal_archive",
            "journal_id": "jmlr",
            "retrieved_at": stamp(),
            "request": {"url": index_url},
            "records": records,
            "html": {"index": index_html, "articles": article_html},
        }
        page_no = mapping.get(str(volume))
        if page_no is None:
            page_no = max(mapping.values(), default=0) + 1
            mapping[str(volume)] = page_no
        write_payload(folder / f"page-{page_no:05d}.json.gz", payload)
        state.update(
            {
                "volume_to_page": mapping,
                "pages": len(mapping),
                "source_total_pages": len(volumes),
                "retrieved": sum(
                    len((cached_records.get(int(v)) or {}).get("records", []))
                    if int(v) != volume
                    else len(records)
                    for v in mapping
                ),
                "archive_index_volumes": volumes,
                "latest_volume": max(volumes),
                "updated_at": stamp(),
            }
        )
        atomic(state_path, state)
        cached_records[volume] = payload
        print(f"jmlr archive volume {volume}: {len(records)} papers staged", flush=True)
    state["complete"] = sorted(map(int, mapping)) == expected and all(
        (folder / f"page-{page_no:05d}.json.gz").exists() for page_no in mapping.values()
    )
    state.pop("archive_gap_volumes", None)
    state.pop("root_index_html", None)
    state["updated_at"] = stamp()
    atomic(state_path, state)
    print(
        f"jmlr archive complete={state['complete']}: {state['retrieved']} papers in {state['pages']} volumes"
    )
