"""Extract text from uploaded document files."""

from __future__ import annotations

import html
import re
import zipfile
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import quote

# defusedxml refuses DTD entity expansion + external references by default;
# vanilla xml.etree expands internal entities (billion-laughs vector) and
# behavior under quadratic-blowup CVE-2023-52425 depends on bundled libexpat.
from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException

# Magic-bytes pre-gate for PDF/DOCX uploads — sniffs the first ~261 bytes
# to verify the file content matches the claimed extension. Pure-Python,
# zero new system deps. Extension-only validation lets an attacker rename
# arbitrary bytes as `.pdf`, which then invokes PyMuPDF (C parser, CVE
# history) on attacker-controlled input. Defense-in-depth: PyMuPDF and
# zipfile would error too, but the magic-bytes guard fails fast and avoids
# invoking the vulnerable parsers on bad input.
import filetype

from website.features.summarization_engine.core.models import IngestResult, SourceType
from website.features.summarization_engine.source_ingest.base import BaseIngestor
from website.features.summarization_engine.source_ingest.utils import compact_text, join_sections


SUPPORTED_EXTENSIONS = frozenset({".pdf", ".txt", ".md", ".markdown", ".docx"})
MAX_EXTRACTED_CHARS = 180_000

# Zip-bomb guard: cap the decompressed size of word/document.xml extracted
# from a user-uploaded DOCX. Realistic DOCX text payloads are <5 MB; 50 MB
# is ~10x headroom while keeping the 2 GB droplet safe from OOM on a single
# upload. Python zipfile has no built-in cap (cpython #109858), so the
# caller is responsible. Two-layer defense: (1) refuse upfront when central-
# directory declared size already exceeds the cap; (2) stream chunked reads
# so a forged header that lies about size still fails fast.
MAX_DOCX_DECOMPRESSED_BYTES = 50 * 1024 * 1024
_DOCX_READ_CHUNK = 64 * 1024


class DocumentUploadError(ValueError):
    """Raised when an uploaded document cannot be accepted or extracted."""

    recoverable = False


class EncryptedDocumentError(DocumentUploadError):
    """PDF requires a password we don't have."""

    recoverable = False


class CorruptDocumentError(DocumentUploadError):
    """File is structurally broken beyond what the parser can repair."""

    recoverable = False


class NoTextLayerError(DocumentUploadError):
    """Valid document with no extractable text layer (scanned / outlined)."""

    recoverable = True

    def __init__(self, *args, page_count: int = 0):
        super().__init__(*args or ("This document has no selectable text.",))
        self.page_count = page_count


class GarbageTextError(DocumentUploadError):
    """Text extracted but is mostly replacement chars (CID font w/o ToUnicode)."""

    recoverable = True

    def __init__(self, *args, page_count: int = 0):
        super().__init__(*args or ("Extracted text was unreadable (no Unicode mapping).",))
        self.page_count = page_count


def _clean_filename(filename: str) -> str:
    name = Path(filename or "uploaded-document").name.strip()
    return name or "uploaded-document"


def _title_from_filename(filename: str) -> str:
    stem = Path(filename).stem.replace("_", " ").replace("-", " ").strip()
    return re.sub(r"\s+", " ", stem).title() or "Uploaded Document"


def _decode_text(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _extract_pdf(data: bytes) -> tuple[str, dict[str, Any]]:
    try:
        import fitz
    except Exception as exc:  # pragma: no cover - dependency is runtime-required.
        raise DocumentUploadError("PDF extraction is unavailable in this environment.") from exc

    try:
        with fitz.open(stream=data, filetype="pdf") as doc:
            if doc.needs_pass:
                # Owner-only-protected PDFs (restrictions but no read password)
                # open with an empty user password; authenticate() returns truthy.
                if not doc.authenticate(""):
                    raise EncryptedDocumentError(
                        "PDF is password-protected; cannot read without the password."
                    )
            pages, vector_count, image_count = [], 0, 0
            for page in doc:
                pages.append(page.get_text("text"))
                # Character-sized vector drawings = "Text-Looking Vectors"
                # (print-to-PDF outlines). Cheap structural signal.
                vector_count += len(page.get_drawings())
                image_count += len(page.get_images())
            metadata = {
                "page_count": doc.page_count,
                "pdf_title": compact_text(str((doc.metadata or {}).get("title") or "")),
                "pdf_author": compact_text(str((doc.metadata or {}).get("author") or "")),
                "vector_count": vector_count,
                "image_count": image_count,
            }
    except (EncryptedDocumentError, CorruptDocumentError):
        raise
    except Exception as exc:
        raise CorruptDocumentError("Could not extract text from this PDF.") from exc
    return "\n\n".join(pages), {k: v for k, v in metadata.items() if v not in ("", None)}


def _extract_docx(data: bytes) -> tuple[str, dict[str, Any]]:
    try:
        archive = zipfile.ZipFile(BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise DocumentUploadError("DOCX file is not a valid Office document.") from exc

    # Pre-check: refuse upfront if the central directory declares
    # word/document.xml past the cap. Targets only the file we'll actually
    # open — a legitimate DOCX with embedded media in OTHER entries (images,
    # fonts) doesn't trigger a false reject. Streaming read below still
    # catches forged-header bombs that lie about declared size.
    try:
        document_info = archive.getinfo("word/document.xml")
    except KeyError as exc:
        raise DocumentUploadError("DOCX file is missing document text.") from exc
    if document_info.file_size > MAX_DOCX_DECOMPRESSED_BYTES:
        raise DocumentUploadError(
            "DOCX file decompresses too large; refuse to extract."
        )

    with archive.open("word/document.xml") as fh:
        chunks: list[bytes] = []
        total = 0
        while chunk := fh.read(_DOCX_READ_CHUNK):
            total += len(chunk)
            if total > MAX_DOCX_DECOMPRESSED_BYTES:
                raise DocumentUploadError(
                    "DOCX document.xml decompresses too large; refuse to extract."
                )
            chunks.append(chunk)
        document_xml = b"".join(chunks)

    try:
        root = ElementTree.fromstring(document_xml)
    except DefusedXmlException as exc:
        raise DocumentUploadError(
            "DOCX file contains forbidden XML constructs (entities or external references)."
        ) from exc
    except ElementTree.ParseError as exc:
        raise DocumentUploadError("DOCX file is not valid XML.") from exc
    namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    paragraphs: list[str] = []
    for paragraph in root.findall(".//w:p", namespace):
        chunks = [
            node.text or ""
            for node in paragraph.findall(".//w:t", namespace)
            if node.text
        ]
        if chunks:
            paragraphs.append("".join(chunks))
    return "\n\n".join(paragraphs), {"docx_paragraph_count": len(paragraphs)}


def _extract_htmlish_text(text: str) -> str:
    if "<" not in text or ">" not in text:
        return text
    stripped = re.sub(r"<(script|style)[\s\S]*?</\1>", " ", text, flags=re.IGNORECASE)
    stripped = re.sub(r"<[^>]+>", " ", stripped)
    return html.unescape(stripped)


def extract_document_upload(
    *,
    filename: str,
    content: bytes,
    content_type: str | None = None,
) -> IngestResult:
    """Build an IngestResult from an already accepted upload body."""

    safe_name = _clean_filename(filename)
    extension = Path(safe_name).suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise DocumentUploadError(
            "Unsupported document type. Upload PDF, TXT, Markdown, or DOCX."
        )
    if not content:
        raise DocumentUploadError("Uploaded document is empty.")

    # Magic-bytes pre-gate for binary formats. filetype only reads the
    # first 261 bytes (per its docs), so this is microsecond-cheap.
    # Plain-text formats (.txt/.md/.markdown) are not sniffed — filetype
    # cannot reliably detect text, and the downstream _decode_text fallback
    # already handles non-decodable bytes safely.
    if extension == ".pdf":
        kind = filetype.guess(content)
        if kind is None or kind.mime != "application/pdf":
            raise DocumentUploadError("File is not a valid PDF (magic bytes mismatch).")
    elif extension == ".docx":
        kind = filetype.guess(content)
        # DOCX is an Office Open XML container — a ZIP archive on the wire.
        # filetype returns the specific DOCX mime when it can peek the inner
        # word/document.xml; otherwise it falls back to generic application/zip.
        # Accept both. Downstream archive.read("word/document.xml") raises if
        # the zip isn't actually a DOCX.
        _DOCX_MIME = (
            "application/zip",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        if kind is None or kind.mime not in _DOCX_MIME:
            raise DocumentUploadError("File is not a valid DOCX (magic bytes mismatch).")

    metadata: dict[str, Any] = {
        "filename": safe_name,
        "content_type": content_type or "application/octet-stream",
        "extension": extension.lstrip("."),
        "byte_size": len(content),
    }
    if extension == ".pdf":
        text, extracted_meta = _extract_pdf(content)
        metadata.update(extracted_meta)
    elif extension == ".docx":
        text, extracted_meta = _extract_docx(content)
        metadata.update(extracted_meta)
    else:
        text = _extract_htmlish_text(_decode_text(content))

    cleaned = compact_text(text, max_chars=MAX_EXTRACTED_CHARS)
    if len(cleaned) < 50:
        if extension == ".pdf":
            # Scanned/outlined PDF (visual content but no text) → recoverable
            # via vision; genuinely empty PDF stays terminal.
            has_visual = (
                metadata.get("vector_count", 0) >= 50
                or metadata.get("image_count", 0) >= 1
            )
            if has_visual:
                raise NoTextLayerError(
                    "This PDF has no selectable text.",
                    page_count=int(metadata.get("page_count", 0)),
                )
        raise DocumentUploadError("Could not extract enough text from this document.")

    title = metadata.get("pdf_title") or _title_from_filename(safe_name)
    sections = {
        "## Document": f"Title: {title}\nFilename: {safe_name}",
        "## Extracted Text": cleaned,
    }
    return IngestResult(
        source_type=SourceType.DOCUMENT,
        url=f"file-upload://{quote(safe_name)}",
        original_url=f"file-upload://{quote(safe_name)}",
        raw_text=join_sections(sections),
        sections=sections,
        metadata=metadata,
        extraction_confidence="high",
        confidence_reason="document_upload_text_extracted",
        fetched_at=datetime.now(timezone.utc),
        ingestor_version="1.0.0",
    )


class DocumentIngestor(BaseIngestor):
    """Registry-compatible ingestor for document source type."""

    source_type = SourceType.DOCUMENT
    version = "1.0.0"

    async def ingest(self, url: str, *, config: dict[str, Any]) -> IngestResult:
        raise DocumentUploadError("Document uploads must be ingested from multipart bytes.")
