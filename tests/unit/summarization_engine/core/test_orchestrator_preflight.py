"""H4/T7 — unit tests for _yt_preflight_refuse hard-fail detection."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from website.features.summarization_engine.core.orchestrator import (
    _is_youtube_url,
    _yt_preflight_refuse,
)


class _FakeYDL:
    """Context-manager stand-in for yt_dlp.YoutubeDL."""

    def __init__(self, info=None, exc=None):
        self._info = info
        self._exc = exc

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def extract_info(self, url, download=False):
        if self._exc is not None:
            raise self._exc
        return self._info


def _patch_ydl(info=None, exc=None):
    return patch(
        "yt_dlp.YoutubeDL",
        return_value=_FakeYDL(info=info, exc=exc),
        new_callable=MagicMock,
    )


def test_non_youtube_url_proceeds():
    assert _yt_preflight_refuse("https://example.com/blog/post") is None


def test_is_youtube_url_helper():
    assert _is_youtube_url("https://www.youtube.com/watch?v=abc")
    assert _is_youtube_url("https://youtu.be/abc")
    assert not _is_youtube_url("https://example.com")


def test_is_youtube_url_handles_empty_and_malformed():
    """PR #115 narrowing: bad URL shapes must return False without raising
    so a generic-web fallback path takes over (legitimate router behavior).
    Before narrowing, the bare `except Exception` swallowed everything
    including programmer-error TypeErrors that should have surfaced.
    """
    assert _is_youtube_url("") is False
    assert _is_youtube_url("not://a-url{}") is False


def test_is_youtube_url_handles_none_via_attribute_error():
    """urlparse(None) raises AttributeError ('NoneType' has no .decode);
    the narrowed except set catches it and returns False. Pins the deliberate
    fail-soft for None/missing URL inputs that arrive from cache/replay paths."""
    assert _is_youtube_url(None) is False  # type: ignore[arg-type]


def test_livestream_refuses():
    with _patch_ydl(info={"is_live": True}):
        result = _yt_preflight_refuse("https://www.youtube.com/watch?v=abc")
    assert result == (True, "active_livestream")


def test_premiere_refuses():
    with _patch_ydl(info={"is_live": False, "live_status": "is_upcoming"}):
        result = _yt_preflight_refuse("https://www.youtube.com/watch?v=abc")
    assert result == (True, "premiere_or_post_live")


def test_private_via_availability_refuses():
    with _patch_ydl(info={"availability": "private"}):
        result = _yt_preflight_refuse("https://www.youtube.com/watch?v=abc")
    assert result == (True, "private")


def test_members_only_refuses():
    with _patch_ydl(info={"availability": "needs_auth"}):
        result = _yt_preflight_refuse("https://www.youtube.com/watch?v=abc")
    assert result == (True, "members_only_or_age_restricted")


def test_normal_video_proceeds():
    with _patch_ydl(info={"title": "ok", "availability": "public"}):
        result = _yt_preflight_refuse("https://www.youtube.com/watch?v=abc")
    assert result is None


def test_requested_format_unavailable_does_not_refuse():
    with _patch_ydl(exc=RuntimeError("Requested format is not available")):
        result = _yt_preflight_refuse("https://www.youtube.com/watch?v=abc")
    assert result is None


def test_private_via_exception_refuses():
    with _patch_ydl(exc=RuntimeError("ERROR: Private video. Sign in.")):
        result = _yt_preflight_refuse("https://www.youtube.com/watch?v=abc")
    assert result == (True, "private")


def test_removed_via_exception_refuses():
    with _patch_ydl(exc=RuntimeError("Video unavailable: This video has been removed")):
        result = _yt_preflight_refuse("https://www.youtube.com/watch?v=abc")
    assert result == (True, "removed_or_unavailable")


def test_bot_detection_does_not_refuse():
    # Sign-in-to-confirm-not-a-bot is NOT a hard fail — the tier chain
    # (cookies+impersonate) must handle it.
    with _patch_ydl(exc=RuntimeError("Sign in to confirm you're not a bot")):
        result = _yt_preflight_refuse("https://www.youtube.com/watch?v=abc")
    assert result is None
