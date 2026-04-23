"""Tests for the newsletter URL-liveness preflight probe."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from website.features.summarization_engine.core.errors import NewsletterURLUnreachable
from website.features.summarization_engine.source_ingest.newsletter.ingest import (
    NewsletterIngestor,
    _preflight_probe,
)


_GOOD_URL = "https://example.substack.com/p/post"
_BAD_URL = "https://example.substack.com/p/missing"


def _stub_ingest_env(monkeypatch: pytest.MonkeyPatch, html: str = "") -> None:
    """Common stubs so NewsletterIngestor can run in unit tests."""

    async def fake_fetch_and_extract(url: str, **kwargs):  # noqa: ARG001
        return ("Body text long enough.", {"title": "T"}, url, html)

    monkeypatch.setattr(
        "website.features.summarization_engine.source_ingest.newsletter.ingest._fetch_and_extract",
        fake_fetch_and_extract,
    )
    monkeypatch.setattr(
        "website.features.summarization_engine.source_ingest.newsletter.ingest.classify_stance",
        AsyncMock(return_value="neutral"),
    )
    fake_client = MagicMock()
    monkeypatch.setattr(
        "website.features.summarization_engine.api.routes._gemini_client",
        lambda: fake_client,
    )


@pytest.mark.asyncio
async def test_preflight_200_passes(httpx_mock):
    httpx_mock.add_response(method="HEAD", url=_GOOD_URL, status_code=200)

    await _preflight_probe(_GOOD_URL)  # no raise


@pytest.mark.asyncio
async def test_preflight_head_404_then_get_404_raises(httpx_mock):
    httpx_mock.add_response(method="HEAD", url=_BAD_URL, status_code=404)
    httpx_mock.add_response(method="GET", url=_BAD_URL, status_code=404)

    with pytest.raises(NewsletterURLUnreachable) as exc:
        await _preflight_probe(_BAD_URL)
    assert exc.value.status == 404
    assert "http_404" in exc.value.reason


@pytest.mark.asyncio
async def test_preflight_head_405_get_200_passes(httpx_mock):
    # Some CDNs reject HEAD; ranged GET should recover.
    httpx_mock.add_response(method="HEAD", url=_GOOD_URL, status_code=405)
    httpx_mock.add_response(method="GET", url=_GOOD_URL, status_code=200)

    await _preflight_probe(_GOOD_URL)


@pytest.mark.asyncio
async def test_preflight_5xx_raises(httpx_mock):
    httpx_mock.add_response(method="HEAD", url=_BAD_URL, status_code=503)
    httpx_mock.add_response(method="GET", url=_BAD_URL, status_code=503)

    with pytest.raises(NewsletterURLUnreachable) as exc:
        await _preflight_probe(_BAD_URL)
    assert exc.value.status == 503


@pytest.mark.asyncio
async def test_preflight_connect_error_raises(httpx_mock):
    # pytest-httpx: re-raise a ConnectError for every HEAD/GET to the URL.
    httpx_mock.add_exception(httpx.ConnectError("dns failure"), is_reusable=True)

    with pytest.raises(NewsletterURLUnreachable) as exc:
        await _preflight_probe("https://nonexistent.invalid/post")
    assert exc.value.status is None
    # Either the DNS/connect branch or the fallback HTTP-error branch is OK,
    # as long as it is clearly flagged as a reachability failure and not masked.
    assert exc.value.reason  # non-empty
    assert "timeout: timeoutexception" not in exc.value.reason.lower()


@pytest.mark.asyncio
async def test_preflight_timeout_raises(httpx_mock):
    httpx_mock.add_exception(httpx.ConnectTimeout("slow host"), is_reusable=True)

    with pytest.raises(NewsletterURLUnreachable) as exc:
        await _preflight_probe("https://slow.example.com/post")
    assert exc.value.status is None
    assert "timeout" in exc.value.reason.lower()


@pytest.mark.asyncio
async def test_preflight_empty_url_raises():
    with pytest.raises(NewsletterURLUnreachable) as exc:
        await _preflight_probe("")
    assert exc.value.reason == "empty_url"


@pytest.mark.asyncio
async def test_preflight_malformed_url_raises():
    with pytest.raises(NewsletterURLUnreachable) as exc:
        await _preflight_probe("not-a-url")
    assert exc.value.reason == "malformed_url"


@pytest.mark.asyncio
async def test_ingest_preflight_gate_404(
    monkeypatch: pytest.MonkeyPatch, httpx_mock
):
    """End-to-end: a 404 URL is short-circuited before extraction."""
    httpx_mock.add_response(method="HEAD", url=_BAD_URL, status_code=404)
    httpx_mock.add_response(method="GET", url=_BAD_URL, status_code=404)

    # If preflight fails to short-circuit, these would be invoked; they aren't.
    called: dict[str, bool] = {"fetch": False, "stance": False}

    async def fake_fetch_and_extract(url, **kwargs):  # noqa: ARG001
        called["fetch"] = True
        return ("text", {}, url, "<html></html>")

    async def fake_stance(*args, **kwargs):  # noqa: ARG001
        called["stance"] = True
        return "neutral"

    monkeypatch.setattr(
        "website.features.summarization_engine.source_ingest.newsletter.ingest._fetch_and_extract",
        fake_fetch_and_extract,
    )
    monkeypatch.setattr(
        "website.features.summarization_engine.source_ingest.newsletter.ingest.classify_stance",
        fake_stance,
    )

    with pytest.raises(NewsletterURLUnreachable):
        await NewsletterIngestor().ingest(_BAD_URL, config={})

    assert called["fetch"] is False
    assert called["stance"] is False


@pytest.mark.asyncio
async def test_ingest_preflight_gate_disabled(monkeypatch: pytest.MonkeyPatch):
    """Backward compat: opting out of preflight skips the probe entirely."""
    _stub_ingest_env(monkeypatch)

    # No httpx_mock network responses registered — if the probe ran, httpx
    # would fail because pytest-httpx is not installed here; since we didn't
    # use httpx_mock fixture, real network would be hit. Instead we just
    # verify the ingest completes when the gate is off by stubbing the fetch.
    result = await NewsletterIngestor().ingest(
        _GOOD_URL,
        config={"preflight_probe_enabled": False, "min_text_length": 10},
    )
    assert result.raw_text


@pytest.mark.asyncio
async def test_ingest_preflight_200_proceeds(
    monkeypatch: pytest.MonkeyPatch, httpx_mock
):
    """A live URL still flows through to extraction."""
    httpx_mock.add_response(method="HEAD", url=_GOOD_URL, status_code=200)
    _stub_ingest_env(monkeypatch)

    result = await NewsletterIngestor().ingest(
        _GOOD_URL, config={"min_text_length": 10}
    )
    assert result.raw_text
