"""Document upload extraction tests."""

from __future__ import annotations

import zipfile
from io import BytesIO

import pytest

from website.features.summarization_engine.core.models import SourceType
from website.features.summarization_engine.source_ingest.document import (
    DocumentUploadError,
    extract_document_upload,
)


def _docx_bytes(text: str) -> bytes:
    body = "".join(
        f"<w:p><w:r><w:t>{part}</w:t></w:r></w:p>"
        for part in text.split("\n")
    )
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{body}</w:body></w:document>"
    )
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", xml)
    return buffer.getvalue()


def test_extract_text_document_upload_builds_document_ingest_result():
    result = extract_document_upload(
        filename="zettel-notes.md",
        content=(
            b"# Durable notes\n\n"
            b"Uploaded documents should become canonical zettels with enough body text "
            b"for summarization and retrieval in the v2 content schema."
        ),
        content_type="text/markdown",
    )

    assert result.source_type == SourceType.DOCUMENT
    assert result.url == "file-upload://zettel-notes.md"
    assert result.metadata["filename"] == "zettel-notes.md"
    assert result.metadata["extension"] == "md"
    assert "Durable notes" in result.raw_text
    assert result.extraction_confidence == "high"


def test_extract_docx_document_upload_reads_paragraph_text():
    result = extract_document_upload(
        filename="research-brief.docx",
        content=_docx_bytes(
            "A research brief about semantic retrieval.\n"
            "It contains enough extracted document text to summarize reliably."
        ),
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )

    assert result.source_type == SourceType.DOCUMENT
    assert "semantic retrieval" in result.raw_text
    assert result.metadata["docx_paragraph_count"] == 2


def test_extract_document_upload_rejects_unsupported_extension():
    with pytest.raises(DocumentUploadError, match="Unsupported document type"):
        extract_document_upload(
            filename="legacy.doc",
            content=b"Enough body text would be here, but this format is unsupported.",
            content_type="application/msword",
        )


def test_extract_docx_rejects_internal_entity_expansion():
    """Billion-laughs guard: a DOCX with an internal DTD entity must be
    rejected, not silently expanded. defusedxml.ElementTree refuses entity
    expansion by default (forbid_entities=True), closing the canonical
    billion-laughs / quadratic-blowup vector on user uploads.

    Without defusedxml, vanilla xml.etree.ElementTree expands &greeting; to
    "hello" and the document parses successfully — the vulnerability path.
    """
    filler = "Padding text to clear the 50-char minimum threshold check downstream of the parse step."
    body = (
        b'<?xml version="1.0"?>'
        b'<!DOCTYPE doc [<!ENTITY greeting "hello">]>'
        b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        b'<w:body>'
        b'<w:p><w:r><w:t>&greeting;</w:t></w:r></w:p>'
        + f'<w:p><w:r><w:t>{filler}</w:t></w:r></w:p>'.encode()
        + b'</w:body></w:document>'
    )
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", body)

    with pytest.raises(DocumentUploadError):
        extract_document_upload(
            filename="entity.docx",
            content=buffer.getvalue(),
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )


def test_extract_docx_rejects_external_entity():
    """XXE guard: a DOCX referencing an external SYSTEM entity must be
    rejected (defusedxml's forbid_external=True), not silently expanded into
    a file:// or http:// fetch.
    """
    filler = "Padding text to clear the 50-char minimum threshold check downstream of the parse step."
    body = (
        b'<?xml version="1.0"?>'
        b'<!DOCTYPE doc [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>'
        b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        b'<w:body>'
        b'<w:p><w:r><w:t>&xxe;</w:t></w:r></w:p>'
        + f'<w:p><w:r><w:t>{filler}</w:t></w:r></w:p>'.encode()
        + b'</w:body></w:document>'
    )
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", body)

    with pytest.raises(DocumentUploadError):
        extract_document_upload(
            filename="xxe.docx",
            content=buffer.getvalue(),
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
