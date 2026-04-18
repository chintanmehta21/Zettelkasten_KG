from __future__ import annotations

import asyncio

from website.core import url_utils


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
