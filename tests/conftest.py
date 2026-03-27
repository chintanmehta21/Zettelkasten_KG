"""Shared pytest fixtures for the zettelkasten_bot test suite."""

import pytest


@pytest.fixture
def sample_reddit_url() -> str:
    return "https://www.reddit.com/r/python/comments/abc123/test_post/"


@pytest.fixture
def sample_youtube_url() -> str:
    return "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


@pytest.fixture
def sample_github_url() -> str:
    return "https://github.com/user/repo"


@pytest.fixture
def sample_newsletter_url() -> str:
    return "https://example.substack.com/p/my-post"


@pytest.fixture
def sample_generic_url() -> str:
    return "https://example.com/article"
