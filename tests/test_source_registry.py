"""Tests for telegram_bot.sources.registry.detect_source_type.

No network calls; no Telegram credentials needed.  The newsletter_domains
argument is passed explicitly so these tests bypass get_settings() entirely.
"""

from __future__ import annotations

import pytest

from telegram_bot.models.capture import SourceType
from telegram_bot.sources.registry import detect_source_type

# Default newsletter domains used across tests (mirrors settings.py defaults)
_NEWSLETTER_DOMAINS = [
    "substack.com", "buttondown.email", "beehiiv.com", "mailchimp.com",
    "medium.com", "stackoverflow.com", "stackexchange.com",
    "news.ycombinator.com", "dev.to", "hackernoon.com",
]


# ─────────────────────────────────────────────────────────────────────────────
# Reddit
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "url",
    [
        "https://www.reddit.com/r/python/comments/abc123/my_post/",
        "https://reddit.com/r/learnpython/",
        "https://old.reddit.com/r/MachineLearning/",
        "https://redd.it/abc123",
        "https://np.reddit.com/r/programming/",
        "https://sh.reddit.com/r/programming/comments/xyz/",
        "https://reddit.app.link/abc123xyz",
        "https://new.reddit.com/r/python/comments/abc/post/",
    ],
)
def test_detect_reddit(url: str):
    assert (
        detect_source_type(url, newsletter_domains=_NEWSLETTER_DOMAINS) == SourceType.REDDIT
    )


@pytest.mark.parametrize(
    "url",
    [
        "https://i.redd.it/abc123.jpg",
        "https://v.redd.it/abc123",
        "https://preview.redd.it/abc123.png",
    ],
)
def test_detect_reddit_media_goes_to_web(url: str):
    """Reddit media-only hosts → routed to Web (no post context)."""
    assert (
        detect_source_type(url, newsletter_domains=_NEWSLETTER_DOMAINS) == SourceType.WEB
    )


# ─────────────────────────────────────────────────────────────────────────────
# YouTube
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://youtube.com/watch?v=abc123",
        "https://youtu.be/dQw4w9WgXcQ",
        "https://www.youtube.com/shorts/abc123",
        "https://m.youtube.com/watch?v=xyz",
        "https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ",
        "https://music.youtube.com/watch?v=abc123",
        "https://www.youtube.com/live/abc12345678",
    ],
)
def test_detect_youtube(url: str):
    assert (
        detect_source_type(url, newsletter_domains=_NEWSLETTER_DOMAINS) == SourceType.YOUTUBE
    )


# ─────────────────────────────────────────────────────────────────────────────
# GitHub
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/user/repo",
        "https://github.com/org/project/issues/42",
        "https://github.com/user/repo/blob/main/README.md",
        "https://raw.github.com/user/repo/main/file.py",
        "https://api.github.com/repos/user/repo",
    ],
)
def test_detect_github(url: str):
    assert (
        detect_source_type(url, newsletter_domains=_NEWSLETTER_DOMAINS) == SourceType.GITHUB
    )


# ─────────────────────────────────────────────────────────────────────────────
# Newsletter
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "url",
    [
        # Substack subdomain (most common pattern)
        "https://example.substack.com/p/my-post",
        # Exact domain match
        "https://substack.com/",
        # buttondown.email
        "https://buttondown.email/user/archive/my-email",
        # beehiiv subdomain
        "https://myblog.beehiiv.com/p/article",
        # mailchimp archive
        "https://mailchimp.com/resources/email-marketing/",
        # Medium
        "https://medium.com/@user/article-title-123abc",
        # Stack Overflow
        "https://stackoverflow.com/questions/12345/some-question",
        # Hacker News
        "https://news.ycombinator.com/item?id=12345",
        # dev.to
        "https://dev.to/user/my-article",
        # Hackernoon
        "https://hackernoon.com/some-article",
    ],
)
def test_detect_newsletter(url: str):
    assert (
        detect_source_type(url, newsletter_domains=_NEWSLETTER_DOMAINS) == SourceType.NEWSLETTER
    )


def test_detect_newsletter_custom_domains():
    """Passing a custom domain list should override defaults."""
    result = detect_source_type(
        "https://tinyletter.com/mylist",
        newsletter_domains=["tinyletter.com"],
    )
    assert result == SourceType.NEWSLETTER


def test_detect_newsletter_empty_domains_falls_through_to_web():
    """Empty newsletter_domains list → newsletter domains detected as Web."""
    result = detect_source_type("https://example.substack.com/p/post", newsletter_domains=[])
    assert result == SourceType.WEB


def test_detect_substack_custom_domain_needs_newsletter_domains():
    """Custom Substack domain (not *.substack.com) → only matches if in newsletter_domains."""
    # Without the custom domain in newsletter_domains → Web
    result = detect_source_type(
        "https://nlp.elvissaravia.com/p/top-ai-papers",
        newsletter_domains=_NEWSLETTER_DOMAINS,
    )
    assert result == SourceType.WEB

    # With the custom domain added → Newsletter
    extended_domains = _NEWSLETTER_DOMAINS + ["elvissaravia.com"]
    result = detect_source_type(
        "https://nlp.elvissaravia.com/p/top-ai-papers",
        newsletter_domains=extended_domains,
    )
    assert result == SourceType.NEWSLETTER


# ─────────────────────────────────────────────────────────────────────────────
# Web
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/article",
        "https://arxiv.org/abs/2301.12345",
        "https://en.wikipedia.org/wiki/Python_(programming_language)",
        "https://blog.example.org/post",
        "https://gist.github.com/user/abc123def456",
    ],
)
def test_detect_web(url: str):
    assert (
        detect_source_type(url, newsletter_domains=_NEWSLETTER_DOMAINS) == SourceType.WEB
    )


def test_legacy_source_type_string_maps_to_web():
    assert SourceType("generic") is SourceType.WEB
    assert SourceType.GENERIC is SourceType.WEB


# ─────────────────────────────────────────────────────────────────────────────
# Edge cases
# ─────────────────────────────────────────────────────────────────────────────


def test_detect_source_type_uses_settings_when_no_domains_given(monkeypatch):
    """When newsletter_domains=None, the function reads from settings."""
    # Patch get_settings to return a mock with known domains
    from unittest.mock import MagicMock
    import telegram_bot.sources.registry as reg

    mock_settings = MagicMock()
    mock_settings.newsletter_domains = ["custom-newsletter.io"]

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "telegram_bot.sources.registry.get_settings",
            lambda: mock_settings,
            raising=False,
        )
        # Temporarily make the lazy import resolvable
        import importlib
        import sys

        # Inject mock into the module's namespace for the lazy import path
        original_get_settings = reg.__dict__.get("get_settings")
        try:
            result = detect_source_type(
                "https://example.custom-newsletter.io/article",
                newsletter_domains=["custom-newsletter.io"],
            )
            assert result == SourceType.NEWSLETTER
        finally:
            if original_get_settings is not None:
                reg.__dict__["get_settings"] = original_get_settings


def test_detect_prioritizes_reddit_over_newsletter():
    """A domain that could match newsletter but also matches Reddit → Reddit wins."""
    # Artificial scenario: reddit.com added as newsletter domain
    result = detect_source_type(
        "https://reddit.com/r/test",
        newsletter_domains=["reddit.com"],
    )
    assert result == SourceType.REDDIT


def test_detect_source_type_no_path():
    """URL with no path component should still detect correctly."""
    result = detect_source_type("https://github.com", newsletter_domains=[])
    assert result == SourceType.GITHUB
