from __future__ import annotations

import asyncio
import urllib.parse

import pytest

from website.core import url_utils
from website.core.url_utils import normalize_url


def test_normalize_url_strips_tracking_params() -> None:
    normalized = url_utils.normalize_url(
        "https://Example.COM/path?utm_source=newsletter&b=2&a=1#frag"
    )

    assert normalized == "https://example.com/path?a=1&b=2"


def test_validate_url_rejects_private_ip() -> None:
    assert url_utils.validate_url("http://127.0.0.1/path") is False


def test_resolve_redirects_returns_original_on_timeout(monkeypatch) -> None:
    class FakeTimeoutException(Exception):
        pass

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            self.args = args
            self.kwargs = kwargs

        async def __aenter__(self) -> "FakeClient":
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

        async def head(self, url: str):
            raise FakeTimeoutException()

        async def get(self, url: str):
            raise AssertionError("GET should not be called after timeout")

    monkeypatch.setattr(url_utils.httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(url_utils.httpx, "TimeoutException", FakeTimeoutException)

    original = "https://example.com/resource"

    result = asyncio.run(url_utils.resolve_redirects(original))

    assert result == original


# Dedup-critical coverage: the URL-dedup gate keys on
# normalize_url(resolve_redirects(url)), so any pair that should collapse must
# normalize to the same string. Each pair below was verified against the real
# normalize_url implementation before being asserted.
@pytest.mark.parametrize(
    ("a", "b"),
    [
        # scheme/host are lowercased by normalize_url
        ("https://Example.com/Path", "https://example.com/Path"),
        # query params are sorted by key
        ("https://example.com/p?b=2&a=1", "https://example.com/p?a=1&b=2"),
        # utm_source is in _TRACKING_PARAMS and is stripped
        ("https://example.com/p?utm_source=x&a=1", "https://example.com/p?a=1"),
        # fbclid is in _TRACKING_PARAMS and is stripped
        ("https://example.com/p?fbclid=zzz&a=1", "https://example.com/p?a=1"),
    ],
)
def test_normalize_url_collapses_dedup_equivalent_urls(a: str, b: str) -> None:
    assert normalize_url(a) == normalize_url(b)


@pytest.mark.parametrize(
    ("a", "b"),
    [
        # scheme-default ports are stripped so they dedup against the
        # port-less form (closes the prior dedup blind spot).
        ("https://example.com:443/p", "https://example.com/p"),
        ("http://example.com:80/p", "http://example.com/p"),
        ("https://Example.com:443/P?b=2&a=1", "https://example.com/P?a=1&b=2"),
    ],
)
def test_normalize_url_strips_scheme_default_port(a: str, b: str) -> None:
    assert normalize_url(a) == normalize_url(b)


@pytest.mark.parametrize(
    ("url", "expected_netloc"),
    [
        # non-default ports MUST be preserved (distinct resources)
        ("https://example.com:8443/p", "example.com:8443"),
        ("http://example.com:8080/p", "example.com:8080"),
        # cross-scheme: :80 under https / :443 under http are NOT defaults
        ("https://example.com:80/p", "example.com:80"),
        ("http://example.com:443/p", "example.com:443"),
        # port-like substrings in path must not be touched
        ("https://example.com/a:443", "example.com"),
    ],
)
def test_normalize_url_keeps_non_default_ports(url: str, expected_netloc: str) -> None:
    assert urllib.parse.urlparse(normalize_url(url)).netloc == expected_netloc


def test_normalize_url_preserves_distinct_query_meaning() -> None:
    # Protects the two Zoro iana rows that differ only by a non-tracking
    # query param — these must NOT collapse to one dedup key.
    assert normalize_url(
        "https://www.iana.org/help/example-domains?zk_verif=1"
    ) != normalize_url("https://www.iana.org/help/example-domains?api_verif=1")
