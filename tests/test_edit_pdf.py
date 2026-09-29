from pathlib import Path

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from cairn.errors import Conflict, Denied
from cairn.ingest.service import capture, extract
from cairn.records.models import Record, digest
from cairn.storage.markdown import encode
from cairn.storage.workspace import Workspace
from cairn.transactions.edit import edit_from_file


def test_owner_edit_is_staged_and_checks_base(
    ws: Workspace, tmp_path: Path, record: Record
) -> None:
    path = "vault/wiki/research/concept_demo.md"
    original = encode(record, "Original owner text.\n")
    ws.fs.write(path, original)
    file = tmp_path / "owner-edit.md"
    file.write_bytes(encode(record, "Owner revised text.\n"))
    proposal = edit_from_file(
        ws, record.id, file, expected_hash=digest(original), inline_synthetic=True
    )
    assert proposal and len(proposal.changes) == 1
    assert ws.fs.read(path) == original
    ws.fs.write(path, encode(record, "New intervening edit.\n"))
    with pytest.raises(Conflict):
        edit_from_file(ws, record.id, file, expected_hash=digest(original), inline_synthetic=True)


def test_pdf_extraction_preserves_page_and_partial_coverage(ws: Workspace, tmp_path: Path) -> None:
    writer = PdfWriter()
    page = writer.add_blank_page(width=200, height=200)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
    )
    content = DecodedStreamObject()
    content.set_data(b"BT /F1 12 Tf 10 100 Td (Synthetic total 12.) Tj ET")
    page[NameObject("/Contents")] = content
    file = tmp_path / "source.pdf"
    writer.write(file)
    source = capture(ws, file, domain="research")
    extraction, _ = extract(ws, source.id, inline_synthetic=True)
    assert extraction.coverage == "excerpt"
    assert extraction.segments[0].locator == "page 1, line 1"
    assert "Synthetic total 12." in extraction.segments[0].text
    assert not extraction.tables_inspected and not extraction.images_inspected
    edited_source = tmp_path / "source-edit.md"
    edited_source.write_bytes(ws.fs.read(f"vault/sources/{source.id}.md"))
    with pytest.raises(Denied):
        edit_from_file(ws, source.id, edited_source, expected_hash="0" * 64, inline_synthetic=True)
