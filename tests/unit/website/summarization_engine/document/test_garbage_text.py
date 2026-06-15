import pytest
from website.features.summarization_engine.source_ingest.document import ingest as di
from website.features.summarization_engine.source_ingest.document import GarbageTextError


def test_ufffd_density():
    assert di._ufffd_density("abc") == 0.0
    assert di._ufffd_density("���abcdefg") == pytest.approx(0.3, abs=0.01)
    assert di._ufffd_density("") == 0.0


def test_garbage_text_routed(monkeypatch):
    garbage = ("�" * 80) + ("x" * 20)
    monkeypatch.setattr(di, "_extract_pdf", lambda data: (garbage, {"page_count": 1, "image_count": 0, "vector_count": 0}))
    # Ensure the magic-bytes pre-gate passes for our fake bytes:
    monkeypatch.setattr(di.filetype, "guess", lambda c: type("K", (), {"mime": "application/pdf"})())
    with pytest.raises(GarbageTextError):
        di.extract_document_upload(filename="cid.pdf", content=b"%PDF-1.7 fake bytes here")
