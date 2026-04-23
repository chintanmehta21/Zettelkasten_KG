import pytest
from unittest.mock import AsyncMock, patch

from website.features.summarization_engine.source_ingest.reddit.pullpush import (
    PullPushResult,
    recover_removed_comments,
)


@pytest.mark.asyncio
async def test_recover_removed_comments_returns_list():
    mock_response = {
        "data": [
            {"id": "c1", "body": "Removed comment 1", "author": "[deleted]", "score": 5},
            {"id": "c2", "body": "Removed comment 2", "author": "user2", "score": 12},
        ]
    }
    with patch("httpx.AsyncClient.get", new=AsyncMock()) as mock_get:
        mock_get.return_value.json = lambda: mock_response
        mock_get.return_value.status_code = 200
        result = await recover_removed_comments(
            link_id="abc123",
            base_url="https://api.pullpush.io",
            timeout_sec=5,
            max_recovered=50,
        )
    assert isinstance(result, PullPushResult)
    assert len(result.comments) == 2
    assert result.comments[0].body == "Removed comment 1"


@pytest.mark.asyncio
async def test_recover_removed_comments_handles_timeout():
    import httpx

    with patch("httpx.AsyncClient.get", side_effect=httpx.ReadTimeout("slow")):
        result = await recover_removed_comments(
            link_id="abc123",
            base_url="https://api.pullpush.io",
            timeout_sec=1,
            max_recovered=50,
        )
    assert result.success is False
    assert "timeout" in (result.error or "").lower()


@pytest.mark.asyncio
async def test_recover_respects_max_cap():
    mock_response = {
        "data": [
            {"id": f"c{i}", "body": f"b{i}", "author": "u", "score": 1}
            for i in range(60)
        ]
    }
    with patch("httpx.AsyncClient.get", new=AsyncMock()) as mock_get:
        mock_get.return_value.json = lambda: mock_response
        mock_get.return_value.status_code = 200
        result = await recover_removed_comments(
            link_id="x",
            base_url="https://api.pullpush.io",
            timeout_sec=5,
            max_recovered=25,
        )
    assert len(result.comments) == 25
