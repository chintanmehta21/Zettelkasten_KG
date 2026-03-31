"""Tests for telegram_bot.utils.url_utils.

All tests are fully offline — httpx is mocked so no real network calls happen.
"""

from __future__ import annotations

import pytest
import httpx
from unittest.mock import AsyncMock, MagicMock, patch

from telegram_bot.utils.url_utils import (
    validate_url,
    normalize_url,
    resolve_redirects,
    is_shortener,
)


# ─────────────────────────────────────────────────────────────────────────────
# validate_url
# ─────────────────────────────────────────────────────────────────────────────


def test_validate_url_valid_http():
    assert validate_url("http://example.com") is True


def test_validate_url_valid_https():
    assert validate_url("https://example.com/path?q=1") is True


def test_validate_url_valid_https_with_port():
    assert validate_url("https://example.com:8080/path") is True


def test_validate_url_rejects_ftp():
    assert validate_url("ftp://example.com/file.txt") is False


def test_validate_url_rejects_no_scheme():
    assert validate_url("example.com/path") is False


def test_validate_url_rejects_empty():
    assert validate_url("") is False


def test_validate_url_rejects_scheme_only():
    # "http://" has empty netloc
    assert validate_url("http://") is False


def test_validate_url_none_raises_type_error():
    """Passing None must raise TypeError (not silently return False)."""
    with pytest.raises((TypeError, AttributeError)):
        validate_url(None)  # type: ignore[arg-type]


def test_validate_url_rejects_fragment_only():
    assert validate_url("#section") is False


# ─────────────────────────────────────────────────────────────────────────────
# normalize_url
# ─────────────────────────────────────────────────────────────────────────────


def test_normalize_strips_utm_params():
    url = "https://example.com/page?utm_source=newsletter&utm_medium=email&content=real"
    result = normalize_url(url)
    assert "utm_source" not in result
    assert "utm_medium" not in result
    assert "content=real" in result


def test_normalize_strips_all_tracking_params():
    tracking = (
        "https://example.com/?utm_source=a&utm_medium=b&utm_campaign=c"
        "&utm_term=d&utm_content=e&fbclid=f&gclid=g&ref=h&source=i"
    )
    result = normalize_url(tracking)
    for param in ("utm_source", "utm_medium", "utm_campaign", "utm_term",
                  "utm_content", "fbclid", "gclid", "ref", "source"):
        assert param not in result


def test_normalize_lowercases_host():
    result = normalize_url("https://EXAMPLE.COM/Path")
    assert result.startswith("https://example.com/")


def test_normalize_lowercases_scheme():
    result = normalize_url("HTTP://example.com/")
    assert result.startswith("http://")


def test_normalize_strips_fragment():
    result = normalize_url("https://example.com/page#section")
    assert "#" not in result
    assert "section" not in result


def test_normalize_preserves_non_tracking_params():
    result = normalize_url("https://example.com/?q=search&page=2")
    assert "q=search" in result
    assert "page=2" in result


def test_normalize_sorts_params():
    url_a = normalize_url("https://example.com/?z=last&a=first")
    url_b = normalize_url("https://example.com/?a=first&z=last")
    assert url_a == url_b


def test_normalize_url_with_only_tracking_params():
    """A URL whose entire query is tracking params should produce an empty query."""
    result = normalize_url("https://example.com/?utm_source=x&fbclid=y")
    # No query string characters should remain
    assert "?" not in result or result.endswith("?")


def test_normalize_url_with_no_path():
    """URL with no path component should survive normalization."""
    result = normalize_url("https://example.com")
    assert result.startswith("https://example.com")


# ─────────────────────────────────────────────────────────────────────────────
# resolve_redirects (async — uses mocked httpx)
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_resolve_redirects_follows():
    """resolve_redirects returns the final URL reported by httpx."""
    final_url = "https://final-destination.com/page"

    mock_response = MagicMock()
    mock_response.url = httpx.URL(final_url)
    mock_response.status_code = 200

    mock_client = AsyncMock()
    mock_client.head = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("telegram_bot.utils.url_utils.httpx.AsyncClient", return_value=mock_client):
        result = await resolve_redirects("https://bit.ly/short")

    assert result == final_url


@pytest.mark.asyncio
async def test_resolve_redirects_falls_back_to_get_on_4xx():
    """HEAD returning 405 should trigger a GET fallback."""
    final_url = "https://final.com/page"

    head_response = MagicMock()
    head_response.url = httpx.URL("https://bit.ly/short")
    head_response.status_code = 405

    get_response = MagicMock()
    get_response.url = httpx.URL(final_url)
    get_response.status_code = 200

    mock_client = AsyncMock()
    mock_client.head = AsyncMock(return_value=head_response)
    mock_client.get = AsyncMock(return_value=get_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("telegram_bot.utils.url_utils.httpx.AsyncClient", return_value=mock_client):
        result = await resolve_redirects("https://bit.ly/short")

    assert result == final_url


@pytest.mark.asyncio
async def test_resolve_redirects_returns_original_on_connection_error():
    """httpx.ConnectError → return original URL without raising."""
    original = "https://bit.ly/broken"

    mock_client = AsyncMock()
    mock_client.head = AsyncMock(side_effect=httpx.ConnectError("connection refused"))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("telegram_bot.utils.url_utils.httpx.AsyncClient", return_value=mock_client):
        result = await resolve_redirects(original)

    assert result == original


@pytest.mark.asyncio
async def test_resolve_redirects_returns_original_on_timeout():
    """httpx.TimeoutException → return original URL without raising."""
    original = "https://slow-server.com/page"

    mock_client = AsyncMock()
    mock_client.head = AsyncMock(
        side_effect=httpx.TimeoutException("timed out", request=None)
    )
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("telegram_bot.utils.url_utils.httpx.AsyncClient", return_value=mock_client):
        result = await resolve_redirects(original)

    assert result == original


@pytest.mark.asyncio
async def test_resolve_redirects_returns_original_on_generic_exception():
    """Any unexpected exception → return original URL."""
    original = "https://example.com/page"

    mock_client = AsyncMock()
    mock_client.head = AsyncMock(side_effect=RuntimeError("unexpected"))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("telegram_bot.utils.url_utils.httpx.AsyncClient", return_value=mock_client):
        result = await resolve_redirects(original)

    assert result == original


# ─────────────────────────────────────────────────────────────────────────────
# is_shortener
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "url",
    [
        "https://bit.ly/abc123",
        "https://tinyurl.com/xyz",
        "https://t.co/AbCdEf",
        "https://goo.gl/maps/test",
        "https://ow.ly/link",
        "https://is.gd/short",
        "https://buff.ly/post",
        "https://adf.ly/1234",
        "https://shorturl.at/mylink",
        "https://rb.gy/abc123",
        "https://v.gd/short",
        "https://tiny.cc/xyz",
        "https://lnkd.in/post",
        "https://amzn.to/product",
        "https://youtu.be/dQw4w9WgXcQ",
        "https://redd.it/abc123",
    ],
)
def test_is_shortener_true(url: str):
    assert is_shortener(url) is True


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/page",
        "https://github.com/user/repo",
        "https://reddit.com/r/python",
        "https://youtube.com/watch?v=abc",
        "https://medium.com/@author/article",
        "https://www.google.com/search?q=test",
    ],
)
def test_is_shortener_false(url: str):
    assert is_shortener(url) is False


def test_is_shortener_with_www_prefix():
    """www. prefix should not affect shortener detection."""
    assert is_shortener("https://www.bit.ly/test") is True
