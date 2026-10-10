"""Opt-in Markdown projections. Failures never undo the canonical transaction."""

from pathlib import Path
from typing import Literal

from pydantic import model_validator

from cairn.errors import CairnError, Conflict, Denied
from cairn.policies.models import Operation
from cairn.presentation.render import render_bundle
from cairn.presentation.service import assemble, output_bytes, recheck, renderer_identity
from cairn.records.models import ID, Digest, Labels, Model, canonical, digest
from cairn.storage.files import RootFS, components, disjoint
from cairn.storage.workspace import Workspace

PREFIX = "receipts/presentation/renders"


class Rendering(Model):
    id: ID
    record_id: ID
    scope: ID
    output: str
    route: tuple[str, str] | None = None
    dependencies: dict[str, Digest] = {}
    policy_hash: Digest | None = None
    renderer: str = ""
    checksum: Digest | None = None
    pending_checksum: Digest | None = None
    active: bool = False
    status: Literal["current", "stale", "inactive"] = "inactive"
    error: str | None = None

    @model_validator(mode="after")
    def checked(self) -> "Rendering":
        output = Path(self.output)
        if not output.is_absolute():
            raise ValueError("render output must be absolute")
        components(output.relative_to(output.anchor).as_posix())
        for path in self.dependencies:
            components(path)
        if self.id != rendering_id(self.record_id, self.scope, output):
            raise ValueError("rendering identity mismatch")
        return self


def rendering_id(record_id: str, scope: str, output: Path) -> str:
    return "render_" + digest(canonical([record_id, scope, str(output.absolute())]))[:32]


def safe_destination(ws: Workspace, output: Path) -> None:
    if any(p.is_symlink() for p in (output, *output.parents)) or not disjoint(output, ws.root):
        raise Denied("HTML destination must be outside the knowledge base without symlinks")
    if any(not disjoint(output, Path(p)) for p in ws.config.code_roots):
        raise Denied("HTML destination must be outside public code")
    components(output.absolute().relative_to(output.anchor).as_posix())


def output_hash(ws: Workspace, output: Path) -> str | None:
    safe_destination(ws, output)
    fs = RootFS(Path(output.anchor))
    path = output.relative_to(output.anchor).as_posix()
    return digest(fs.read(path)) if fs.exists(path) else None


def registrations(ws: Workspace) -> list[Rendering]:
    return [Rendering.model_validate_json(ws.fs.read(p)) for p in ws.fs.files(PREFIX)]


def deactivate(fs: RootFS) -> None:
    """A backup cannot authorize writing to the original machine's destinations."""
    for path in fs.files(PREFIX):
        registration = Rendering.model_validate_json(fs.read(path))
        registration.active = False
        registration.pending_checksum = None
        registration.status = "inactive"
        registration.error = "Restored: explicitly render to rebind an output destination."
        fs.write(path, canonical(registration))


def _render(ws: Workspace, entry: Rendering, *, inline_synthetic: bool) -> Rendering:
    path = f"{PREFIX}/{entry.id}.json"
    with ws.lock():
        previous = ws.fs.read(path) if ws.fs.exists(path) else None
    bundle = assemble(
        ws, "page", scope=entry.scope, object_id=entry.record_id, cloud_route=entry.route
    )
    html = render_bundle(ws, bundle, inline_synthetic=inline_synthetic)
    with ws.lock(write=True):
        recheck(ws, bundle)
        if entry.route:
            scope = ws.policy.scope(entry.scope)
            ws.policy.authorize_route(
                scope,
                [ws.record(k, scope)[1] for k in bundle.record_ids],
                route="cloud",
                provider=entry.route[0],
                destination=entry.route[1],
                operation="client_export",
                question=Labels(domain=sorted(scope.domains)[0], processing="cloud_eligible"),
            )
        if (ws.fs.read(path) if ws.fs.exists(path) else None) != previous:
            raise Conflict("render registration changed; retry")
        output = Path(entry.output)
        observed = output_hash(ws, output)
        if observed is not None and observed not in (entry.checksum, entry.pending_checksum):
            raise Conflict("HTML output was modified; preserved; select another destination")
        entry.pending_checksum = digest(html)
        entry.status = "stale"
        ws.fs.write(path, canonical(entry))
        output_bytes(ws, output, html)
        from cairn.transactions.apply import _crash

        _crash(ws, "html:replaced")
        entry.checksum = entry.pending_checksum
        entry.pending_checksum = None
        entry.dependencies = bundle.input_hashes
        entry.policy_hash = bundle.policy_hash
        entry.renderer = bundle.renderer
        entry.active = True
        entry.status = "current"
        entry.error = None
        ws.fs.write(path, canonical(entry))
    return entry


def render_page(
    ws: Workspace,
    record_id: str,
    scope: str,
    output: Path,
    *,
    route: tuple[str, str] | None = None,
    inline_synthetic: bool = False,
) -> Rendering:
    output = output.absolute()
    safe_destination(ws, output)
    key = rendering_id(record_id, scope, output)
    with ws.lock():
        path = f"{PREFIX}/{key}.json"
        entry = (
            Rendering.model_validate_json(ws.fs.read(path))
            if ws.fs.exists(path)
            else Rendering(id=key, record_id=record_id, scope=scope, output=str(output))
        )
        entry.route = route
    return _render(ws, entry, inline_synthetic=inline_synthetic)


def sync(ws: Workspace) -> list[Rendering]:
    with ws.lock():
        entries = registrations(ws)
    for entry in entries:
        if not entry.active and not entry.pending_checksum:
            continue
        try:
            with ws.lock():
                scope = ws.policy.scope(entry.scope)
                ws.record(entry.record_id, scope)
                if entry.route:
                    operations: tuple[Operation, ...] = ("query", "client_export")
                    for operation in operations:
                        ws.policy.authorize_route(
                            scope,
                            [],
                            route="cloud",
                            provider=entry.route[0],
                            destination=entry.route[1],
                            operation=operation,
                            question=Labels(
                                domain=sorted(scope.domains)[0], processing="cloud_eligible"
                            ),
                        )
                unchanged = (
                    entry.status == "current"
                    and entry.policy_hash == ws.policy_hash
                    and entry.renderer == renderer_identity()
                    and all(
                        ws.fs.exists(p) and digest(ws.fs.read(p)) == h
                        for p, h in entry.dependencies.items()
                    )
                )
                if output_hash(ws, Path(entry.output)) != entry.checksum:
                    unchanged = False
            if not unchanged:
                entry = _render(ws, entry, inline_synthetic=ws.config.synthetic)
        except (CairnError, OSError, ValueError):
            # No paths, citations, restricted titles or provider responses in maintenance errors.
            entry.status = "stale"
            entry.error = "Refresh failed; check scope, route, renderer and output integrity."
            with ws.lock(write=True):
                path = f"{PREFIX}/{entry.id}.json"
                current = Rendering.model_validate_json(ws.fs.read(path))
                current.status, current.error = entry.status, entry.error
                ws.fs.write(path, canonical(current))
    with ws.lock():
        return registrations(ws)


def maintain(ws: Workspace) -> None:
    import warnings

    try:
        stale = any(entry.status == "stale" for entry in sync(ws))
    except (CairnError, OSError, ValueError):
        stale = True
    if stale:
        warnings.warn(
            "Markdown is committed; HTML refresh is pending. Run cairn view sync.",
            RuntimeWarning,
            stacklevel=2,
        )
