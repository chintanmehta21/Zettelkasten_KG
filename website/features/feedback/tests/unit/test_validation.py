"""Tests for image-file validation (extension whitelist + magic-byte sniff)."""
from __future__ import annotations

import pytest

from website.features.feedback.intake.validation import (
    ValidationError as FeedbackValidationError,
    sniff_and_validate_image,
)


def test_accepts_valid_jpeg(jpeg_bytes_no_exif: bytes) -> None:
    result = sniff_and_validate_image(jpeg_bytes_no_exif, filename="shot.jpg")
    assert result.detected_mime == "image/jpeg"
    assert result.normalized_extension == "jpg"


def test_accepts_valid_png() -> None:
    from io import BytesIO
    from PIL import Image
    buf = BytesIO()
    Image.new("RGB", (4, 4), (0, 0, 255)).save(buf, format="PNG")
    result = sniff_and_validate_image(buf.getvalue(), filename="x.png")
    assert result.detected_mime == "image/png"
    assert result.normalized_extension == "png"


def test_rejects_unknown_extension(jpeg_bytes_no_exif: bytes) -> None:
    with pytest.raises(FeedbackValidationError, match="extension"):
        sniff_and_validate_image(jpeg_bytes_no_exif, filename="x.heic")


def test_rejects_extension_mime_mismatch(jpeg_bytes_no_exif: bytes) -> None:
    # JPEG bytes but caller claims ".png" — magic-byte sniff catches it.
    with pytest.raises(FeedbackValidationError, match="mime"):
        sniff_and_validate_image(jpeg_bytes_no_exif, filename="x.png")


def test_rejects_svg_even_if_text_mime_sniff_says_image() -> None:
    svg = b'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg"></svg>'
    with pytest.raises(FeedbackValidationError):
        sniff_and_validate_image(svg, filename="x.svg")


def test_rejects_empty_bytes() -> None:
    with pytest.raises(FeedbackValidationError):
        sniff_and_validate_image(b"", filename="x.jpg")
