"""Feature-local fixtures for the feedback module's tests."""
from __future__ import annotations

import os
import pytest


@pytest.fixture
def fake_slack_creds(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """Stub all Slack env vars so route tests don't 503."""
    creds = {
        "SLACK_BOT_TOKEN_FEEDBACK": "xoxb-test-fake-token-1234",
        "SLACK_CHANNEL_FEEDBACK": "C09TESTCHAN",
        "SECRET_FEEDBACK_COOKIE": "0123456789abcdef" * 4,  # 64-byte hex
        "FEEDBACK_REQUIRE_TURNSTILE": "false",
    }
    for k, v in creds.items():
        monkeypatch.setenv(k, v)
    # Reset the lru_cache so the next get_feedback_settings() call sees the fakes.
    # NOTE: this fixture only takes effect AFTER Task 3 lands core/settings.py.
    # Until then the import inside the function will fail with ImportError —
    # tests that depend on this fixture won't run until then, which is fine.
    try:
        from website.features.feedback.core.settings import get_feedback_settings
        get_feedback_settings.cache_clear()
    except ImportError:
        pass  # core/settings.py not yet implemented (pre-Task-3)
    return creds


@pytest.fixture
def jpeg_bytes_no_exif() -> bytes:
    """Minimal 8x8 black JPEG with no EXIF, for image-pipeline tests."""
    from io import BytesIO
    from PIL import Image
    buf = BytesIO()
    Image.new("RGB", (8, 8), (0, 0, 0)).save(buf, format="JPEG", quality=85)
    return buf.getvalue()


@pytest.fixture
def jpeg_bytes_with_gps_exif() -> bytes:
    """8x8 JPEG carrying a fake GPS EXIF tag, for the EXIF-strip test."""
    from io import BytesIO
    import piexif
    from PIL import Image
    buf = BytesIO()
    img = Image.new("RGB", (8, 8), (255, 0, 0))
    # GPS tag block — latitude 37.7749, longitude -122.4194 (San Francisco)
    gps_ifd = {
        piexif.GPSIFD.GPSLatitudeRef: b"N",
        piexif.GPSIFD.GPSLatitude: [(37, 1), (46, 1), (4, 1)],
        piexif.GPSIFD.GPSLongitudeRef: b"W",
        piexif.GPSIFD.GPSLongitude: [(122, 1), (25, 1), (10, 1)],
    }
    exif_dict = {"GPS": gps_ifd}
    exif_bytes = piexif.dump(exif_dict)
    img.save(buf, format="JPEG", exif=exif_bytes, quality=85)
    return buf.getvalue()
