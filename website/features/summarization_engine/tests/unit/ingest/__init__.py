"""Unit tests for source ingestors with mocked network calls."""
from __future__ import annotations

import base64

import pytest
from pytest_httpx import HTTPXMock

from website.features.summarization_engine.core.errors import ExtractionError
from website.features.summarization_engine.core.models import SourceType
from website.features.summarization_engine.source_ingest import get_ingestor, list_ingestors
from website.features.summarization_engine.source_ingest.github.ingest import GitHubIngestor
from website.features.summarization_engine.source_ingest.hackernews.ingest import HackerNewsIngestor
from website.features.summarization_engine.source_ingest.web.ingest import WebIngestor


def test_auto_discovery_finds_all_source_ingestors():
    mapping = list_ingestors()
    for source_type in SourceType:
        assert source_type in mapping
        assert get_ingestor(source_type) is mapping[source_type]


@pytest.mark.asyncio
async def test_github_ingest_public_repo(httpx_mock: HTTPXMock):
    readme = "# demo\n\nOfficial SDK for testing."
    httpx_mock.add_response(
        json={
            "name": "repo",
            "full_name": "foo/repo",
            "description": "A test repo",
            "stargazers_count": 12,
            "forks_count": 2,
            "language": "Python",
            "topics": ["ai", "tools"],
            "license": {"spdx_id": "MIT"},
            "updated_at": "2026-04-01T00:00:00Z",
        }
    )
    httpx_mock.add_response(json={"content": base64.b64encode(readme.encode()).decode()})
    httpx_mock.add_response(json={"Python": 100})
    httpx_mock.add_response(json=[{"number": 1, "title": "Bug", "body": "Fix it"}])
    httpx_mock.add_response(json=[{"sha": "abc", "commit": {"message": "feat: test"}}])

    result = await GitHubIngestor().ingest(
        "https://github.com/foo/repo",
        config={"fetch_issues": True, "fetch_commits": True},
    )

    assert result.source_type == SourceType.GITHUB
    assert "Official SDK" in result.raw_text
    assert result.metadata["stars"] == 12
    assert result.extraction_confidence == "high"


@pytest.mark.asyncio
async def test_github_404_raises(httpx_mock: HTTPXMock):
    httpx_mock.add_response(status_code=404)
    with pytest.raises(ExtractionError):
        await GitHubIngestor().ingest("https://github.com/foo/missing", config={})


@pytest.mark.asyncio
async def test_hackernews_ingest_flattens_comments(httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        json={
            "id": 123,
            "title": "Launch HN",
            "url": "https://example.com",
            "points": 42,
            "author": "pg",
            "children": [
                {"author": "a", "text": "First", "children": [{"author": "b", "text": "Reply"}]},
            ],
        }
    )
    result = await HackerNewsIngestor().ingest(
        "https://news.ycombinator.com/item?id=123",
        config={"max_comments": 10},
    )
    assert result.source_type == SourceType.HACKERNEWS
    assert "Launch HN" in result.raw_text
    assert "Reply" in result.raw_text


@pytest.mark.asyncio
async def test_web_ingest_extracts_html_text(httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        html="<html><head><title>Demo</title></head><body><article><h1>Demo</h1><p>Hello world article text.</p></article></body></html>"
    )
    result = await WebIngestor().ingest("https://example.com/post", config={"min_text_length": 10})
    assert result.source_type == SourceType.WEB
    assert "Hello world" in result.raw_text
    assert result.metadata["title"] == "Demo"
    assert result.extraction_confidence == "high"

