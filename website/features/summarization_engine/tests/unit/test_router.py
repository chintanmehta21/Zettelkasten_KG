"""URL router tests: detect SourceType from URL."""
import pytest

from website.features.summarization_engine.core.models import SourceType
from website.features.summarization_engine.core.router import (
    detect_route_decision,
    detect_source_type,
)


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
        ("https://newsletter.pragmaticengineer.com/p/the-product-minded-engineer", SourceType.NEWSLETTER),
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


@pytest.mark.parametrize(
    ("url", "subtype", "supported"),
    [
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "video", True),
        ("https://youtu.be/dQw4w9WgXcQ", "video", True),
        ("https://www.youtube.com/shorts/dQw4w9WgXcQ", "video", True),
        ("https://www.youtube.com/embed/dQw4w9WgXcQ", "video", True),
        ("https://www.youtube.com/@somechannel", "channel", False),
        ("https://www.youtube.com/playlist?list=PL123", "playlist", False),
        ("https://github.com/foo/bar", "repo", True),
        ("https://github.com/foo/bar/issues/10", "issue", True),
        ("https://github.com/foo/bar/pull/11", "pull_request", True),
        ("https://github.com/foo/bar/commit/abc123", "commit", True),
        ("https://github.com/foo/bar/releases/tag/v1.0.0", "release", True),
        ("https://github.com/foo/bar/blob/main/README.md", "blob", True),
        ("https://github.com/foo/bar/tree/main/src", "tree", True),
        ("https://www.linkedin.com/posts/satya_activity-1234", "post", True),
        ("https://www.linkedin.com/login", "authwall", False),
        ("https://arxiv.org/abs/2310.11511", "abstract", True),
        ("https://arxiv.org/pdf/2310.11511", "pdf", True),
        ("https://ar5iv.labs.arxiv.org/html/2310.11511", "html", True),
        ("https://open.spotify.com/episode/abc123", "episode", True),
        ("https://twitter.com/user/status/1234567890", "status", True),
    ],
)
def test_detect_route_decision_subtypes(url, subtype, supported):
    decision = detect_route_decision(url)
    assert decision.subtype == subtype
    assert decision.supported is supported


def test_detect_route_decision_marks_bad_youtube_shape_without_changing_family():
    decision = detect_route_decision("https://www.youtube.com/@somechannel")

    assert decision.source_type == SourceType.YOUTUBE
    assert decision.supported is False
    assert decision.reason == "unsupported_youtube_channel"


@pytest.mark.parametrize(
    ("url", "subtype", "supported"),
    [
        # Post permalinks — supported (existing ingestion behavior preserved).
        ("https://www.reddit.com/r/onions/comments/abc123/some_slug/", "post", True),
        ("https://www.reddit.com/r/onions/comments/abc123/", "post", True),
        ("https://old.reddit.com/r/Python/comments/abc/test/", "post", True),
        ("https://www.reddit.com/comments/abc123", "post", True),
        ("https://redd.it/abc123", "post_shortlink", True),
        # Comment permalink — unsupported (6th segment is a comment id; the JSON
        # shape differs from a thread and the summarizer would mis-extract).
        (
            "https://www.reddit.com/r/onions/comments/abc123/some_slug/def456/",
            "comment_permalink",
            False,
        ),
        # Subreddit listings — unsupported. THIS is the silent-pollution case:
        # the old generic route accepted these and persisted empty zettels.
        ("https://www.reddit.com/r/onions/", "subreddit_listing", False),
        ("https://www.reddit.com/r/onions/top/?t=all", "subreddit_listing", False),
        ("https://www.reddit.com/r/onions/hot", "subreddit_listing", False),
        # Wiki pages — unsupported (need bespoke ingestion).
        ("https://www.reddit.com/r/onions/wiki/index", "wiki", False),
        # User profiles — unsupported.
        ("https://www.reddit.com/user/spez/", "user_profile", False),
        ("https://www.reddit.com/u/spez", "user_profile", False),
        # Multireddit — unsupported.
        ("https://www.reddit.com/user/spez/m/tech/", "multireddit", False),
    ],
)
def test_reddit_route_subtypes(url, subtype, supported):
    decision = detect_route_decision(url)
    assert decision.source_type == SourceType.REDDIT
    assert decision.subtype == subtype
    assert decision.supported is supported


def test_reddit_listing_carries_unsupported_reason():
    decision = detect_route_decision("https://www.reddit.com/r/onions/top/?t=all")
    assert decision.supported is False
    assert decision.reason == "unsupported_reddit_url_shape"


# ---------------------------------------------------------------------------
# G2 — newsletter probe (refine_web_route)
# ---------------------------------------------------------------------------
from website.features.summarization_engine.core.router import refine_web_route  # noqa: E402

_WEB_DECISION = detect_route_decision("https://example.com/some-article")


def _const_fetcher(html: str):
    async def _f(_url: str) -> str:
        return html

    return _f


async def test_probe_reclassifies_blogposting_jsonld():
    html = (
        '<html><head><script type="application/ld+json">'
        '{"@context":"https://schema.org","@type":"BlogPosting","headline":"x"}'
        "</script></head></html>"
    )
    d = await refine_web_route(
        "https://blog.example/post-1", _WEB_DECISION, fetcher=_const_fetcher(html)
    )
    assert d.source_type == SourceType.NEWSLETTER
    assert d.subtype == "post"


async def test_probe_reclassifies_substack_generator():
    html = '<head><meta name="generator" content="Substack"></head>'
    d = await refine_web_route(
        "https://sub.example/p/a", _WEB_DECISION, fetcher=_const_fetcher(html)
    )
    assert d.source_type == SourceType.NEWSLETTER


async def test_probe_reclassifies_ghost_generator():
    html = '<head><meta content="Ghost 5.20" name="generator"></head>'
    d = await refine_web_route(
        "https://ghost.example/welcome", _WEB_DECISION, fetcher=_const_fetcher(html)
    )
    assert d.source_type == SourceType.NEWSLETTER


async def test_probe_ignores_plain_news_article_with_rss_and_newsarticle():
    # og:type=article + RSS feed + NewsArticle JSON-LD, but NO BlogPosting and
    # NO newsletter-platform generator. Must NOT be reclassified (news != newsletter).
    html = (
        "<head>"
        '<meta property="og:type" content="article">'
        '<link rel="alternate" type="application/rss+xml" href="/feed.xml">'
        '<meta name="generator" content="WordPress 6.4">'
        '<script type="application/ld+json">{"@type":"NewsArticle"}</script>'
        "</head>"
    )
    d = await refine_web_route(
        "https://news.example/story", _WEB_DECISION, fetcher=_const_fetcher(html)
    )
    assert d.source_type == SourceType.WEB


async def test_probe_fault_tolerant_on_fetch_error():
    async def _boom(_url: str) -> str:
        raise RuntimeError("network down")

    d = await refine_web_route(
        "https://broken.example/p", _WEB_DECISION, fetcher=_boom
    )
    assert d.source_type == SourceType.WEB


async def test_probe_does_not_fetch_non_web_decision():
    gh = detect_route_decision("https://github.com/foo/bar")
    calls = {"n": 0}

    async def _counting(_url: str) -> str:
        calls["n"] += 1
        return '<meta name="generator" content="Ghost">'

    d = await refine_web_route("https://github.com/foo/bar", gh, fetcher=_counting)
    assert d is gh
    assert calls["n"] == 0
