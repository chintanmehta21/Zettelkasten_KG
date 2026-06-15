import io, fitz, pytest
from PIL import Image
from website.features.summarization_engine.source_ingest.document import (
    extract_document_upload, NoTextLayerError, DocumentUploadError,
)


def _image_only_pdf(pages=2) -> bytes:
    doc = fitz.open()
    img = Image.new("RGB", (400, 250), (230, 230, 230))
    buf = io.BytesIO(); img.save(buf, format="PNG")
    for _ in range(pages):
        p = doc.new_page(width=612, height=792)
        p.insert_image(fitz.Rect(56, 56, 456, 306), stream=buf.getvalue())
    return doc.tobytes()


def _text_pdf() -> bytes:
    doc = fitz.open(); p = doc.new_page()
    p.insert_text((72, 100), "Real selectable text well past fifty characters easily here.")
    return doc.tobytes()


def _blank_pdf() -> bytes:
    doc = fitz.open(); doc.new_page(); return doc.tobytes()


def test_image_only_pdf_is_recoverable_no_text_layer():
    with pytest.raises(NoTextLayerError):
        extract_document_upload(filename="scan.pdf", content=_image_only_pdf())


def test_real_text_pdf_accepted():
    res = extract_document_upload(filename="ok.pdf", content=_text_pdf())
    assert "selectable text" in res.raw_text


def test_truly_blank_pdf_is_terminal_not_recoverable():
    with pytest.raises(DocumentUploadError) as ei:
        extract_document_upload(filename="blank.pdf", content=_blank_pdf())
    assert not getattr(ei.value, "recoverable", False)
