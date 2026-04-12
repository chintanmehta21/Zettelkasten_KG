"""URL router tests: detect SourceType from URL."""
import pytest

from website.features.summarization_engine.core.models import SourceType
from website.features.summarization_engine.core.router import detect_source_type


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://github.com/foo/bar", SourceType.GITHUB),
        ("https://www.github.com/foo/bar", SourceType.GITHUB),
        ("https://github.com/foo/bar/tree/main", SourceType.GITHUB),
        ("https://news.ycombinator.com/item?id=123", SourceType.HACKERNEWS),
        ("https://arxiv.org/abs/2310.11511", SourceType.ARXIV),
        ("https://arxiv.org/pdf/2310.11511", SourceType.ARXIV),
        ("https://ar5iv.labs.arxiv.org/html/2310.11511", SourceType.ARXIV),
        ("https://www.reddit.com/r/Python/comments/abc/test/", SourceType.REDDIT),
        ("https://old.reddit.com/r/Python/comments/abc/test/", SourceType.REDDIT),
        ("https://redd.it/abc123", SourceType.REDDIT),
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", SourceType.YOUTUBE),
        ("https://youtu.be/dQw4w9WgXcQ", SourceType.YOUTUBE),
        ("https://m.youtube.com/watch?v=dQw4w9WgXcQ", SourceType.YOUTUBE),
        ("https://www.linkedin.com/posts/satya_activity-1234", SourceType.LINKEDIN),
        ("https://stratechery.substack.com/p/some-post", SourceType.NEWSLETTER),
        ("https://medium.com/@author/some-post-abc123", SourceType.NEWSLETTER),
        ("https://author.substack.com/p/post", SourceType.NEWSLETTER),
        ("https://podcasts.apple.com/us/podcast/foo/id123?i=456", SourceType.PODCAST),
        ("https://open.spotify.com/episode/abc123", SourceType.PODCAST),
        ("https://overcast.fm/+XYZ", SourceType.PODCAST),
        ("https://twitter.com/user/status/1234567890", SourceType.TWITTER),
        ("https://x.com/user/status/1234567890", SourceType.TWITTER),
        ("https://example.com/article", SourceType.WEB),
        ("https://unknown-site.org/page", SourceType.WEB),
    ],
)
def test_detect_source_type(url, expected):
    assert detect_source_type(url) == expected


def test_detect_source_type_empty_returns_web():
    assert detect_source_type("") == SourceType.WEB


def test_detect_source_type_malformed_returns_web():
    assert detect_source_type("not-a-url") == SourceType.WEB

