"""Tests for the Pillow-rewrite image pipeline."""
from __future__ import annotations

import piexif
import pytest
from io import BytesIO
from PIL import Image

from website.features.feedback.intake.image_pipeline import (
    process_image,
    ImageProcessingError,
)


def test_jpeg_passthrough_strips_no_exif(jpeg_bytes_no_exif: bytes) -> None:
    out = process_image(jpeg_bytes_no_exif, source_ext="jpg")
    img = Image.open(BytesIO(out.body))
    assert img.format == "JPEG"
    assert img.mode == "RGB"
    assert out.filename.endswith(".jpg")


def test_jpeg_with_gps_exif_is_stripped(jpeg_bytes_with_gps_exif: bytes) -> None:
    out = process_image(jpeg_bytes_with_gps_exif, source_ext="jpg")
    img = Image.open(BytesIO(out.body))
    # When exif=b"" is passed to PIL.save, the output has no EXIF segment at all
    # (img.info has no "exif" key). That's the strongest form of stripping.
    # If for any reason an EXIF segment does sneak through, parse it and assert
    # GPS IFD is empty.
    exif_blob = img.info.get("exif")
    if exif_blob:
        exif = piexif.load(exif_blob)
        assert not exif.get("GPS"), "GPS EXIF should be stripped"
    else:
        assert exif_blob in (None, b""), "EXIF segment must be absent or empty"


def test_png_passthrough(jpeg_bytes_no_exif: bytes) -> None:
    # Encode a fresh PNG
    buf = BytesIO()
    Image.new("RGB", (10, 10), (12, 34, 56)).save(buf, format="PNG")
    out = process_image(buf.getvalue(), source_ext="png")
    img = Image.open(BytesIO(out.body))
    assert img.format == "PNG"
    assert out.filename.endswith(".png")


def test_corrupt_bytes_raises() -> None:
    with pytest.raises(ImageProcessingError):
        process_image(b"\x00\x00\x00 not an image", source_ext="jpg")


def test_truncated_jpeg_raises(jpeg_bytes_no_exif: bytes) -> None:
    truncated = jpeg_bytes_no_exif[:30]
    with pytest.raises(ImageProcessingError):
        process_image(truncated, source_ext="jpg")


def test_filename_is_uuid_format(jpeg_bytes_no_exif: bytes) -> None:
    import re
    out = process_image(jpeg_bytes_no_exif, source_ext="jpg")
    # 32 hex chars + .jpg
    assert re.match(r"^[0-9a-f]{32}\.jpg$", out.filename)
