from __future__ import annotations

import io
import os
import stat
import tempfile
import zipfile
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from cairn.errors import CairnError, Conflict, Denied
from cairn.policies.audit import PolicyChange, RouteAudit, policy_changes
from cairn.policies.models import Policy
from cairn.proposals.models import Approval, JobEnvelope, Proposal
from cairn.proposals.service import all_refs, target_path
from cairn.records.json import read_json
from cairn.records.models import ID, Digest, Event, Extraction, Model, Record, canonical, digest
from cairn.records.runtime import ReviewAcknowledgement, RuntimeApproval
from cairn.storage.activation import check_runtime_metadata, prepare_activation
from cairn.storage.files import MAX_FILE_BYTES, RootFS, components, disjoint
from cairn.storage.history_safety import check_history_config, check_history_paths
from cairn.storage.markdown import decode
from cairn.storage.workspace import Workspace, WorkspaceConfig, check_roots
from cairn.transactions.apply import ApplyReceipt, Transaction

DURABLE_DIRS = (
    "vault",
    "blobs",
    "evidence",
    "policy",
    "proposals",
    "approvals",
    "receipts",
    "journal",
    "history.git",
)
MAX_BACKUP_BYTES = 256 * 1024 * 1024
MAX_ARCHIVE_BYTES = MAX_BACKUP_BYTES + 16 * 1024 * 1024


class BackupManifest(Model):
    schema_version: Literal[1] = 1
    workspace_id: ID
    files: dict[str, Digest]


def _paths(names: list[str]) -> None:
    """Validate the whole namespace, including directories, before writing anything."""
    seen: dict[tuple[str, ...], tuple[str, ...]] = {}
    files: set[tuple[str, ...]] = set()
    for name in names:
        parts = components(name)
        if (
            ".git" in parts
            or (len(parts) == 1 and name not in ("workspace.json", "manifest.json"))
            or (len(parts) > 1 and parts[0] not in DURABLE_DIRS)
        ):
            raise Denied("archive contains an unauthorized member")
        key = tuple(part.casefold() for part in parts)
        if key in files:
            raise Denied("duplicate archive member")
        files.add(key)
        for length in range(1, len(parts) + 1):
            prefix, folded = parts[:length], key[:length]
            if folded in seen and seen[folded] != prefix:
                raise Denied("ambiguous case or Unicode archive path")
            seen[folded] = prefix
    if any(prefix[:length] in files for prefix in files for length in range(1, len(prefix))):
        raise Denied("archive file/directory collision")
    check_history_paths(names)


def validate_payloads(payloads: dict[str, bytes]) -> WorkspaceConfig:
    """Validate durable structures and evidence without executing restored content."""
    _paths(list(payloads))
    if "workspace.json" not in payloads or "policy/workspace.json" not in payloads:
        raise CairnError("backup omits workspace configuration or policy")
    try:
        config = WorkspaceConfig.model_validate(read_json(payloads["workspace.json"]))
        if not config.synthetic:
            check_runtime_metadata(config, payloads.__getitem__)
        policy = Policy.model_validate(read_json(payloads["policy/workspace.json"]))
        policy_changes(
            digest(payloads["policy/workspace.json"]), policy, payloads.__getitem__, config.id
        )
        if "history.git/config" in payloads:
            check_history_config(payloads["history.git/config"])
        elif any(path.startswith("history.git/") for path in payloads):
            raise CairnError("backup omits history configuration")
        records: dict[str, Record] = {}
        evidence: dict[str, Extraction] = {}
        transactions: list[Transaction] = []
        for path, raw in payloads.items():
            if path.startswith(
                ("vault/sources/", "vault/wiki/", "vault/decisions/")
            ) and path.endswith(".md"):
                record, _ = decode(raw)
                expected = (
                    f"vault/sources/{record.id}.md"
                    if record.type == "source"
                    else target_path(record)
                )
                if path != expected or record.id in records:
                    raise Conflict("backup record identity/path mismatch")
                records[record.id] = record
            elif path.startswith("blobs/"):
                if path != f"blobs/{digest(raw)}":
                    raise Conflict("backup blob checksum mismatch")
            elif path.startswith("evidence/"):
                if path != f"evidence/{digest(raw)}.json":
                    raise Conflict("backup extraction checksum mismatch")
                evidence[digest(raw)] = Extraction.model_validate(read_json(raw))
            elif path.startswith("proposals/jobs/"):
                job = JobEnvelope.model_validate(read_json(raw))
                if path != f"proposals/jobs/{job.job.id}.json":
                    raise Conflict("backup job identity mismatch")
            elif path.startswith("proposals/"):
                proposal = Proposal.model_validate(read_json(raw))
                if path != f"proposals/{proposal.id}.json" or proposal.workspace_id != config.id:
                    raise Conflict("backup proposal identity mismatch")
            elif path.startswith("approvals/"):
                approval = Approval.model_validate(read_json(raw))
                if (
                    path != f"approvals/{approval.proposal_id}.json"
                    or approval.workspace_id != config.id
                ):
                    raise Conflict("backup approval identity mismatch")
            elif path.startswith("receipts/events/"):
                event = Event.model_validate(read_json(raw))
                if path != f"receipts/events/{event.id}.json":
                    raise Conflict("backup event identity mismatch")
            elif path.startswith("receipts/policy/"):
                change = PolicyChange.model_validate(read_json(raw))
                if path != f"receipts/policy/{change.id}.json" or change.workspace_id != config.id:
                    raise Conflict("backup policy audit identity mismatch")
            elif path.startswith("receipts/routes/"):
                audit = RouteAudit.model_validate(read_json(raw))
                if path != f"receipts/routes/{audit.id}.json" or audit.workspace_id != config.id:
                    raise Conflict("backup route audit identity mismatch")
            elif path.startswith("receipts/runtime/"):
                runtime = RuntimeApproval.model_validate(read_json(raw))
                if (
                    path != f"receipts/runtime/{runtime.id}.json"
                    or runtime.workspace_id != config.id
                ):
                    raise Conflict("backup runtime approval identity mismatch")
            elif path.startswith("receipts/applied/"):
                receipt = ApplyReceipt.model_validate(read_json(raw))
                if path != f"receipts/applied/{receipt.proposal_id}.json":
                    raise Conflict("backup receipt identity mismatch")
            elif path.startswith("journal/"):
                transaction = Transaction.model_validate(read_json(raw))
                if path != f"journal/{transaction.id}/transaction.json":
                    raise Conflict("backup transaction identity mismatch")
                transactions.append(transaction)
            elif path.startswith("receipts/") and path.endswith(".json"):
                # Subsystem receipts have independent shapes; reject ambiguous JSON at minimum.
                read_json(raw)
        for record in records.values():
            meta = record.source
            if meta:
                if meta.blob != f"blobs/{meta.content_hash}" or meta.blob not in payloads:
                    raise Conflict("backup omits referenced source bytes")
                if digest(payloads[meta.blob]) != meta.content_hash:
                    raise Conflict("backup source checksum mismatch")
                if meta.extraction:
                    extracted = evidence.get(meta.extraction.evidence_hash)
                    if (
                        extracted is None
                        or extracted.source_id != record.id
                        or extracted.source_hash != meta.content_hash
                    ):
                        raise Conflict("backup evidence/source binding mismatch")
                    for field in (
                        "method",
                        "method_version",
                        "coverage",
                        "tables_inspected",
                        "images_inspected",
                    ):
                        if getattr(meta.extraction, field) != getattr(extracted, field):
                            raise Conflict("backup extraction metadata mismatch")
            for ref in all_refs(record):
                source = records.get(ref.id)
                artifact = evidence.get(ref.evidence_hash)
                if (
                    source is None
                    or source.source is None
                    or artifact is None
                    or (
                        source.source.content_hash != ref.source_hash
                        or artifact.source_id != ref.id
                        or artifact.source_hash != ref.source_hash
                    )
                ):
                    raise Conflict("backup evidence reference unavailable")
                segments = [
                    segment for segment in artifact.segments if segment.locator == ref.locator
                ]
                if not segments or (
                    ref.quote is not None and not any(ref.quote in s.text for s in segments)
                ):
                    raise Conflict("backup evidence locator/quote mismatch")
        for tx in transactions:
            for entry in tx.entries:
                after, _ = decode(entry.after.encode())
                if (
                    entry.path != target_path(after)
                    or digest(entry.after.encode()) != entry.after_hash
                ):
                    raise Conflict("backup journal target/hash mismatch")
                if (entry.before is None) != (entry.before_hash is None) or (
                    entry.before is not None and digest(entry.before.encode()) != entry.before_hash
                ):
                    raise Conflict("backup journal before-image mismatch")
            if tx.status == "prepared":
                proposal_path = f"proposals/{tx.proposal_id}.json"
                approval_path = f"approvals/{tx.proposal_id}.json"
                if proposal_path not in payloads or approval_path not in payloads:
                    raise Conflict("backup omits pending authorization")
                if (
                    digest(payloads[proposal_path]) != tx.proposal_hash
                    or digest(payloads[approval_path]) != tx.approval_hash
                ):
                    raise Conflict("backup pending authorization checksum mismatch")
        return config
    except (ValidationError, KeyError, ValueError, TypeError) as exc:
        raise CairnError("backup contains invalid durable metadata") from exc


def backup(
    ws: Workspace, destination: Path, *, include_pending: bool = False
) -> dict[str, str | int]:
    destination = destination.absolute()
    if not disjoint(destination, ws.root) or any(
        not disjoint(destination, Path(root)) for root in ws.config.code_roots
    ):
        raise Denied("backup destination must be outside workspace and public code")
    with ws.lock(recovery=include_pending):
        contents = {"workspace.json": ws.fs.read("workspace.json")}
        for directory in DURABLE_DIRS:
            for path in ws.fs.files(directory):
                contents[path] = ws.fs.read(path)
        if len(contents) >= 10000 or sum(map(len, contents.values())) > MAX_BACKUP_BYTES:
            raise CairnError("backup exceeds supported size or file count")
        validate_payloads(contents)
        manifest = BackupManifest(
            workspace_id=ws.config.id, files={name: digest(data) for name, data in contents.items()}
        )
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", canonical(manifest))
            for path, data in sorted(contents.items()):
                archive.writestr(path, data)
        output = buffer.getvalue()
        destination.parent.mkdir(parents=True, exist_ok=True)
        RootFS(destination.parent).write(
            destination.name, output, exclusive=True, limit=MAX_ARCHIVE_BYTES
        )
        return {"workspace_id": ws.config.id, "files": len(contents), "sha256": digest(output)}


def restore(
    archive_path: Path,
    destination: Path,
    *,
    code_roots: list[Path],
    expected_sha256: str | None = None,
    synthetic: bool = False,
    release: Path | None = None,
    release_sha256: str | None = None,
    statement: str | None = None,
    acknowledgements: set[ReviewAcknowledgement] | None = None,
) -> Workspace:
    destination = check_roots(destination, code_roots)
    if destination.exists() and any(destination.iterdir()):
        raise Conflict("restore requires an empty destination")
    if synthetic and any((release, release_sha256, statement, acknowledgements)):
        raise Denied("synthetic restore cannot record private release approval")
    if not synthetic and expected_sha256 is None:
        raise Denied("private restore requires an independently recorded archive digest")
    activation = (
        None
        if synthetic
        else prepare_activation(
            release,
            expected_sha256=release_sha256,
            statement=statement,
            acknowledgements=acknowledgements,
        )
    )
    fd = os.open(archive_path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        RootFS._regular(os.fstat(stream.fileno()))
        raw = stream.read(MAX_ARCHIVE_BYTES + 1)
    if len(raw) > MAX_ARCHIVE_BYTES:
        raise CairnError("archive exceeds size limit")
    if expected_sha256 is not None and digest(raw) != expected_sha256:
        raise Conflict("archive differs from the independently recorded digest")
    payloads: dict[str, bytes] = {}
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            members = archive.infolist()
            if (
                len(members) > 10000
                or sum(item.file_size for item in members) > MAX_ARCHIVE_BYTES
                or any(item.file_size > MAX_FILE_BYTES for item in members)
            ):
                raise CairnError("archive expands beyond limits")
            _paths([item.filename for item in members])
            if "workspace.json" in {item.filename for item in members}:
                archived_config = WorkspaceConfig.model_validate(
                    read_json(archive.read("workspace.json"))
                )
                if archived_config.synthetic != synthetic:
                    raise Denied("restore mode does not match the archive workspace")
            for item in members:
                kind = stat.S_IFMT(item.external_attr >> 16)
                if item.is_dir() or kind not in (0, stat.S_IFREG) or item.flag_bits & 1:
                    raise Denied("archive contains an unsupported member")
                payloads[item.filename] = archive.read(item)
        if "manifest.json" not in payloads:
            raise CairnError("backup omits manifest")
        manifest = BackupManifest.model_validate(read_json(payloads.pop("manifest.json")))
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError, ValidationError) as exc:
        raise CairnError("invalid backup archive") from exc
    if sum(map(len, payloads.values())) > MAX_BACKUP_BYTES:
        raise CairnError("backup expands beyond payload limit")
    if manifest.files != {path: digest(data) for path, data in payloads.items()}:
        raise Conflict("backup manifest checksum mismatch")
    config = validate_payloads(payloads)
    if config.id != manifest.workspace_id:
        raise Conflict("backup workspace identity mismatch")
    if config.synthetic != synthetic:
        raise Denied("restore mode does not match the archive workspace")
    if activation:
        if config.runtime_release_hash != digest(activation.raw_manifest):
            raise Denied(
                "private restore requires the original reviewed release; upgrade separately"
            )
        approval = activation.approval(config.id, "restore", archive_hash=digest(raw))
        config.runtime_approval_id = approval.id
        payloads[f"receipts/runtime/{approval.id}.json"] = canonical(approval)
    config.code_roots = [str(root.resolve()) for root in code_roots]
    payloads["workspace.json"] = canonical(config)
    destination.parent.mkdir(parents=True, exist_ok=True)
    # A failed copy never publishes a partial workspace at the requested destination.
    # An abrupt crash can leave an owner-only staging directory with restore.pending.
    with tempfile.TemporaryDirectory(prefix=".cairn-restore-", dir=destination.parent) as temporary:
        staging = Path(temporary) / "workspace"
        staging.mkdir(mode=0o700)
        fs = RootFS(staging)
        fs.write("restore.pending", canonical({"archive_sha256": digest(raw)}), exclusive=True)
        for path, data in sorted(payloads.items()):
            fs.write(path, data, exclusive=True)
        for path, data in payloads.items():
            if digest(fs.read(path)) != digest(data):
                raise Conflict("restored file checksum mismatch")
        fs.remove("restore.pending")
        Workspace(staging)
        if destination.is_symlink() or (destination.exists() and any(destination.iterdir())):
            raise Conflict("restore destination changed during staging")
        os.replace(staging, destination)
        directory = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    return Workspace(destination)
