import pytest
from unittest.mock import AsyncMock, patch

from website.features.summarization_engine.source_ingest.github.api_client import (
    GitHubApiClient,
    RepoSignals,
)


@pytest.mark.asyncio
async def test_fetch_languages_returns_sorted_percentages():
    client = GitHubApiClient(token="x", base_url="https://api.github.com", timeout_sec=5)
    with patch.object(client, "_get", new=AsyncMock()) as mock_get:
        mock_get.return_value = {"Python": 10000, "Rust": 5000, "Shell": 500}
        langs = await client.fetch_languages("a/b")
    assert langs[0][0] == "Python"
    assert round(langs[0][1], 1) == 64.5
    assert langs[-1][0] == "Shell"


@pytest.mark.asyncio
async def test_fetch_root_dir_detects_benchmarks_tests_examples():
    client = GitHubApiClient(token="x", base_url="https://api.github.com", timeout_sec=5)
    with patch.object(client, "_get", new=AsyncMock()) as mock_get:
        mock_get.return_value = [
            {"name": "src", "type": "dir"},
            {"name": "tests", "type": "dir"},
            {"name": "benchmarks", "type": "dir"},
            {"name": "README.md", "type": "file"},
        ]
        signals = await client.fetch_root_dir_signals("a/b")
    assert signals["has_tests"] is True
    assert signals["has_benchmarks"] is True
    assert signals["has_examples"] is False


@pytest.mark.asyncio
async def test_fetch_pages_handles_404_as_no_pages():
    client = GitHubApiClient(token="x", base_url="https://api.github.com", timeout_sec=5)
    with patch.object(client, "_get", new=AsyncMock(side_effect=_HttpError(404))):
        pages = await client.fetch_pages_url("a/b")
    assert pages is None


class _HttpError(Exception):
    def __init__(self, status):
        self.status = status
