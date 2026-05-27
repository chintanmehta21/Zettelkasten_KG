"""Rewrite uploaded images via Pillow:

  * Re-parses the bytes through PIL.Image.open + verify() — destroys malformed
    payloads and ensures we can serialize the result deterministically.
  * Strips EXIF metadata (GPS, device model, camera serial), as the OWASP
    File Upload Cheat Sheet recommends for any user-uploaded image.
  * Re-encodes to a canonical form: JPEG q=85 if source was JPEG, PNG
    otherwise. Output bytes never include EXIF.
  * Generates a server-side filename — never trusts the client name.

Returns the rewritten bytes + a uuid4-based filename ready for files_upload_v2.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from io import BytesIO

from PIL import Image, UnidentifiedImageError


class ImageProcessingError(Exception):
    """Raised when an image fails to parse / verify. Maps to HTTP 400."""


@dataclass(frozen=True)
class ProcessedImage:
    body: bytes
    filename: str  # e.g. "deadbeef...0123.jpg"
    content_type: str  # "image/jpeg" or "image/png" or "image/webp"


_SAVE_FORMATS = {
    "jpg":  ("JPEG", "image/jpeg", {"quality": 85, "optimize": True}),
    "png":  ("PNG", "image/png", {"optimize": True}),
    "webp": ("WEBP", "image/webp", {"quality": 85, "method": 6}),
}


def process_image(blob: bytes, *, source_ext: str) -> ProcessedImage:
    """Re-encode + EXIF-strip an uploaded image.

    Args:
        blob: raw bytes from UploadFile.
        source_ext: normalized extension (e.g. "jpg") from validation step.

    Raises:
        ImageProcessingError: parse failure, truncation, or unsupported format.
    """
    if source_ext not in _SAVE_FORMATS:
        raise ImageProcessingError(f"unsupported source extension: {source_ext}")

    try:
        # First open + verify — destroys instance per Pillow docs
        Image.open(BytesIO(blob)).verify()
        # Re-open for actual conversion
        img = Image.open(BytesIO(blob))
        img.load()
    except (UnidentifiedImageError, OSError, SyntaxError) as exc:
        raise ImageProcessingError(f"invalid image bytes: {exc}") from exc

    # Convert any mode to RGB (drops alpha for JPEG; safe for PNG/WEBP too).
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGB")
    elif img.mode == "RGBA" and source_ext == "jpg":
        # JPEG can't carry alpha — flatten on white.
        background = Image.new("RGB", img.size, (255, 255, 255))
        background.paste(img, mask=img.split()[3])
        img = background

    fmt, mime, kwargs = _SAVE_FORMATS[source_ext]
    out_buf = BytesIO()
    # Pass exif=b"" explicitly so PIL doesn't carry forward any preserved EXIF.
    img.save(out_buf, format=fmt, exif=b"", **kwargs)

    body = out_buf.getvalue()
    filename = f"{uuid.uuid4().hex}.{source_ext}"
    return ProcessedImage(body=body, filename=filename, content_type=mime)
