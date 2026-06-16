"""DocumentTooComplexError: a parse that hits the resource cap is *too complex*,
not *corrupt* — distinct exception, distinct RFC-9457 type + message."""

import fitz
import pytest

from website.api.zettels_routes import _async_failure_error_payload
from website.features.summarization_engine.source_ingest.document import (
    DocumentTooComplexError,
    DocumentUploadError,
    extract_document_upload,
)


def test_too_complex_is_terminal_subclass():
    assert issubclass(DocumentTooComplexError, DocumentUploadError)
    assert DocumentTooComplexError().recoverable is False


def test_too_complex_problem_detail_distinct_from_corrupt():
    body = _async_failure_error_payload(DocumentTooComplexError(), operation_id="op1")
    assert body["type"].endswith("document-too-complex")
    assert "complex" in body["detail"].lower()
    # Must NOT read as the misleading "corrupt/damaged" wording.
    assert "damaged" not in body["detail"].lower()


def test_memory_error_during_parse_maps_to_too_complex(monkeypatch):
    # Build valid PDF bytes with the REAL fitz, THEN force the parse to OOM so
    # the RLIMIT_AS-jail path (MemoryError) is exercised end-to-end.
    d = fitz.open()
    d.new_page().insert_text((72, 72), "enough real text here to clear the fifty char gate easily.")
    pdf = d.tobytes()

    def _boom(*a, **k):
        raise MemoryError("simulated rlimit OOM")

    monkeypatch.setattr(fitz, "open", _boom)
    with pytest.raises(DocumentTooComplexError):
        extract_document_upload(filename="big.pdf", content=pdf)
