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
from website.features.summarization_engine.source_ingest.newsletter.ingest import NewsletterIngestor
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
        config={"fetch_issues": True, "fetch_commits": True, "fetch_docs": False},
    )

    assert result.source_type == SourceType.GITHUB
    assert "Official SDK" in result.raw_text
    assert result.metadata["stars"] == 12
    assert result.extraction_confidence == "high"


@pytest.mark.asyncio
async def test_github_fetch_docs_appends_contributing_and_docs_readme(
    httpx_mock: HTTPXMock,
):
    """GitHubIngestor should pull CONTRIBUTING.md and docs/README.md alongside the README."""
    readme_body = "# demo\n\nCore README."
    contrib_body = "# Contributing\n\nFollow these steps to submit a PR."
    docs_readme_body = "# Docs\n\nOverview of the docs directory."

    # 1. repo metadata
    httpx_mock.add_response(
        json={
            "name": "repo",
            "full_name": "foo/repo",
            "description": "Docs test repo",
            "stargazers_count": 0,
            "forks_count": 0,
            "language": "Python",
            "topics": [],
            "license": None,
            "updated_at": "2026-04-01T00:00:00Z",
            "default_branch": "main",
        }
    )
    # 2. README
    httpx_mock.add_response(
        json={"content": base64.b64encode(readme_body.encode()).decode()}
    )
    # 3. languages
    httpx_mock.add_response(json={"Python": 100})
    # 4. issues (empty)
    httpx_mock.add_response(json=[])
    # 5. commits (empty)
    httpx_mock.add_response(json=[])
    # 6. /contents top-level listing
    httpx_mock.add_response(
        json=[
            {"name": "README.md", "type": "file"},
            {"name": "CONTRIBUTING.md", "type": "file"},
            {"name": "docs", "type": "dir"},
        ]
    )
    # 7. CONTRIBUTING.md file fetch
    httpx_mock.add_response(
        json={
            "encoding": "base64",
            "content": base64.b64encode(contrib_body.encode()).decode(),
        }
    )
    # 8. docs/README.md file fetch
    httpx_mock.add_response(
        json={
            "encoding": "base64",
            "content": base64.b64encode(docs_readme_body.encode()).decode(),
        }
    )
    # 9-14. Remaining docs/ candidate slots (index, getting-started, overview;
    # lowercase and uppercase variants) all absent.
    for _ in range(6):
        httpx_mock.add_response(status_code=404)

    result = await GitHubIngestor().ingest(
        "https://github.com/foo/repo",
        config={
            "fetch_issues": True,
            "fetch_commits": True,
            "fetch_docs": True,
            "max_docs": 4,
            "doc_char_cap": 2000,
        },
    )

    assert "Core README" in result.raw_text
    assert "Follow these steps" in result.raw_text
    assert "Overview of the docs directory" in result.raw_text
    assert "CONTRIBUTING.md" in result.metadata["extra_doc_files"]
    assert any(
        name.startswith("docs/README") for name in result.metadata["extra_doc_files"]
    )
    assert result.extraction_confidence == "high"
    assert "extra doc" in result.confidence_reason


@pytest.mark.asyncio
async def test_github_fetch_docs_missing_docs_dir_still_succeeds(httpx_mock: HTTPXMock):
    """When a repo has no docs/ directory and no governance docs, the README alone still produces a high-confidence result."""
    readme_body = "# demo\n\nOnly a README, nothing else."

    httpx_mock.add_response(
        json={
            "name": "repo",
            "full_name": "foo/bare",
            "description": "Bare repo",
            "stargazers_count": 0,
            "forks_count": 0,
            "language": "Python",
            "topics": [],
            "license": None,
            "updated_at": "2026-04-01T00:00:00Z",
            "default_branch": "main",
        }
    )
    httpx_mock.add_response(
        json={"content": base64.b64encode(readme_body.encode()).decode()}
    )
    httpx_mock.add_response(json={"Python": 100})
    httpx_mock.add_response(json=[])
    httpx_mock.add_response(json=[])
    # /contents listing with no docs-eligible entries
    httpx_mock.add_response(
        json=[
            {"name": "README.md", "type": "file"},
            {"name": "src", "type": "dir"},
        ]
    )

    result = await GitHubIngestor().ingest(
        "https://github.com/foo/bare",
        config={"fetch_docs": True, "max_docs": 4},
    )

    assert "Only a README" in result.raw_text
    assert result.metadata["extra_doc_files"] == []
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
async def test_newsletter_direct_fetch_succeeds_without_fallback(httpx_mock: HTTPXMock):
    """If the direct fetch returns enough content, no bypass provider is called."""
    long_article = (
        "<html><head><title>The Article</title></head><body><article>"
        + "<p>" + ("Substantial content about the topic. " * 80) + "</p>"
        + "</article></body></html>"
    )
    # Only the direct fetch is mocked — if the ingestor tries a bypass provider
    # pytest_httpx will raise because there is no matching response.
    httpx_mock.add_response(url="https://example.substack.com/p/post", html=long_article)

    result = await NewsletterIngestor().ingest(
        "https://example.substack.com/p/post",
        config={"min_text_length": 100, "googlebot_ua": True},
    )

    assert result.source_type == SourceType.NEWSLETTER
    assert "Substantial content" in result.raw_text
    assert result.extraction_confidence == "high"
    assert result.metadata["paywall_provider"] == "direct"


@pytest.mark.asyncio
async def test_newsletter_wayback_fallback_recovers_paywalled_article(
    httpx_mock: HTTPXMock,
):
    """When the direct fetch is paywalled/short, wayback should supply the body."""
    paywalled = "<html><head><title>Paywalled</title></head><body><p>Subscribe to read.</p></body></html>"
    full_article = (
        "<html><head><title>Full Article</title></head><body><article>"
        + "<p>" + ("Full unlocked content from the wayback snapshot. " * 80) + "</p>"
        + "</article></body></html>"
    )

    # Direct fetch — short (< min_text_length)
    httpx_mock.add_response(
        url="https://example.substack.com/p/paywalled",
        html=paywalled,
    )
    # Wayback API lookup
    httpx_mock.add_response(
        url="https://archive.org/wayback/available?url=https%3A%2F%2Fexample.substack.com%2Fp%2Fpaywalled",
        json={
            "archived_snapshots": {
                "closest": {
                    "url": "https://web.archive.org/web/2026/https://example.substack.com/p/paywalled",
                    "available": True,
                }
            }
        },
    )
    # Snapshot fetch
    httpx_mock.add_response(
        url="https://web.archive.org/web/2026/https://example.substack.com/p/paywalled",
        html=full_article,
    )

    result = await NewsletterIngestor().ingest(
        "https://example.substack.com/p/paywalled",
        config={
            "min_text_length": 500,
            "googlebot_ua": False,  # avoid duplicate direct fetch with googlebot UA
            "paywall_fallbacks": ["wayback"],
        },
    )

    assert "Full unlocked content" in result.raw_text
    assert result.metadata["paywall_provider"] == "wayback"
    assert result.extraction_confidence == "high"


@pytest.mark.asyncio
async def test_newsletter_all_providers_fail_returns_low_confidence(
    httpx_mock: HTTPXMock,
):
    """Every provider 500s → empty body and low confidence, no exception."""
    # Direct fetch fails
    httpx_mock.add_response(
        url="https://example.medium.com/p/dead",
        status_code=500,
    )
    # Wayback API returns no snapshot
    httpx_mock.add_response(
        url="https://archive.org/wayback/available?url=https%3A%2F%2Fexample.medium.com%2Fp%2Fdead",
        json={"archived_snapshots": {}},
    )

    result = await NewsletterIngestor().ingest(
        "https://example.medium.com/p/dead",
        config={
            "min_text_length": 500,
            "googlebot_ua": False,
            "paywall_fallbacks": ["wayback"],
        },
    )

    assert result.raw_text == ""
    assert result.extraction_confidence == "low"
    assert result.metadata["paywall_provider"] == "direct"


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
