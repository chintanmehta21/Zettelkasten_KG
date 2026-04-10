"""Shared fixtures for summarization engine tests."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest


def pytest_addoption(parser):
    try:
        parser.addoption(
            "--live",
            action="store_true",
            default=False,
            help="Run live tests that hit real APIs (require credentials)",
        )
    except ValueError as exc:
        if "--live" not in str(exc):
            raise


def pytest_collection_modifyitems(config, items):
    if config.getoption("--live"):
        return
    skip_live = pytest.mark.skip(reason="need --live flag to run")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip_live)


@pytest.fixture
def sample_user_id() -> UUID:
    return UUID("00000000-0000-0000-0000-000000000001")


@pytest.fixture
def sample_urls() -> dict[str, str]:
    return {
        "github": "https://github.com/anthropic-ai/anthropic-sdk-python",
        "reddit": "https://www.reddit.com/r/Python/comments/abc123/test_post/",
        "youtube": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "hackernews": "https://news.ycombinator.com/item?id=40123456",
        "arxiv": "https://arxiv.org/abs/2310.11511",
        "newsletter": "https://stratechery.com/2024/some-post/",
        "linkedin": "https://www.linkedin.com/posts/satyanadella_activity-1234567890-abcd",
        "podcast": "https://podcasts.apple.com/us/podcast/lex-fridman/id1434243584?i=1000123456",
        "twitter": "https://twitter.com/elonmusk/status/1234567890123456789",
    }


@pytest.fixture
def mock_gemini_client():
    """Mock TieredGeminiClient that returns canned responses."""
    client = MagicMock()
    client.generate = AsyncMock()
    return client


@pytest.fixture
def fixtures_dir() -> Path:
    return Path(__file__).parent / "fixtures"
