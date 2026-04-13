"""YouTube ingestor fallback chain tests."""
from unittest.mock import patch, MagicMock

import pytest

from website.features.summarization_engine.source_ingest.youtube.ingest import (
    YouTubeIngestor,
    _fetch_oembed_and_meta,
)


@pytest.mark.asyncio
async def test_ingestor_uses_oembed_when_transcript_and_ytdlp_fail():
    """When transcript and yt-dlp both fail, oEmbed+meta should provide metadata."""
    ingestor = YouTubeIngestor()

    oembed_info = {
        "title": "Test Video Title",
        "channel": "Test Channel",
        "description": "A long enough description about this video that provides enough context for proper summarization to proceed.",
    }

    with patch(
        "website.features.summarization_engine.source_ingest.youtube.ingest._fetch_transcript",
        return_value="",
    ), patch(
        "website.features.summarization_engine.source_ingest.youtube.ingest._fetch_ytdlp_info",
        return_value={},
    ), patch(
        "website.features.summarization_engine.source_ingest.youtube.ingest._fetch_oembed_and_meta",
        return_value=oembed_info,
    ):
        result = await ingestor.ingest(
            "https://www.youtube.com/watch?v=abc123",
            config={},
        )

    assert result.metadata["title"] == "Test Video Title"
    assert result.metadata["channel"] == "Test Channel"
    assert result.extraction_confidence == "medium"
    assert "oembed" in result.confidence_reason
    assert "Test Video Title" in result.raw_text


@pytest.mark.asyncio
async def test_ingestor_prefers_ytdlp_over_oembed():
    """yt-dlp should be tried first; if it succeeds, oEmbed is never called."""
    ingestor = YouTubeIngestor()

    ytdlp_info = {
        "title": "yt-dlp Title",
        "channel": "yt-dlp Channel",
        "description": "A rich description from yt-dlp that is long enough to pass the minimum content threshold for summarization.",
        "duration": 300,
    }

    with patch(
        "website.features.summarization_engine.source_ingest.youtube.ingest._fetch_transcript",
        return_value="",
    ), patch(
        "website.features.summarization_engine.source_ingest.youtube.ingest._fetch_ytdlp_info",
        return_value=ytdlp_info,
    ) as mock_ytdlp, patch(
        "website.features.summarization_engine.source_ingest.youtube.ingest._fetch_oembed_and_meta",
    ) as mock_oembed:
        result = await ingestor.ingest(
            "https://www.youtube.com/watch?v=abc123",
            config={},
        )

    mock_ytdlp.assert_called_once()
    mock_oembed.assert_not_called()
    assert result.metadata["title"] == "yt-dlp Title"
    assert "yt-dlp" in result.confidence_reason


def test_fetch_oembed_and_meta_parses_response():
    """_fetch_oembed_and_meta correctly parses oEmbed JSON and page meta tags."""
    oembed_json = '{"title": "Video Title", "author_name": "Channel Name"}'
    page_html = '<html><head><meta property="og:description" content="Test description"></head></html>'

    mock_oembed_resp = MagicMock()
    mock_oembed_resp.status_code = 200
    mock_oembed_resp.json.return_value = {"title": "Video Title", "author_name": "Channel Name"}

    mock_page_resp = MagicMock()
    mock_page_resp.status_code = 200
    mock_page_resp.text = page_html

    mock_client = MagicMock()
    mock_client.get.side_effect = [mock_oembed_resp, mock_page_resp]
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)

    with patch("website.features.summarization_engine.source_ingest.youtube.ingest.httpx.Client", return_value=mock_client):
        result = _fetch_oembed_and_meta("https://www.youtube.com/watch?v=test123", "test123")

    assert result["title"] == "Video Title"
    assert result["channel"] == "Channel Name"
    assert result["description"] == "Test description"


def test_fetch_oembed_and_meta_returns_empty_on_failure():
    """If both oEmbed and page fetch fail, return empty dict."""
    with patch("website.features.summarization_engine.source_ingest.youtube.ingest.httpx.Client") as mock_cls:
        mock_cls.side_effect = Exception("network error")
        result = _fetch_oembed_and_meta("https://www.youtube.com/watch?v=fail", "fail")

    assert result == {}
