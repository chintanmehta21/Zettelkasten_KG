import fitz, pytest
from website.features.summarization_engine.source_ingest.document import (
    extract_document_upload, EncryptedDocumentError,
)


def _encrypted_pdf() -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Secret content that needs a password to read.")
    return doc.tobytes(encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw="owner", user_pw="userpw")


def test_encrypted_pdf_raises_encrypted_error():
    with pytest.raises(EncryptedDocumentError):
        extract_document_upload(filename="locked.pdf", content=_encrypted_pdf())
