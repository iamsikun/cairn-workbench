import base64
import io

from PIL import Image
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from cairn.library.reader_models import PaperClaim, PaperSummary, ReaderJob
from cairn.library.reader_worker import page_image, read
from cairn.reading.skill import guidance_hash
from cairn.records.models import digest


def evidence_pdf(pages: int) -> bytes:
    writer = PdfWriter()
    for index in range(pages):
        page = writer.add_blank_page(width=300, height=300)
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
        content.set_data(
            f"BT /F1 12 Tf 20 250 Td (Page {index + 1}: result = 4 examples.) Tj ET".encode()
        )
        page[NameObject("/Contents")] = writer._add_object(content)
    stream = io.BytesIO()
    writer.write(stream)
    return stream.getvalue()


def test_real_page_render_and_long_paper_batches() -> None:
    raw = evidence_pdf(11)
    image = Image.open(io.BytesIO(base64.b64decode(page_image(raw, 1))))
    assert image.size == (480, 480)
    job = ReaderJob(
        id="read_demo",
        paper_id="entity_demo",
        source_id="source_demo",
        source_hash=digest(raw),
        policy_hash="1" * 64,
        device_hash="2" * 64,
        device_id="device_demo",
        source_type="pdf",
        title="Synthetic equations and result",
        model_hash="3" * 64,
        projection_hash="4" * 64,
        page_limit=10,
        guidance_hash=guidance_hash(),
    )
    batches = []

    def generated(content):
        batches.append(content)
        # Structural test, not a semantic-quality claim: the first page's quote is
        # checked against deterministic PDF text after hierarchical synthesis.
        return PaperSummary(
            summary="Synthetic result",
            findings=[PaperClaim(text="Four examples", page=1, quote="4 examples")],
        )

    result = read(job, raw, generated)
    assert result.page_count == 11 and result.inspected_pages == list(range(1, 11))
    assert result.visual_pages == result.inspected_pages
    assert result.extraction.coverage == "excerpt"
    assert len(batches) == 4
    assert all(sum(x["type"] == "image_url" for x in batch) <= 4 for batch in batches)
