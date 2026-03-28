"""Comprehensive tests for YouTube URL handling across the full pipeline.

Tests _extract_video_id, detect_source_type, and normalize_url for every
known YouTube URL format, including edge cases that should fail gracefully.
"""

from __future__ import annotations

import pytest

from zettelkasten_bot.models.capture import SourceType
from zettelkasten_bot.sources.registry import detect_source_type
from zettelkasten_bot.sources.youtube import _extract_video_id
from zettelkasten_bot.utils.url_utils import normalize_url

VIDEO_ID = "dQw4w9WgXcQ"


# ---------------------------------------------------------------------------
# _extract_video_id — valid URLs that MUST return the correct video ID
# ---------------------------------------------------------------------------

class TestExtractVideoIdStandardWatch:
    """Standard /watch?v= URLs."""

    def test_www_youtube(self):
        assert _extract_video_id(f"https://www.youtube.com/watch?v={VIDEO_ID}") == VIDEO_ID

    def test_no_www(self):
        assert _extract_video_id(f"https://youtube.com/watch?v={VIDEO_ID}") == VIDEO_ID

    def test_mobile(self):
        assert _extract_video_id(f"https://m.youtube.com/watch?v={VIDEO_ID}") == VIDEO_ID

    def test_music(self):
        assert _extract_video_id(f"https://music.youtube.com/watch?v={VIDEO_ID}") == VIDEO_ID


class TestExtractVideoIdWithExtraParams:
    """Watch URLs with extra query parameters (v= may not be first)."""

    def test_with_timestamp(self):
        assert _extract_video_id(f"https://www.youtube.com/watch?v={VIDEO_ID}&t=120") == VIDEO_ID

    def test_with_list(self):
        url = f"https://www.youtube.com/watch?v={VIDEO_ID}&list=PLrAXtmErZgOeiKm4sgNOknGvNjby9efdf"
        assert _extract_video_id(url) == VIDEO_ID

    def test_with_si(self):
        url = f"https://www.youtube.com/watch?v={VIDEO_ID}&si=4QYCwP9gy5_09jVE"
        assert _extract_video_id(url) == VIDEO_ID

    def test_with_feature(self):
        url = f"https://www.youtube.com/watch?v={VIDEO_ID}&feature=shared"
        assert _extract_video_id(url) == VIDEO_ID

    def test_v_not_first_param(self):
        url = f"https://www.youtube.com/watch?list=PLrAXtmErZgOe&v={VIDEO_ID}"
        assert _extract_video_id(url) == VIDEO_ID


class TestExtractVideoIdShortUrls:
    """youtu.be short URLs."""

    def test_plain(self):
        assert _extract_video_id(f"https://youtu.be/{VIDEO_ID}") == VIDEO_ID

    def test_with_si(self):
        assert _extract_video_id(f"https://youtu.be/{VIDEO_ID}?si=4QYCwP9gy5_09jVE") == VIDEO_ID

    def test_with_timestamp(self):
        assert _extract_video_id(f"https://youtu.be/{VIDEO_ID}?t=30") == VIDEO_ID

    def test_with_si_and_timestamp(self):
        assert _extract_video_id(f"https://youtu.be/{VIDEO_ID}?si=xxx&t=120") == VIDEO_ID


class TestExtractVideoIdEmbed:
    """Embed URLs including youtube-nocookie.com."""

    def test_standard_embed(self):
        assert _extract_video_id(f"https://www.youtube.com/embed/{VIDEO_ID}") == VIDEO_ID

    def test_nocookie_embed(self):
        assert _extract_video_id(f"https://www.youtube-nocookie.com/embed/{VIDEO_ID}") == VIDEO_ID

    def test_embed_with_autoplay(self):
        assert _extract_video_id(f"https://youtube.com/embed/{VIDEO_ID}?autoplay=1") == VIDEO_ID


class TestExtractVideoIdOldEmbedFormats:
    """/v/ and /e/ old-style embed formats (newly added support)."""

    def test_v_format(self):
        assert _extract_video_id(f"https://www.youtube.com/v/{VIDEO_ID}") == VIDEO_ID

    def test_e_format(self):
        assert _extract_video_id(f"https://www.youtube.com/e/{VIDEO_ID}") == VIDEO_ID


class TestExtractVideoIdShorts:
    """YouTube Shorts URLs."""

    def test_shorts_www(self):
        assert _extract_video_id(f"https://www.youtube.com/shorts/{VIDEO_ID}") == VIDEO_ID

    def test_shorts_with_feature(self):
        assert _extract_video_id(f"https://youtube.com/shorts/{VIDEO_ID}?feature=share") == VIDEO_ID


class TestExtractVideoIdLive:
    """YouTube Live URLs."""

    def test_live_www(self):
        assert _extract_video_id(f"https://www.youtube.com/live/{VIDEO_ID}") == VIDEO_ID

    def test_live_with_si(self):
        assert _extract_video_id(f"https://youtube.com/live/{VIDEO_ID}?si=xxx") == VIDEO_ID


class TestExtractVideoIdFailCases:
    """URLs that must return None (no valid video ID)."""

    def test_playlist_only(self):
        assert _extract_video_id("https://www.youtube.com/playlist?list=PLrAXtmErZgOe") is None

    def test_channel_page(self):
        assert _extract_video_id("https://www.youtube.com/channel/UCxxxxxx") is None

    def test_homepage(self):
        assert _extract_video_id("https://www.youtube.com/") is None

    def test_feed_page(self):
        assert _extract_video_id("https://www.youtube.com/feed/subscriptions") is None

    def test_search_page(self):
        assert _extract_video_id("https://www.youtube.com/results?search_query=test") is None

    def test_non_youtube_url(self):
        assert _extract_video_id("https://example.com/watch?v=dQw4w9WgXcQ") is None

    def test_empty_string(self):
        assert _extract_video_id("") is None

    def test_invalid_video_id_too_short(self):
        assert _extract_video_id("https://www.youtube.com/watch?v=abc") is None


# ---------------------------------------------------------------------------
# detect_source_type — must return SourceType.YOUTUBE for all YouTube URLs
# ---------------------------------------------------------------------------

_YOUTUBE_URLS = [
    f"https://www.youtube.com/watch?v={VIDEO_ID}",
    f"https://youtube.com/watch?v={VIDEO_ID}",
    f"https://m.youtube.com/watch?v={VIDEO_ID}",
    f"https://music.youtube.com/watch?v={VIDEO_ID}",
    f"https://youtu.be/{VIDEO_ID}",
    f"https://www.youtube.com/embed/{VIDEO_ID}",
    f"https://www.youtube-nocookie.com/embed/{VIDEO_ID}",
    f"https://www.youtube.com/shorts/{VIDEO_ID}",
    f"https://www.youtube.com/live/{VIDEO_ID}",
    f"https://www.youtube.com/v/{VIDEO_ID}",
    f"https://www.youtube.com/e/{VIDEO_ID}",
]


@pytest.mark.parametrize("url", _YOUTUBE_URLS)
def test_detect_source_type_youtube(url: str):
    assert detect_source_type(url, newsletter_domains=[]) == SourceType.YOUTUBE


_NON_YOUTUBE_URLS = [
    ("https://github.com/user/repo", SourceType.GITHUB),
    ("https://www.reddit.com/r/python/comments/abc/title/", SourceType.REDDIT),
    ("https://example.com/article", SourceType.GENERIC),
]


@pytest.mark.parametrize("url,expected", _NON_YOUTUBE_URLS)
def test_detect_source_type_not_youtube(url: str, expected: SourceType):
    assert detect_source_type(url, newsletter_domains=[]) == expected


def test_detect_source_type_music_youtube():
    """music.youtube.com must be detected as YOUTUBE (substring match)."""
    url = f"https://music.youtube.com/watch?v={VIDEO_ID}"
    assert detect_source_type(url, newsletter_domains=[]) == SourceType.YOUTUBE


# ---------------------------------------------------------------------------
# Full chain: normalize_url -> _extract_video_id still works
# ---------------------------------------------------------------------------

_NORMALIZE_CHAIN_URLS = [
    # (input_url, expected_video_id)
    (f"https://www.youtube.com/watch?v={VIDEO_ID}&utm_source=twitter", VIDEO_ID),
    (f"https://www.youtube.com/watch?v={VIDEO_ID}&t=120", VIDEO_ID),
    (f"https://www.youtube.com/watch?v={VIDEO_ID}&list=PLrAXtmErZgOe&feature=shared", VIDEO_ID),
    (f"https://www.youtube.com/watch?list=PLrAXtmErZgOe&v={VIDEO_ID}", VIDEO_ID),
    (f"https://youtu.be/{VIDEO_ID}?si=4QYCwP9gy5_09jVE", VIDEO_ID),
    (f"https://www.youtube.com/embed/{VIDEO_ID}?autoplay=1", VIDEO_ID),
    (f"https://www.youtube.com/shorts/{VIDEO_ID}?feature=share", VIDEO_ID),
    (f"https://www.youtube.com/live/{VIDEO_ID}?si=xxx", VIDEO_ID),
    (f"https://www.youtube.com/v/{VIDEO_ID}", VIDEO_ID),
    (f"https://www.youtube.com/e/{VIDEO_ID}", VIDEO_ID),
]


@pytest.mark.parametrize("url,expected_id", _NORMALIZE_CHAIN_URLS)
def test_normalize_then_extract(url: str, expected_id: str):
    """normalize_url should not break video ID extraction."""
    normalized = normalize_url(url)
    assert _extract_video_id(normalized) == expected_id


class TestNormalizePreservesVideoId:
    """Specific checks that normalization does not destroy v= param."""

    def test_sorts_params_but_preserves_v(self):
        url = f"https://www.youtube.com/watch?z=1&v={VIDEO_ID}&a=2"
        normalized = normalize_url(url)
        assert _extract_video_id(normalized) == VIDEO_ID

    def test_strips_tracking_keeps_v(self):
        url = f"https://www.youtube.com/watch?v={VIDEO_ID}&utm_source=twitter&utm_medium=social"
        normalized = normalize_url(url)
        assert _extract_video_id(normalized) == VIDEO_ID
        # Tracking params should be gone
        assert "utm_source" not in normalized
        assert "utm_medium" not in normalized

    def test_strips_fragment(self):
        url = f"https://www.youtube.com/watch?v={VIDEO_ID}#section"
        normalized = normalize_url(url)
        assert _extract_video_id(normalized) == VIDEO_ID
        assert "#" not in normalized
