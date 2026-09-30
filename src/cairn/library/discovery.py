"""Owner-selected public metadata discovery. No PDF downloads or model-chosen URLs."""

from __future__ import annotations

import http.client
import ipaddress
import json
import socket
import ssl
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Callable
from datetime import datetime, timedelta
from html import unescape
from html.parser import HTMLParser
from typing import Any
from urllib.parse import quote, urlencode, urljoin, urlsplit

from pydantic import Field

from cairn.errors import Blocked, CairnError, Conflict, Denied
from cairn.ingest.service import capture_bytes
from cairn.library.catalog import config_unlocked, new_entity
from cairn.library.models import Journal, MetadataEvidence, Paper, metadata, set_metadata
from cairn.library.store import commit_unlocked, entities_unlocked, entity_bytes, record_path
from cairn.records.models import ID, Model, canonical, digest, now
from cairn.storage.workspace import Workspace

MAX_RESPONSE = 8 * 1024 * 1024
Fetch = Callable[[str, set[str]], bytes]


class Publication(Model):
    title: str = Field(min_length=1, max_length=10000)
    external_id: str = Field(min_length=1, max_length=2000)
    doi: str | None = None
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    published: str | None = None
    volume: str | None = None
    issue: str | None = None
    pages: str | None = None
    abstract: str | None = None


class DiscoveryReport(Model):
    journal_id: ID
    added: list[ID] = Field(default_factory=list)
    changed: list[ID] = Field(default_factory=list)
    complete: bool = False
    pages: int = 0
    issue: str | None = None


def public_url(url: str, allowed_hosts: set[str]) -> str:
    parts = urlsplit(url)
    host = parts.hostname or ""
    if (
        parts.scheme != "https"
        or host not in allowed_hosts
        or parts.username
        or parts.password
        or parts.port not in (None, 443)
        or parts.fragment
    ):
        raise Denied("unapproved discovery destination")
    addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(str(a[4][0])).is_global for a in addresses):
        raise Denied("discovery destination is not public")
    return url


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> None:
        raise Denied("discovery redirect requires an explicit source configuration")


def fetch_public(url: str, allowed_hosts: set[str]) -> bytes:
    public_url(url, allowed_hosts)
    parts = urlsplit(url)
    host = parts.hostname or ""
    addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(str(a[4][0])).is_global for a in addresses):
        raise Denied("discovery destination changed to a non-public address")
    connection = http.client.HTTPSConnection(host, timeout=30)
    try:
        # Connect to a checked numeric address, preserving TLS hostname verification.
        # A second DNS lookup inside the HTTP library cannot rebind to a private host.
        raw_socket = socket.create_connection((str(addresses[0][4][0]), 443), timeout=30)
        connection.sock = ssl.create_default_context().wrap_socket(raw_socket, server_hostname=host)
        path = parts.path or "/"
        if parts.query:
            path += "?" + parts.query
        connection.request("GET", path, headers={"User-Agent": "CairnMetadata/0.2"})
        response = connection.getresponse()
        if response.status != 200:
            raise Blocked("publication_source_status_unavailable")
        data = response.read(MAX_RESPONSE + 1)
    except (OSError, http.client.HTTPException) as exc:
        raise Blocked("publication_source_unavailable") from exc
    finally:
        connection.close()
    if len(data) > MAX_RESPONSE:
        raise CairnError("publication response exceeds limit")
    return data


def crossref_items(raw: bytes) -> tuple[list[Publication], str | None]:
    message = json.loads(raw)["message"]
    items = []
    for item in message["items"]:
        if item.get("type") not in (None, "journal-article", "proceedings-article", "book-chapter"):
            continue
        title = item.get("title") or []
        if not title or not item.get("DOI"):
            continue
        date_parts = (item.get("published") or item.get("issued") or {}).get("date-parts", [[]])[0]
        date_value = "-".join(str(v).zfill(2) for v in date_parts) or None
        items.append(
            Publication(
                title=unescape(title[0]),
                external_id="doi:" + item["DOI"].lower(),
                doi=item["DOI"],
                authors=[
                    " ".join(str(a.get(k, "")) for k in ("given", "family")).strip()
                    or a.get("name", "Unknown")
                    for a in item.get("author", [])
                ],
                year=date_parts[0] if date_parts else None,
                published=date_value,
                volume=item.get("volume"),
                issue=item.get("issue"),
                pages=item.get("page"),
                abstract=item.get("abstract"),
            )
        )
    return items, message.get("next-cursor") if message["items"] else None


def feed_items(raw: bytes, source_url: str) -> list[Publication]:
    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise Denied("XML entities are not supported")
    root = ET.fromstring(raw)
    items = []
    for node in root.iter():
        if node.tag.split("}")[-1] not in ("entry", "item"):
            continue
        fields: dict[str, str] = {}
        for child in node:
            key = child.tag.split("}")[-1]
            value = "".join(child.itertext()).strip()
            if key == "link":
                value = child.attrib.get("href", value)
            fields.setdefault(key, value)
        title = fields.get("title")
        identity = fields.get("id") or fields.get("guid") or fields.get("link")
        if title and identity:
            items.append(
                Publication(
                    title=title,
                    external_id=f"{source_url}#{identity}"[:2000],
                    abstract=fields.get("summary") or fields.get("description"),
                )
            )
    return items


class ProceedingsPage(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.fields: dict[str, list[str]] = {}
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "meta" and (attributes.get("name") or "").startswith("citation_"):
            self.fields.setdefault(attributes["name"] or "", []).append(
                attributes.get("content") or ""
            )
        if tag == "a" and attributes.get("href"):
            self.links.append(attributes["href"] or "")


def proceedings_item(raw: bytes, url: str) -> tuple[Publication | None, list[str]]:
    page = ProceedingsPage()
    page.feed(raw.decode("utf-8"))
    fields = page.fields
    title = fields.get("citation_title", [None])[0]
    publication = None
    if title:
        publication = Publication(
            title=title,
            external_id=url,
            authors=fields.get("citation_author", []),
            doi=fields.get("citation_doi", [None])[0],
            published=fields.get("citation_publication_date", [None])[0],
        )
    host = urlsplit(url).hostname
    links = []
    for link in page.links:
        target = urljoin(url, link)
        parts = urlsplit(target)
        if (
            parts.scheme == "https"
            and parts.hostname == host
            and not parts.query
            and not parts.fragment
            and (parts.path.endswith(".html") or parts.path.endswith("/"))
        ):
            links.append(target)
    return publication, sorted(set(links))


def import_publications(
    ws: Workspace,
    journal_id: str,
    publications: list[Publication],
    raw: bytes,
    origin: str,
    scope: str,
) -> tuple[list[str], list[str]]:
    with ws.lock():
        _, journal_record, _ = ws.record(journal_id, ws.policy.scope(scope))
        if not isinstance(metadata(journal_record), Journal):
            raise CairnError("not a journal")
    source = capture_bytes(
        ws,
        raw,
        origin=origin,
        domain="research",
        title=f"Publication metadata: {journal_record.title}",
        identity=f"journal-metadata:{journal_id}:{digest(raw)}",
        source_type="text",
        scope_name=scope,
    )
    added: list[str] = []
    changed: list[str] = []
    with ws.lock(write=True):
        records = entities_unlocked(ws, scope)
        papers = [(r, p) for r in records if isinstance(p := metadata(r), Paper)]
        outputs = {}
        for publication in publications:
            from cairn.library.models import normalize_doi

            doi = normalize_doi(publication.doi)
            matches = [
                (r, p)
                for r, p in papers
                if (doi and p.doi == doi) or publication.external_id in p.external_ids
            ]
            if len(matches) > 1:
                raise Conflict("publication matches multiple catalog entries")
            if matches:
                record, paper = matches[0]
                before = canonical(paper)
                before_title = record.title
            else:
                paper = Paper(journal_ids=[journal_id], first_seen=now())
                record = new_entity(publication.title, paper)
                papers.append((record, paper))
                before, before_title = b"", ""
            paper.journal_ids = sorted(set([*paper.journal_ids, journal_id]))
            for field in (
                "title",
                "doi",
                "authors",
                "year",
                "published",
                "volume",
                "issue",
                "pages",
                "abstract",
            ):
                value = doi if field == "doi" else getattr(publication, field)
                previous = record.title if field == "title" else getattr(paper, field)
                if value and field not in paper.owner_fields and value != previous:
                    if field == "title":
                        record.title = value[:500]
                    else:
                        setattr(paper, field, value)
                    paper.metadata_evidence[field] = MetadataEvidence(
                        origin=origin, source_id=source.id, observed_at=now()
                    )
            paper.external_ids = sorted(set([*paper.external_ids, publication.external_id]))
            # Repeated metadata does not accumulate source references or timestamps.
            if before != canonical(paper) or before_title != record.title:
                paper.source_ids = sorted(set([*paper.source_ids, source.id]))
                record.updated_at = now()
                set_metadata(record, paper)
                outputs[record_path(record)] = entity_bytes(record)
                (changed if matches else added).append(record.id)
        commit_unlocked(ws, outputs, "discover_publications")
    return added, changed


def discover(
    ws: Workspace,
    *,
    fetch: Fetch | None = None,
    journal_id: str | None = None,
    page_budget: int = 100,
) -> list[DiscoveryReport]:
    if fetch is None:
        from cairn.library.fetcher import fetch_isolated

        def fetch(url: str, hosts: set[str]) -> bytes:
            return fetch_isolated(ws, url, hosts)
    if page_budget < 1 or page_budget > 10000:
        raise ValueError("invalid discovery page budget")
    with ws.lock():
        config = config_unlocked(ws)
        journals = [
            r
            for r in entities_unlocked(ws, config.scope)
            if isinstance(metadata(r), Journal) and (journal_id is None or r.id == journal_id)
        ]
    reports = []
    for record in journals:
        journal = metadata(record)
        assert isinstance(journal, Journal)
        report = DiscoveryReport(journal_id=record.id)
        reports.append(report)
        if not journal.resolved or not journal.discovery:
            report.issue = "journal_identity_or_source_unresolved"
            continue
        all_complete = True
        for endpoint in journal.discovery:
            key = digest(canonical(endpoint))
            checkpoint = f"receipts/library/discovery/{record.id}/{key}.json"
            with ws.lock():
                state = json.loads(ws.fs.read(checkpoint)) if ws.fs.exists(checkpoint) else {}
            started = state.get("started") or now().isoformat()
            watermark = state.get("watermark")
            cursor = state.get("cursor") or "*"
            pending = state.get("pending") or ([endpoint.url] if endpoint.url else [])
            visited = set(state.get("visited", []))
            completed = False
            try:
                for _ in range(page_budget):
                    if endpoint.kind == "crossref":
                        params = {"rows": "200", "cursor": cursor}
                        if watermark:
                            since = datetime.fromisoformat(watermark) - timedelta(days=7)
                            params["filter"] = "from-index-date:" + since.date().isoformat()
                        url = (
                            "https://api.crossref.org/journals/"
                            + quote(endpoint.issn or "")
                            + "/works?"
                            + urlencode(params)
                        )
                        hosts = {"api.crossref.org"}
                    else:
                        if not pending:
                            completed = True
                            break
                        url = pending[0]
                        hosts = {urlsplit(endpoint.url or "").hostname or ""}
                    raw = fetch(url, hosts)
                    report.pages += 1
                    next_cursor = None
                    if endpoint.kind == "crossref":
                        publications, next_cursor = crossref_items(raw)
                        completed = next_cursor is None
                        if next_cursor == cursor and not completed:
                            raise CairnError("discovery cursor did not advance")
                        cursor = next_cursor or "*"
                    elif endpoint.kind in ("rss", "atom"):
                        publications = feed_items(raw, url)
                        completed = True
                    else:
                        publication, links = proceedings_item(raw, url)
                        publications = [publication] if publication else []
                        visited.add(url)
                        pending = pending[1:] + [
                            u for u in links if u not in visited and u not in pending
                        ]
                        completed = not pending
                    added, changed = import_publications(
                        ws, record.id, publications, raw, url, config.scope
                    )
                    report.added.extend(added)
                    report.changed.extend(changed)
                    state = {
                        "started": None if completed else started,
                        "watermark": started if completed else watermark,
                        "cursor": None if completed else cursor,
                        "pending": [] if completed else pending,
                        "visited": [] if completed else sorted(visited),
                    }
                    with ws.lock(write=True):
                        commit_unlocked(ws, {checkpoint: canonical(state)}, "discovery_checkpoint")
                    if completed:
                        break
            except (CairnError, ValueError, KeyError, ET.ParseError):
                report.issue = "source_failed_retryable"
            if not completed:
                all_complete = False
        report.complete = all_complete
        if all_complete:
            with ws.lock(write=True):
                _, current, _ = ws.record(record.id, ws.policy.scope(config.scope))
                value = metadata(current)
                assert isinstance(value, Journal)
                if value.discovery != journal.discovery:
                    raise Conflict("journal configuration changed during discovery")
                value.checked_at = now()
                value.watermark = value.checked_at
                value.coverage = (
                    "Registered publication metadata; publisher completeness not assumed"
                )
                if all(e.kind in ("atom", "rss") for e in value.discovery):
                    value.coverage = "Feed updates only; historical coverage incomplete"
                set_metadata(current, value)
                commit_unlocked(
                    ws, {record_path(current): entity_bytes(current)}, "journal_checked"
                )
    return reports
