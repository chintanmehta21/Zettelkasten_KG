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
            pages = [page.get_text("text") for page in doc]
            metadata = {
                "page_count": doc.page_count,
                "pdf_title": compact_text(str((doc.metadata or {}).get("title") or "")),
                "pdf_author": compact_text(str((doc.metadata or {}).get("author") or "")),
            }
    except Exception as exc:
        raise DocumentUploadError("Could not extract text from this PDF.") from exc
    return "\n\n".join(pages), {k: v for k, v in metadata.items() if v not in ("", None)}


def _extract_docx(data: bytes) -> tuple[str, dict[str, Any]]:
    try:
        archive = zipfile.ZipFile(BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise DocumentUploadError("DOCX file is not a valid Office document.") from exc

    # Pre-check: refuse upfront if the central-directory declares a total
    # decompressed size beyond cap. Fast-reject for stated-size bombs; the
    # streaming read below catches forged-header bombs.
    total_declared = sum(zi.file_size for zi in archive.infolist())
    if total_declared > MAX_DOCX_DECOMPRESSED_BYTES:
        raise DocumentUploadError(
            "DOCX file decompresses too large; refuse to extract."
        )

    try:
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
    except KeyError as exc:
        raise DocumentUploadError("DOCX file is missing document text.") from exc

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
