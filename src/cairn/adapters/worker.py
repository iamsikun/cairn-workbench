"""Unprivileged worker: one JSON request in, one JSON result out; no owner APIs."""

import base64
import json
import sys

from cairn.ingest.extractors import extract_bytes
from cairn.records.models import Record, canonical
from cairn.records.runtime import ProbeRequest


def main() -> None:
    raw = sys.stdin.buffer.read(48 * 1024 * 1024 + 1)
    try:
        if len(raw) > 48 * 1024 * 1024:
            raise ValueError("job too large")
        document = json.loads(raw)
        if document.get("operation") == "render_view":
            from cairn.presentation.models import RenderJob
            from cairn.presentation.render import run_renderer
            from cairn.presentation.service import renderer_identity
            from cairn.records.models import digest

            render_job = RenderJob.model_validate(document)
            html = run_renderer(render_job.document)
            sys.stdout.buffer.write(
                canonical(
                    {
                        "html": base64.b64encode(html).decode(),
                        "document_hash": digest(canonical(render_job.document)),
                        "renderer": renderer_identity(),
                    }
                )
            )
            return
        if document.get("operation") == "inspect_pdf":
            from cairn.library.pdf import inspect_metadata

            if set(document) != {"operation", "data"}:
                raise ValueError("unexpected metadata fields")
            sys.stdout.buffer.write(
                canonical(inspect_metadata(base64.b64decode(document["data"], validate=True)))
            )
            return
        if document.get("operation") == "probe":
            from cairn.adapters.probe import probe

            sys.stdout.buffer.write(canonical(probe(ProbeRequest.model_validate(document))))
            return
        if document.get("operation") == "extract":
            if set(document) != {"operation", "source", "data"}:
                raise ValueError("unexpected extraction fields")
            result = extract_bytes(
                Record.model_validate(document["source"]),
                base64.b64decode(document["data"], validate=True),
            )
            sys.stdout.buffer.write(canonical(result))
            return
        # Drafting is the owner's agent's job (draft packets); the worker never generates.
        raise ValueError("unsupported worker operation")
    except Exception:
        # Never send untrusted/private exception text into generic diagnostics.
        sys.stderr.write("worker rejected job\n")
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
