from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path
from typing import Any

from cairn.errors import CairnError, Conflict, Denied
from cairn.ingest.service import capture_bytes
from cairn.library.models import (
    FileLocation,
    Journal,
    LibraryConfig,
    MetadataEvidence,
    Paper,
    ReadingState,
    ScanReport,
    metadata,
    normalize_doi,
    set_metadata,
)
from cairn.library.store import commit_unlocked, entities_unlocked, entity_bytes, record_path
from cairn.records.models import Record, canonical, digest, new_id, now
from cairn.storage.files import MAX_FILE_BYTES, RootFS, disjoint
from cairn.storage.workspace import Workspace

CONFIG_PATH = "receipts/library/config.json"


def check_library_root(ws: Workspace, root: Path) -> Path:
    if not root.is_absolute() or any(p.is_symlink() for p in (root, *root.parents)):
        raise Denied("library requires an absolute non-symlink root")
    resolved = root.resolve(strict=True)
    if not resolved.is_dir() or resolved == Path.home() or resolved == Path("/"):
        raise Denied("select a dedicated library directory")
    if not disjoint(resolved, ws.root) or any(
        not disjoint(resolved, Path(code)) for code in ws.config.code_roots
    ):
        raise Denied("library, workspace, and code roots must be disjoint")
    return resolved


def configure(ws: Workspace, config: LibraryConfig) -> LibraryConfig:
    check_library_root(ws, Path(config.root))
    with ws.lock(write=True):
        scope = ws.policy.scope(config.scope)
        scope.require(new_entity("Library", Journal(folder="library")))
        if ws.fs.exists(CONFIG_PATH):
            old = LibraryConfig.model_validate_json(ws.fs.read(CONFIG_PATH))
            if old != config:
                raise Conflict("library root already configured; relocation requires migration")
        commit_unlocked(ws, {CONFIG_PATH: canonical(config)}, "configure")
    return config


def config_unlocked(ws: Workspace) -> LibraryConfig:
    if not ws.fs.exists(CONFIG_PATH):
        raise CairnError("library is not configured")
    return LibraryConfig.model_validate_json(ws.fs.read(CONFIG_PATH))


def new_entity(title: str, value: Journal | Paper) -> Record:
    stamp = now()
    record = Record(
        id=new_id("entity"),
        type="entity",
        title=title[:500] or "Untitled paper",
        domain="research",
        created_at=stamp,
        updated_at=stamp,
        status="active",
    )
    set_metadata(record, value)
    return record


def register_journal(ws: Workspace, title: str, value: Journal) -> Record:
    with ws.lock(write=True):
        config = config_unlocked(ws)
        records = entities_unlocked(ws, config.scope)
        matches = [
            r
            for r in records
            if isinstance(m := metadata(r), Journal)
            and value.folder in (m.folder, *m.folder_aliases)
        ]
        match = next((r for r in matches if r.title == title), None)
        if match is None and len(matches) > 1:
            raise Conflict("journal folder has multiple identities; resolve explicitly")
        match = match or (matches[0] if matches else None)
        record = match or new_entity(title, value)
        record.title = title
        record.updated_at = now()
        ws.policy.scope(config.scope).require(record)
        set_metadata(record, value)
        commit_unlocked(ws, {record_path(record): entity_bytes(record)}, "register_journal")
        return record


def list_entities(ws: Workspace, scope: str, kind: str) -> list[Record]:
    with ws.lock():
        return [
            r
            for r in entities_unlocked(ws, scope)
            if (value := metadata(r)) is not None and value.kind == kind
        ]


def get_paper(ws: Workspace, paper_id: str, scope: str) -> tuple[Record, Paper]:
    _, record, _ = ws.record(paper_id, ws.policy.scope(scope))
    value = metadata(record)
    if not isinstance(value, Paper):
        raise CairnError("record is not a library paper")
    return record, value


def mark(ws: Workspace, paper_id: str, reading: ReadingState, *, scope: str) -> Record:
    with ws.lock(write=True):
        record, value = get_paper(ws, paper_id, scope)
        if value.reading != reading:
            value.reading = reading
            record.updated_at = now()
            set_metadata(record, value)
            commit_unlocked(ws, {record_path(record): entity_bytes(record)}, "owner_reading")
        return record


def correct(ws: Workspace, paper_id: str, fields: dict[str, Any], *, scope: str) -> Record:
    allowed = {
        "title",
        "doi",
        "authors",
        "year",
        "published",
        "volume",
        "issue",
        "pages",
        "abstract",
        "priority",
        "topics",
        "note_ids",
    }
    if not fields or not fields.keys() <= allowed:
        raise Denied("unsupported owner correction")
    with ws.lock(write=True):
        record, value = get_paper(ws, paper_id, scope)
        for linked in fields.get("note_ids", []):
            ws.record(linked, ws.policy.scope(scope))
        if "title" in fields:
            record.title = fields["title"]
        for key, val in fields.items():
            if key != "title":
                setattr(value, key, val)
            value.owner_fields.add(key)
            value.metadata_evidence[key] = MetadataEvidence(origin="owner", observed_at=now())
        record.updated_at = now()
        set_metadata(record, value)
        commit_unlocked(ws, {record_path(record): entity_bytes(record)}, "owner_correction")
        return record


def inspect_pdf(ws: Workspace, data: bytes) -> dict[str, Any]:
    if ws.config.synthetic:
        from cairn.library.pdf import inspect_metadata

        return inspect_metadata(data)
    import base64

    from cairn.adapters.isolation import invoke_worker

    if not ws.config.worker_image:
        raise Denied("isolated PDF metadata extraction unavailable")
    result = json.loads(
        invoke_worker(
            ws.config.worker_image,
            canonical(
                {
                    "operation": "inspect_pdf",
                    "data": base64.b64encode(data).decode(),
                }
            ),
        )
    )
    if not isinstance(result, dict):
        raise CairnError("invalid PDF metadata result")
    return result


def scan(ws: Workspace, *, extract_metadata: bool = True, rehash: bool = False) -> ScanReport:
    with ws.lock():
        config = config_unlocked(ws)
        records = entities_unlocked(ws, config.scope)
        config_hash = digest(canonical(config))
        initial_hashes = {r.id: digest(ws.fs.read(record_path(r))) for r in records}
        baseline = not ws.fs.exists("receipts/library/last_scan.json")
    report = ScanReport(id=new_id("scan"), at=now(), baseline=baseline)
    try:
        root = check_library_root(ws, Path(config.root))
    except (OSError, CairnError):
        report.complete = False
        report.issues["library"] = "offline_or_inaccessible"
        return report
    fs = RootFS(root)
    journals: dict[str, list[Record]] = {}
    papers: dict[str, tuple[Record, Paper]] = {}
    by_path: dict[str, str] = {}
    by_hash: dict[str, set[str]] = {}
    by_doi: dict[str, set[str]] = {}
    outputs: dict[str, bytes] = {}
    for record in records:
        value = metadata(record)
        if isinstance(value, Journal):
            journals.setdefault(value.folder, []).append(record)
            for alias in value.folder_aliases:
                journals.setdefault(alias, []).append(record)
        elif isinstance(value, Paper):
            papers[record.id] = record, value
            if value.doi:
                by_doi.setdefault(value.doi, set()).add(record.id)
            for known_location in value.files:
                by_path[known_location.path] = record.id
                by_hash.setdefault(known_location.content_hash, set()).add(record.id)
    seen: set[str] = set()

    def walk_error(error: OSError) -> None:
        report.complete = False
        report.issues["directory"] = "inaccessible_directory"

    for directory, dirs, files in os.walk(root, followlinks=False, onerror=walk_error):
        parent = Path(directory)
        for name in list(dirs):
            path = parent / name
            if name.startswith("."):
                dirs.remove(name)
            elif path.is_symlink():
                dirs.remove(name)
                report.complete = False
                report.issues[path.relative_to(root).as_posix()] = "symlink_denied"
            elif parent == root and name not in journals:
                journal = new_entity(name, Journal(folder=name))
                journals[name] = [journal]
                outputs[record_path(journal)] = entity_bytes(journal)
        for name in sorted(files):
            if name.startswith("."):
                continue
            path = parent / name
            relative = path.relative_to(root).as_posix()
            try:
                from cairn.storage.files import components

                parts = components(relative)
                if len(parts) < 2 or path.suffix.lower() != ".pdf":
                    report.issues[relative] = "unsupported_or_outside_journal"
                    continue
                info = path.lstat()
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    raise Denied("not a regular file")
                seen.add(relative)
                previous_id = by_path.get(relative)
                previous = papers.get(previous_id or "")
                location = (
                    next((f for f in previous[1].files if f.path == relative), None)
                    if previous
                    else None
                )
                if (
                    location
                    and location.availability == "available"
                    and not rehash
                    and info.st_size == location.size
                    and info.st_mtime_ns == location.mtime_ns
                ):
                    report.unchanged += 1
                    continue
                data = None
                if info.st_size > MAX_FILE_BYTES:
                    report.issues[relative] = "PDF_exceeds_processing_limit"
                    checksum = hashlib.sha256()
                    with fs.parent(relative) as (fd, leaf):
                        file_fd = os.open(
                            leaf, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd
                        )
                        with os.fdopen(file_fd, "rb") as stream:
                            fs._regular(os.fstat(stream.fileno()))
                            for block in iter(lambda: stream.read(1024 * 1024), b""):
                                checksum.update(block)
                    content_hash = checksum.hexdigest()
                else:
                    data = fs.read(relative)
                    content_hash = digest(data)
                after = path.lstat()
                if (info.st_ino, info.st_size, info.st_mtime_ns) != (
                    after.st_ino,
                    after.st_size,
                    after.st_mtime_ns,
                ):
                    raise Conflict("file changed during scan")
                observed: dict[str, Any] = {}
                if extract_metadata and data is not None:
                    try:
                        observed = inspect_pdf(ws, data)
                    except (CairnError, ValueError):
                        report.issues[relative] = "metadata_unavailable"
                doi = normalize_doi(observed.get("doi"))
                candidates = by_hash.get(content_hash, set()) | (
                    by_doi.get(doi, set()) if doi else set()
                )
                if previous_id:
                    candidates.add(previous_id)
                if len(candidates) > 1:
                    report.issues[relative] = "identity_conflict"
                    report.complete = False
                    continue
                if parts[0] not in journals:
                    journal = new_entity(parts[0], Journal(folder=parts[0]))
                    journals[parts[0]] = [journal]
                    outputs[record_path(journal)] = entity_bytes(journal)
                journal_ids = [r.id for r in journals[parts[0]]]
                paper_id = next(iter(candidates), None)
                if paper_id:
                    record, paper = papers[paper_id]
                    old = canonical(paper)
                    if doi and paper.doi and paper.doi != doi:
                        report.issues[relative] = "DOI_changed_requires_review"
                        report.complete = False
                        continue
                    if not location and paper.files:
                        report.moved.append(record.id)
                    else:
                        report.changed.append(record.id)
                else:
                    paper = Paper(journal_ids=journal_ids, first_seen=report.at)
                    record = new_entity(observed.get("title") or path.stem, paper)
                    paper_id = record.id
                    papers[paper_id] = record, paper
                    report.added.append(paper_id)
                    old = b""
                paper.journal_ids = sorted(set(paper.journal_ids + journal_ids))
                new_location = FileLocation(
                    path=relative,
                    content_hash=content_hash,
                    size=info.st_size,
                    mtime_ns=info.st_mtime_ns,
                    source_id=location.source_id
                    if location and location.content_hash == content_hash
                    else None,
                )
                paper.files = [f for f in paper.files if f.path != relative] + [new_location]
                if data is not None:
                    preserved = capture_bytes(
                        ws,
                        data,
                        origin=f"library:{config.id}/{relative}",
                        identity=f"library-paper:{paper_id}",
                        title=record.title,
                        domain="research",
                        source_type="pdf",
                        classification=record.classification,
                        processing=record.processing,
                        compartments=record.compartments,
                        project_ids=record.project_ids,
                        library_alias="cairn_library",
                        scope_name=config.scope,
                    )
                    new_location.source_id = preserved.id
                    paper.source_ids = sorted(set([*paper.source_ids, preserved.id]))
                snapshot = None
                if observed:
                    snapshot = capture_bytes(
                        ws,
                        canonical({"pdf_hash": content_hash, "observed": observed}),
                        origin=f"pdf-metadata:{content_hash}",
                        identity=f"library-pdf-metadata:{content_hash}",
                        title="Observed PDF bibliographic metadata",
                        domain="research",
                        source_type="bibliography",
                        scope_name=config.scope,
                        classification=record.classification,
                        compartments=record.compartments,
                        project_ids=record.project_ids,
                    )
                    paper.source_ids = sorted(set([*paper.source_ids, snapshot.id]))
                for key in ("title", "authors", "doi", "year"):
                    val = observed.get(key)
                    if val and key not in paper.owner_fields:
                        if key == "title":
                            record.title = str(val)[:500]
                        else:
                            setattr(paper, key, val)
                        paper.metadata_evidence[key] = MetadataEvidence(
                            origin=f"pdf:{content_hash}",
                            source_id=snapshot.id if snapshot else None,
                            observed_at=report.at,
                        )
                if old != canonical(paper):
                    record.updated_at = max(report.at, record.created_at)
                    set_metadata(record, paper)
                    outputs[record_path(record)] = entity_bytes(record)
                by_path[relative] = paper_id
                by_hash.setdefault(content_hash, set()).add(paper_id)
                if paper.doi:
                    by_doi.setdefault(paper.doi, set()).add(paper_id)
            except (OSError, CairnError, ValueError):
                report.complete = False
                report.issues[relative] = "unavailable_or_unsafe"
    if by_path and not seen:
        report.complete = False
        report.issues["library"] = "empty_scan_cannot_confirm_online_availability"
    if report.complete:
        for record, paper in papers.values():
            changed = False
            for location in paper.files:
                if location.path not in seen and location.availability != "missing":
                    location.availability = "missing"
                    changed = True
            if changed:
                report.missing.append(record.id)
                record.updated_at = report.at
                set_metadata(record, paper)
                outputs[record_path(record)] = entity_bytes(record)
    with ws.lock(write=True):
        if digest(canonical(config_unlocked(ws))) != config_hash:
            raise Conflict("library configuration changed during scan")
        current = {
            r.id: digest(ws.fs.read(record_path(r))) for r in entities_unlocked(ws, config.scope)
        }
        if current != initial_hashes:
            raise Conflict("catalog changed during scan; retry without overwriting owner edits")
        from cairn.storage.markdown import decode

        for output_path, data in outputs.items():
            if output_path.startswith("vault/"):
                ws.policy.scope(config.scope).require(decode(data)[0])
        outputs[f"receipts/library/scans/{report.id}.json"] = canonical(report)
        if report.complete:
            outputs["receipts/library/last_scan.json"] = canonical(report)
        commit_unlocked(ws, outputs, "scan")
    return report
