# tests/test_routing.py
"""Tests for content-aware starting model selection."""

from website.features.api_key_switching.routing import select_starting_model

# ── Best model for complex/long content ─────────────────────────────────────


def test_long_content_uses_flash():
    """Content >8000 chars always routes to gemini-2.5-flash."""
    assert select_starting_model(content_length=9000) == "gemini-2.5-flash"


def test_youtube_always_uses_flash():
    """YouTube content routes to flash regardless of length."""
    assert select_starting_model(content_length=500, source_type="youtube") == "gemini-2.5-flash"


def test_newsletter_always_uses_flash():
    """Newsletter content routes to flash regardless of length."""
    assert select_starting_model(content_length=1000, source_type="newsletter") == "gemini-2.5-flash"


def test_github_always_uses_flash():
    """GitHub content routes to flash regardless of length."""
    assert select_starting_model(content_length=800, source_type="github") == "gemini-2.5-flash"


def test_medium_content_uses_flash():
    """Content between 2000-8000 chars routes to flash."""
    assert select_starting_model(content_length=5000) == "gemini-2.5-flash"


# ── Lite model for simple/short content ─────────────────────────────────────


def test_short_content_uses_lite():
    """Content <2000 chars routes to flash-lite."""
    assert select_starting_model(content_length=500) == "gemini-2.5-flash-lite"


def test_short_reddit_uses_lite():
    """Short Reddit content routes to flash-lite."""
    assert select_starting_model(content_length=800, source_type="reddit") == "gemini-2.5-flash-lite"


def test_short_web_uses_lite():
    """Short generic web content routes to flash-lite."""
    assert select_starting_model(content_length=1500, source_type="web") == "gemini-2.5-flash-lite"


# ── Edge cases ──────────────────────────────────────────────────────────────


def test_exactly_2000_uses_flash():
    """Boundary: exactly 2000 chars routes to flash (>= 2000 threshold)."""
    assert select_starting_model(content_length=2000) == "gemini-2.5-flash"


def test_no_source_type_short():
    """No source type + short content → flash-lite."""
    assert select_starting_model(content_length=100, source_type=None) == "gemini-2.5-flash-lite"


def test_no_source_type_long():
    """No source type + long content → flash."""
    assert select_starting_model(content_length=10000, source_type=None) == "gemini-2.5-flash"
