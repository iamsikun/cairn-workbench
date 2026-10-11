"""Native adapters honor configured executables and preserve failed PDF inputs."""

import base64
from pathlib import Path

import pytest
from test_library_catalog import pdf

from cairn.errors import Blocked
from cairn.presentation import native
from cairn.presentation.document import ViewDocument
from cairn.saving.models import Capture, SourceInput
from cairn.saving.service import save
from cairn.saving.workspace import Book


def document():
    return ViewDocument(
        title="Synthetic", bundle_id="view_native", bundle_hash="a" * 64,
        subtitle="Synthetic", sections=[], evidence=[], targets=[],
    )


def test_missing_node_is_actionable(monkeypatch):
    monkeypatch.setenv("PATH", "")
    with pytest.raises(Blocked, match="Node 20 or later.*PATH"):
        native.run_renderer(document())


def test_renderer_uses_path_without_forwarding_credentials(tmp_path: Path, monkeypatch):
    binary = tmp_path / "node"
    binary.write_text("#!/bin/sh\nexit 99\n")
    binary.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setenv("SYNTHETIC_SECRET", "must-not-forward")
    doc = document()
    html = (
        '<!doctype html><meta http-equiv="Content-Security-Policy" '
        'content="default-src \'none\'; connect-src \'none\'">' + doc.bundle_hash
    ).encode()

    def process(command, raw, **kwargs):
        assert command[0] == str(binary)
        assert kwargs["env"] == {"PATH": str(tmp_path), "LANG": "C.UTF-8"}
        return 0, html

    monkeypatch.setattr(native, "bounded_process", process)
    assert native.run_renderer(doc) == html


def test_failed_native_parser_keeps_source_bytes(tmp_path, monkeypatch):
    def unavailable(*args, **kwargs):
        raise Blocked("process_unavailable")

    monkeypatch.setattr("cairn.saving.sources.bounded_process", unavailable)
    book = Book.init(tmp_path / "book", synthetic=True)
    raw = pdf("Synthetic retained source")
    receipt = save(book, "research", Capture(
        operation_key="unavailable-parser", source=SourceInput(identity="native", title="Native"),
        pdf_base64=base64.b64encode(raw).decode(),
    ))
    source = book.record(receipt["notes"][0]["id"], "research")[1].source
    assert source.extraction_status == "failed"
    assert book.fs.read(source.original_blob) == raw
