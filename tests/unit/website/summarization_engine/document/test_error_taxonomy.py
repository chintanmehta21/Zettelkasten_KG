import pytest
from website.features.summarization_engine.source_ingest.document import ingest as doc_ingest
from website.features.summarization_engine.source_ingest.document import DocumentUploadError


def test_subclasses_exist_and_inherit():
    for name in ("EncryptedDocumentError", "CorruptDocumentError", "NoTextLayerError", "GarbageTextError"):
        cls = getattr(doc_ingest, name)
        assert issubclass(cls, DocumentUploadError)


def test_recoverable_flag():
    assert doc_ingest.NoTextLayerError(page_count=3).recoverable is True
    assert doc_ingest.GarbageTextError().recoverable is True
    assert doc_ingest.EncryptedDocumentError().recoverable is False
    assert doc_ingest.CorruptDocumentError().recoverable is False


def test_no_text_layer_carries_page_count():
    err = doc_ingest.NoTextLayerError(page_count=11)
    assert err.page_count == 11
