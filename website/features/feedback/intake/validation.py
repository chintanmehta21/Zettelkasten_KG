"""Pre-pipeline validation: extension whitelist + libmagic MIME sniff.

This runs BEFORE the Pillow rewrite. Goal: cheap, fail-fast rejection of
files that aren't bitmap-image bytes at all, before we hand them to a more
expensive parser. Per OWASP File Upload Cheat Sheet, this is the canonical
extension+magic-bytes pair.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath

import magic


class ValidationError(Exception):
    """Raised when an uploaded image fails validation. Maps to HTTP 400/413."""


# Whitelist — explicit, exhaustive. SVG/ICO/HEIC/GIF intentionally excluded.
_ALLOWED_EXT_TO_MIME = {
    "jpg":  "image/jpeg",
    "jpeg": "image/jpeg",
    "png":  "image/png",
    "webp": "image/webp",
}


@dataclass(frozen=True)
class ValidatedImage:
    detected_mime: str
    normalized_extension: str  # "jpg" or "png" or "webp"


def _normalize_extension(filename: str) -> str:
    ext = PurePosixPath(filename or "").suffix.lstrip(".").lower()
    return ext


def sniff_and_validate_image(blob: bytes, *, filename: str) -> ValidatedImage:
    """Return a ValidatedImage on success; raise ValidationError on failure."""
    if not blob:
        raise ValidationError("empty file")

    ext = _normalize_extension(filename)
    if ext not in _ALLOWED_EXT_TO_MIME:
        raise ValidationError(
            f"extension '.{ext}' not allowed; use jpg, jpeg, png, or webp"
        )

    detected = magic.from_buffer(blob, mime=True)
    expected = _ALLOWED_EXT_TO_MIME[ext]
    if detected != expected:
        raise ValidationError(
            f"file content mime '{detected}' does not match extension '{ext}'"
        )

    # Normalize jpeg/jpg → jpg for consistency in storage filenames.
    normalized_ext = "jpg" if ext in {"jpg", "jpeg"} else ext
    return ValidatedImage(detected_mime=detected, normalized_extension=normalized_ext)
