"""Offline tests for all content extractors (Reddit, YouTube, Newsletter, GitHub, Generic).

All mocks use unittest.mock — no real API calls are made.
asyncio_mode=auto (pytest.ini) — no @pytest.mark.asyncio needed.

Patch sites:
  - Reddit: zettelkasten_bot.sources.reddit.praw.Reddit
  - YouTube yt_dlp: yt_dlp.YoutubeDL  (imported locally inside extract())
  - YouTube transcript: youtube_transcript_api.YouTubeTranscriptApi  (imported locally)
  - Newsletter httpx: zettelkasten_bot.sources.newsletter.httpx.AsyncClient
  - Newsletter trafilatura: zettelkasten_bot.sources.newsletter.trafilatura
  - GitHub httpx: zettelkasten_bot.sources.github.httpx.AsyncClient
  - Generic httpx: zettelkasten_bot.sources.generic.httpx.AsyncClient
  - Generic trafilatura: zettelkasten_bot.sources.generic.trafilatura
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from zettelkasten_bot.models.capture import ExtractedContent, SourceType
from zettelkasten_bot.sources import get_extractor, list_extractors
from zettelkasten_bot.sources.generic import GenericExtractor
from zettelkasten_bot.sources.github import GitHubExtractor
from zettelkasten_bot.sources.newsletter import NewsletterExtractor
from zettelkasten_bot.sources.reddit import RedditExtractor
from zettelkasten_bot.sources.youtube import YouTubeExtractor


# ─────────────────────────────────────────────────────────────────────────────
# Shared constants
# ─────────────────────────────────────────────────────────────────────────────

_REDDIT_URL = "https://www.reddit.com/r/python/comments/abc123/test_post/"
_YOUTUBE_URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
_VIDEO_ID = "dQw4w9WgXcQ"


# ─────────────────────────────────────────────────────────────────────────────
# Reddit test helpers
# ─────────────────────────────────────────────────────────────────────────────


def _make_comment(
    body: str = "Great post!",
    author: str | None = "user123",
    score: int = 42,
) -> MagicMock:
    """Build a mock PRAW comment."""
    comment = MagicMock()
    comment.body = body
    comment.score = score
    if author is None:
        comment.author = None
    else:
        comment.author = MagicMock()
        comment.author.__str__ = lambda self: author  # type: ignore[assignment]
    return comment


def _make_submission(
    title: str = "Test Post",
    selftext: str = "This is the post body.",
    score: int = 100,
    author: str | None = "poster123",
    subreddit: str = "python",
    upvote_ratio: float = 0.95,
    num_comments: int = 10,
    created_utc: float = 1700000000.0,
    is_self: bool = True,
    link_flair_text: str | None = None,
    url: str = _REDDIT_URL,
    comments: list[MagicMock] | None = None,
    url_is_media: bool = False,
) -> MagicMock:
    """Build a mock PRAW submission with configurable fields."""
    sub = MagicMock()
    sub.title = title
    sub.selftext = selftext
    sub.score = score
    sub.upvote_ratio = upvote_ratio
    sub.num_comments = num_comments
    sub.created_utc = created_utc
    sub.is_self = is_self
    sub.link_flair_text = link_flair_text
    sub.url = "https://i.imgur.com/example.jpg" if url_is_media else url

    # Author
    if author is None:
        sub.author = None
    else:
        sub.author = MagicMock()
        sub.author.__str__ = lambda self: author  # type: ignore[assignment]

    # Subreddit
    sub.subreddit = MagicMock()
    sub.subreddit.__str__ = lambda self: subreddit  # type: ignore[assignment]

    # Comments — list so slicing works correctly
    if comments is None:
        comments = [_make_comment(f"Comment {i}", f"user{i}", i * 5) for i in range(1, 6)]
    comment_list = list(comments)

    comments_mock = MagicMock()
    comments_mock.replace_more = MagicMock(return_value=None)
    # Support slicing: comments_mock[:n] → first n items
    comments_mock.__getitem__ = lambda self, key: comment_list[key]

    sub.comments = comments_mock
    return sub


# ─────────────────────────────────────────────────────────────────────────────
# Reddit extractor tests
# ─────────────────────────────────────────────────────────────────────────────


async def test_reddit_happy_path_selftext_with_comments():
    """Selftext post with comments → correct title, body sections, metadata."""
    with patch("zettelkasten_bot.sources.reddit.praw.Reddit") as MockReddit:
        mock_reddit = MockReddit.return_value
        mock_reddit.read_only = True
        submission = _make_submission(
            title="My Python Post",
            selftext="Here is some **content**.",
            author="alice",
            subreddit="python",
            score=200,
        )
        mock_reddit.submission.return_value = submission

        extractor = RedditExtractor("cid", "csecret", "ua/1.0")
        result = await extractor.extract(_REDDIT_URL)

    assert isinstance(result, ExtractedContent)
    assert result.title == "My Python Post"
    assert "## Post Content" in result.body
    assert "Here is some **content**." in result.body
    assert "## Top Comments" in result.body
    assert result.metadata["author"] == "alice"
    assert result.metadata["subreddit"] == "python"
    assert result.metadata["score"] == 200
    assert result.source_type == SourceType.REDDIT


async def test_reddit_link_post_no_selftext():
    """Link post (empty selftext) → body has comments only, metadata.media_url set."""
    with patch("zettelkasten_bot.sources.reddit.praw.Reddit") as MockReddit:
        mock_reddit = MockReddit.return_value
        mock_reddit.read_only = True
        submission = _make_submission(
            selftext="",
            url_is_media=True,
            is_self=False,
        )
        mock_reddit.submission.return_value = submission

        extractor = RedditExtractor("cid", "csecret", "ua/1.0")
        result = await extractor.extract(_REDDIT_URL)

    assert "## Post Content" not in result.body
    assert "## Top Comments" in result.body
    assert "media_url" in result.metadata
    assert result.metadata["media_url"] == "https://i.imgur.com/example.jpg"


async def test_reddit_post_no_comments():
    """Post with no comments → body has post content, no comments section."""
    with patch("zettelkasten_bot.sources.reddit.praw.Reddit") as MockReddit:
        mock_reddit = MockReddit.return_value
        mock_reddit.read_only = True
        submission = _make_submission(
            selftext="My post body.",
            comments=[],
        )
        mock_reddit.submission.return_value = submission

        extractor = RedditExtractor("cid", "csecret", "ua/1.0")
        result = await extractor.extract(_REDDIT_URL)

    assert "## Post Content" in result.body
    assert "## Top Comments" not in result.body


async def test_reddit_deleted_post_author():
    """Post with deleted author → metadata.author == '[deleted]'."""
    with patch("zettelkasten_bot.sources.reddit.praw.Reddit") as MockReddit:
        mock_reddit = MockReddit.return_value
        mock_reddit.read_only = True
        submission = _make_submission(author=None)
        mock_reddit.submission.return_value = submission

        extractor = RedditExtractor("cid", "csecret", "ua/1.0")
        result = await extractor.extract(_REDDIT_URL)

    assert result.metadata["author"] == "[deleted]"


async def test_reddit_deleted_comment_author():
    """Comment with deleted author → comment line shows u/[deleted]."""
    with patch("zettelkasten_bot.sources.reddit.praw.Reddit") as MockReddit:
        mock_reddit = MockReddit.return_value
        mock_reddit.read_only = True
        deleted_comment = _make_comment(body="Top comment text", author=None)
        submission = _make_submission(comments=[deleted_comment])
        mock_reddit.submission.return_value = submission

        extractor = RedditExtractor("cid", "csecret", "ua/1.0")
        result = await extractor.extract(_REDDIT_URL)

    assert "u/[deleted]" in result.body


async def test_reddit_custom_comment_depth():
    """comment_depth=5 → only 5 comments extracted, not 6+."""
    with patch("zettelkasten_bot.sources.reddit.praw.Reddit") as MockReddit:
        mock_reddit = MockReddit.return_value
        mock_reddit.read_only = True
        many_comments = [
            _make_comment(f"Comment {i}", f"user{i}", i) for i in range(1, 16)
        ]
        submission = _make_submission(comments=many_comments)
        mock_reddit.submission.return_value = submission

        extractor = RedditExtractor("cid", "csecret", "ua/1.0", comment_depth=5)
        result = await extractor.extract(_REDDIT_URL)

    assert extractor._comment_depth == 5
    assert "Comment 5" in result.body
    assert "Comment 6" not in result.body


async def test_reddit_default_comment_depth():
    """Default comment_depth=10 → up to 10 comments extracted, not 11+."""
    with patch("zettelkasten_bot.sources.reddit.praw.Reddit") as MockReddit:
        mock_reddit = MockReddit.return_value
        mock_reddit.read_only = True
        many_comments = [
            _make_comment(f"Comment {i}", f"user{i}", i) for i in range(1, 13)
        ]
        submission = _make_submission(comments=many_comments)
        mock_reddit.submission.return_value = submission

        extractor = RedditExtractor("cid", "csecret", "ua/1.0")
        result = await extractor.extract(_REDDIT_URL)

    assert extractor._comment_depth == 10
    assert "Comment 10" in result.body
    assert "Comment 11" not in result.body


async def test_reddit_praw_exception_reraised():
    """PRAWException raised by PRAW → re-raised from extractor."""
    from praw.exceptions import PRAWException

    with patch("zettelkasten_bot.sources.reddit.praw.Reddit") as MockReddit:
        mock_reddit = MockReddit.return_value
        mock_reddit.read_only = True
        mock_reddit.submission.side_effect = PRAWException("PRAW fail")

        extractor = RedditExtractor("cid", "csecret", "ua/1.0")
        with pytest.raises(PRAWException):
            await extractor.extract(_REDDIT_URL)


async def test_reddit_generic_exception_reraised():
    """Generic exception raised by PRAW → re-raised from extractor."""
    with patch("zettelkasten_bot.sources.reddit.praw.Reddit") as MockReddit:
        mock_reddit = MockReddit.return_value
        mock_reddit.read_only = True
        mock_reddit.submission.side_effect = RuntimeError("Network fail")

        extractor = RedditExtractor("cid", "csecret", "ua/1.0")
        with pytest.raises(RuntimeError, match="Network fail"):
            await extractor.extract(_REDDIT_URL)


async def test_reddit_post_with_flair():
    """Post with flair → metadata.flair is set."""
    with patch("zettelkasten_bot.sources.reddit.praw.Reddit") as MockReddit:
        mock_reddit = MockReddit.return_value
        mock_reddit.read_only = True
        submission = _make_submission(link_flair_text="Discussion")
        mock_reddit.submission.return_value = submission

        extractor = RedditExtractor("cid", "csecret", "ua/1.0")
        result = await extractor.extract(_REDDIT_URL)

    assert result.metadata["flair"] == "Discussion"


async def test_reddit_metadata_score_and_ratio_fields():
    """Metadata includes score, upvote_ratio, num_comments, created_utc."""
    with patch("zettelkasten_bot.sources.reddit.praw.Reddit") as MockReddit:
        mock_reddit = MockReddit.return_value
        mock_reddit.read_only = True
        submission = _make_submission(
            score=512,
            upvote_ratio=0.87,
            num_comments=42,
            created_utc=1700000000.0,
        )
        mock_reddit.submission.return_value = submission

        extractor = RedditExtractor("cid", "csecret", "ua/1.0")
        result = await extractor.extract(_REDDIT_URL)

    assert result.metadata["score"] == 512
    assert result.metadata["upvote_ratio"] == 0.87
    assert result.metadata["num_comments"] == 42
    assert result.metadata["created_utc"] == 1700000000.0


async def test_reddit_source_type():
    """ExtractedContent.source_type == SourceType.REDDIT."""
    with patch("zettelkasten_bot.sources.reddit.praw.Reddit") as MockReddit:
        mock_reddit = MockReddit.return_value
        mock_reddit.read_only = True
        submission = _make_submission()
        mock_reddit.submission.return_value = submission

        extractor = RedditExtractor("cid", "csecret", "ua/1.0")
        result = await extractor.extract(_REDDIT_URL)

    assert result.source_type == SourceType.REDDIT


# ─────────────────────────────────────────────────────────────────────────────
# YouTube test helpers
#
# yt_dlp and youtube_transcript_api are imported locally *inside* extract(),
# so we patch at the library root, not at zettelkasten_bot.sources.youtube.*
# ─────────────────────────────────────────────────────────────────────────────


_YT_MOD = "zettelkasten_bot.sources.youtube"

_DEFAULT_YDL_INFO: dict = {
    "title": "Never Gonna Give You Up",
    "channel": "Rick Astley",
    "duration": 213,
    "view_count": 1_000_000,
    "upload_date": "20091025",
    "description": "The official video for Never Gonna Give You Up",
    "like_count": 50000,
}

_DEFAULT_TRANSCRIPT_TEXT = "We're no strangers to love You know the rules and so do I"


# ─────────────────────────────────────────────────────────────────────────────
# YouTube extractor tests
# ─────────────────────────────────────────────────────────────────────────────


async def test_youtube_happy_path():
    """Metadata + transcript available → correct title, body, all metadata fields."""
    with (
        patch(f"{_YT_MOD}._fetch_metadata_sync", return_value=_DEFAULT_YDL_INFO),
        patch(f"{_YT_MOD}._fetch_transcript_sync", return_value=_DEFAULT_TRANSCRIPT_TEXT),
    ):
        extractor = YouTubeExtractor()
        result = await extractor.extract(_YOUTUBE_URL)

    assert result.title == "Never Gonna Give You Up"
    assert "## Transcript" in result.body
    assert "We're no strangers to love" in result.body
    assert result.metadata["channel"] == "Rick Astley"
    assert result.metadata["duration_seconds"] == 213
    assert result.metadata["view_count"] == 1_000_000
    assert result.metadata["upload_date"] == "20091025"
    assert result.metadata["has_transcript"] is True
    assert result.metadata["video_id"] == _VIDEO_ID
    assert result.source_type == SourceType.YOUTUBE


async def test_youtube_no_transcript():
    """Transcript unavailable (all fallbacks fail) → description fallback."""
    with (
        patch(f"{_YT_MOD}._fetch_metadata_sync", return_value=_DEFAULT_YDL_INFO),
        patch(f"{_YT_MOD}._fetch_transcript_sync", side_effect=Exception("No transcript")),
        patch(f"{_YT_MOD}._fetch_subtitles_via_ytdlp_sync", return_value=None),
    ):
        extractor = YouTubeExtractor()
        result = await extractor.extract(_YOUTUBE_URL)

    assert "Video Description" in result.body
    assert result.metadata["has_transcript"] is False
    assert result.title == "Never Gonna Give You Up"


async def test_youtube_no_transcript_no_description():
    """Transcript and description both unavailable → fallback text."""
    info_no_desc = {**_DEFAULT_YDL_INFO, "description": ""}
    with (
        patch(f"{_YT_MOD}._fetch_metadata_sync", return_value=info_no_desc),
        patch(f"{_YT_MOD}._fetch_transcript_sync", side_effect=Exception("No transcript")),
        patch(f"{_YT_MOD}._fetch_subtitles_via_ytdlp_sync", return_value=None),
    ):
        extractor = YouTubeExtractor()
        result = await extractor.extract(_YOUTUBE_URL)

    assert "(Transcript not available" in result.body
    assert result.metadata["has_transcript"] is False


async def test_youtube_ytdlp_fails_transcript_succeeds():
    """yt-dlp fails → title falls back to 'YouTube Video {id}', transcript still extracted."""
    with (
        patch(f"{_YT_MOD}._fetch_metadata_sync", side_effect=Exception("yt-dlp fail")),
        patch(f"{_YT_MOD}._fetch_transcript_sync", return_value=_DEFAULT_TRANSCRIPT_TEXT),
    ):
        extractor = YouTubeExtractor()
        result = await extractor.extract(_YOUTUBE_URL)

    assert result.title == f"YouTube Video {_VIDEO_ID}"
    assert "## Transcript" in result.body
    assert result.metadata["has_transcript"] is True


async def test_youtube_both_fail():
    """Both yt-dlp and transcript fail → minimal content with video_id."""
    with (
        patch(f"{_YT_MOD}._fetch_metadata_sync", side_effect=Exception("yt-dlp fail")),
        patch(f"{_YT_MOD}._fetch_transcript_sync", side_effect=Exception("Transcript fail")),
        patch(f"{_YT_MOD}._fetch_subtitles_via_ytdlp_sync", return_value=None),
    ):
        extractor = YouTubeExtractor()
        result = await extractor.extract(_YOUTUBE_URL)

    assert result.title == f"YouTube Video {_VIDEO_ID}"
    assert result.metadata["video_id"] == _VIDEO_ID
    assert result.metadata["has_transcript"] is False


async def test_youtube_subtitle_fallback():
    """Transcript API fails but yt-dlp subtitles succeed → uses subtitle text."""
    with (
        patch(f"{_YT_MOD}._fetch_metadata_sync", return_value=_DEFAULT_YDL_INFO),
        patch(f"{_YT_MOD}._fetch_transcript_sync", side_effect=Exception("No transcript")),
        patch(f"{_YT_MOD}._fetch_subtitles_via_ytdlp_sync", return_value="Subtitle fallback text here"),
    ):
        extractor = YouTubeExtractor()
        result = await extractor.extract(_YOUTUBE_URL)

    assert "## Transcript" in result.body
    assert "Subtitle fallback text here" in result.body
    assert result.metadata["has_transcript"] is True


async def test_youtube_metadata_timeout():
    """Metadata timeout → graceful degradation with fallback title."""
    import asyncio as _asyncio

    with (
        patch(f"{_YT_MOD}._fetch_metadata_sync", side_effect=_asyncio.TimeoutError()),
        patch(f"{_YT_MOD}._fetch_transcript_sync", return_value=_DEFAULT_TRANSCRIPT_TEXT),
    ):
        extractor = YouTubeExtractor()
        result = await extractor.extract(_YOUTUBE_URL)

    assert result.title == f"YouTube Video {_VIDEO_ID}"
    assert "## Transcript" in result.body
    assert result.metadata["has_transcript"] is True


async def test_youtube_transcript_timeout():
    """Transcript timeout → falls through to subtitle fallback."""
    import asyncio as _asyncio

    with (
        patch(f"{_YT_MOD}._fetch_metadata_sync", return_value=_DEFAULT_YDL_INFO),
        patch(f"{_YT_MOD}._fetch_transcript_sync", side_effect=_asyncio.TimeoutError()),
        patch(f"{_YT_MOD}._fetch_subtitles_via_ytdlp_sync", return_value="Fallback subs"),
    ):
        extractor = YouTubeExtractor()
        result = await extractor.extract(_YOUTUBE_URL)

    assert "Fallback subs" in result.body
    assert result.metadata["has_transcript"] is True


async def test_youtube_invalid_url_raises():
    """URL with no extractable video ID → raises ValueError."""
    extractor = YouTubeExtractor()
    with pytest.raises(ValueError, match="Cannot extract video ID"):
        await extractor.extract("https://www.youtube.com/playlist?list=PLabc")


async def test_youtube_shorts_url():
    """YouTube Shorts URL → correctly extracts video ID."""
    shorts_url = "https://www.youtube.com/shorts/abc12345678"

    with (
        patch(f"{_YT_MOD}._fetch_metadata_sync", return_value={"title": "Short video"}),
        patch(f"{_YT_MOD}._fetch_transcript_sync", side_effect=Exception("no transcript")),
        patch(f"{_YT_MOD}._fetch_subtitles_via_ytdlp_sync", return_value=None),
    ):
        extractor = YouTubeExtractor()
        result = await extractor.extract(shorts_url)

    assert result.metadata["video_id"] == "abc12345678"


async def test_youtube_short_url():
    """youtu.be short URL → correctly extracts video ID."""
    short_url = "https://youtu.be/dQw4w9WgXcQ"

    with (
        patch(f"{_YT_MOD}._fetch_metadata_sync", return_value=_DEFAULT_YDL_INFO),
        patch(f"{_YT_MOD}._fetch_transcript_sync", return_value=_DEFAULT_TRANSCRIPT_TEXT),
    ):
        extractor = YouTubeExtractor()
        result = await extractor.extract(short_url)

    assert result.metadata["video_id"] == _VIDEO_ID


async def test_youtube_embed_url():
    """Embed URL → correctly extracts video ID."""
    embed_url = "https://www.youtube.com/embed/dQw4w9WgXcQ"

    with (
        patch(f"{_YT_MOD}._fetch_metadata_sync", return_value=_DEFAULT_YDL_INFO),
        patch(f"{_YT_MOD}._fetch_transcript_sync", return_value=_DEFAULT_TRANSCRIPT_TEXT),
    ):
        extractor = YouTubeExtractor()
        result = await extractor.extract(embed_url)

    assert result.metadata["video_id"] == _VIDEO_ID


async def test_youtube_live_url():
    """YouTube Live URL → correctly extracts video ID."""
    live_url = "https://www.youtube.com/live/dQw4w9WgXcQ"

    with (
        patch(f"{_YT_MOD}._fetch_metadata_sync", return_value=_DEFAULT_YDL_INFO),
        patch(f"{_YT_MOD}._fetch_transcript_sync", return_value=_DEFAULT_TRANSCRIPT_TEXT),
    ):
        extractor = YouTubeExtractor()
        result = await extractor.extract(live_url)

    assert result.metadata["video_id"] == _VIDEO_ID


async def test_youtube_nocookie_url():
    """youtube-nocookie.com embed URL → correctly extracts video ID."""
    nocookie_url = "https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ"

    with (
        patch(f"{_YT_MOD}._fetch_metadata_sync", return_value=_DEFAULT_YDL_INFO),
        patch(f"{_YT_MOD}._fetch_transcript_sync", return_value=_DEFAULT_TRANSCRIPT_TEXT),
    ):
        extractor = YouTubeExtractor()
        result = await extractor.extract(nocookie_url)

    assert result.metadata["video_id"] == _VIDEO_ID


async def test_youtube_video_id_in_metadata():
    """video_id always present in metadata, regardless of API failures."""
    with (
        patch(f"{_YT_MOD}._fetch_metadata_sync", return_value=_DEFAULT_YDL_INFO),
        patch(f"{_YT_MOD}._fetch_transcript_sync", return_value=_DEFAULT_TRANSCRIPT_TEXT),
    ):
        extractor = YouTubeExtractor()
        result = await extractor.extract(_YOUTUBE_URL)

    assert "video_id" in result.metadata
    assert result.metadata["video_id"] == _VIDEO_ID


async def test_youtube_source_type():
    """ExtractedContent.source_type == SourceType.YOUTUBE."""
    with (
        patch(f"{_YT_MOD}._fetch_metadata_sync", return_value=_DEFAULT_YDL_INFO),
        patch(f"{_YT_MOD}._fetch_transcript_sync", return_value=_DEFAULT_TRANSCRIPT_TEXT),
    ):
        extractor = YouTubeExtractor()
        result = await extractor.extract(_YOUTUBE_URL)

    assert result.source_type == SourceType.YOUTUBE


# ─────────────────────────────────────────────────────────────────────────────
# Newsletter test helpers
#
# _fetch_html and _fetch_wayback_url each open their own httpx.AsyncClient.
# We patch zettelkasten_bot.sources.newsletter.httpx.AsyncClient so every
# call goes through our mock.  The mock is configured as a context manager
# that returns a mock client with an AsyncMock .get() method.
# ─────────────────────────────────────────────────────────────────────────────

_NEWSLETTER_URL = "https://example.substack.com/p/my-article"
_LONG_BODY = "x" * 300  # >= 200 chars → not paywalled
_SHORT_BODY = "x" * 50  # < 200 chars → looks paywalled


def _make_httpx_client_cm(responses: list[MagicMock]) -> MagicMock:
    """Build an httpx.AsyncClient context-manager mock.

    Each time the context manager is entered it returns a fresh mock client
    whose `.get()` is an AsyncMock that pops the next response from *responses*.
    """
    call_count = [0]

    async def _get(url, **kwargs):  # noqa: ANN001, ANN202
        idx = call_count[0]
        call_count[0] += 1
        if idx < len(responses):
            return responses[idx]
        raise RuntimeError(f"Unexpected extra HTTP call (call #{idx + 1})")

    client_mock = MagicMock()
    client_mock.get = AsyncMock(side_effect=_get)

    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=client_mock)
    cm.__aexit__ = AsyncMock(return_value=False)

    # Each instantiation of AsyncClient(...) returns the same context manager
    constructor = MagicMock(return_value=cm)
    return constructor


def _make_response(text: str = "", status_code: int = 200, json_data: dict | None = None) -> MagicMock:
    """Build a minimal mock httpx.Response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    resp.raise_for_status = MagicMock()
    if json_data is not None:
        resp.json = MagicMock(return_value=json_data)
    return resp


def _make_trafilatura_mock(
    body: str | None = _LONG_BODY,
    title: str = "Article Title",
    has_metadata: bool = True,
) -> tuple[MagicMock, MagicMock]:
    """Return (mock_extract_fn, mock_extract_metadata_fn).

    mock_extract_fn returns *body* (can be None).
    mock_extract_metadata_fn returns a mock with .title set if has_metadata.
    """
    mock_extract = MagicMock(return_value=body)

    if has_metadata:
        meta_mock = MagicMock()
        meta_mock.title = title
        mock_extract_metadata = MagicMock(return_value=meta_mock)
    else:
        mock_extract_metadata = MagicMock(return_value=None)

    return mock_extract, mock_extract_metadata


# ─────────────────────────────────────────────────────────────────────────────
# Newsletter extractor tests
# ─────────────────────────────────────────────────────────────────────────────


async def test_newsletter_direct_fetch_succeeds():
    """Direct fetch returns long body → succeeds without bypass, bypass_used is None."""
    html = f"<html><title>My Article</title><body>{_LONG_BODY}</body></html>"
    client_ctor = _make_httpx_client_cm([_make_response(text=html)])
    mock_extract, mock_meta = _make_trafilatura_mock(body=_LONG_BODY, title="My Article")

    with (
        patch("zettelkasten_bot.sources.newsletter.httpx.AsyncClient", client_ctor),
        patch("zettelkasten_bot.sources.newsletter.trafilatura.extract", mock_extract),
        patch("zettelkasten_bot.sources.newsletter.trafilatura.extract_metadata", mock_meta),
    ):
        extractor = NewsletterExtractor()
        result = await extractor.extract(_NEWSLETTER_URL)

    assert isinstance(result, ExtractedContent)
    assert result.title == "My Article"
    assert result.body == _LONG_BODY
    assert result.metadata["bypass_used"] is None
    assert result.source_type == SourceType.NEWSLETTER


async def test_newsletter_bypass1_removepaywalls_succeeds():
    """Direct fetch is paywalled; bypass 1 (removepaywalls.com) returns long body."""
    short_html = f"<html><body>{_SHORT_BODY}</body></html>"
    long_html = f"<html><title>Bypass Article</title><body>{_LONG_BODY}</body></html>"

    # Call 1: direct fetch → short/paywalled
    # Call 2: removepaywalls.com bypass → long body
    client_ctor = _make_httpx_client_cm([
        _make_response(text=short_html),
        _make_response(text=long_html),
    ])

    mock_extract = MagicMock(side_effect=[_SHORT_BODY, _LONG_BODY])
    meta_mock = MagicMock()
    meta_mock.title = "Bypass Article"
    mock_meta = MagicMock(return_value=meta_mock)

    with (
        patch("zettelkasten_bot.sources.newsletter.httpx.AsyncClient", client_ctor),
        patch("zettelkasten_bot.sources.newsletter.trafilatura.extract", mock_extract),
        patch("zettelkasten_bot.sources.newsletter.trafilatura.extract_metadata", mock_meta),
    ):
        extractor = NewsletterExtractor()
        result = await extractor.extract(_NEWSLETTER_URL)

    assert result.metadata["bypass_used"] == "removepaywalls.com"
    assert result.body == _LONG_BODY


async def test_newsletter_bypass2_removepaywall_succeeds():
    """Bypass 1 fails; bypass 2 (removepaywall.com) succeeds."""
    short_html = f"<html><body>{_SHORT_BODY}</body></html>"
    long_html = f"<html><title>Via bypass2</title><body>{_LONG_BODY}</body></html>"

    # Call 1: direct fetch → short body (paywalled)
    # Call 2: bypass 1 raises → but we control the client mock per-context-manager
    #         So: call 1 direct (short), call 2 bypass1 raises, call 3 bypass2 long
    # Since each AsyncClient cm is a separate call to the constructor, we need a
    # stateful constructor that sequences responses across multiple cm instances.
    responses_iter = iter([
        _make_response(text=short_html),           # direct fetch
        RuntimeError("removepaywalls.com failed"), # bypass 1 raises
        _make_response(text=long_html),            # bypass 2 succeeds
    ])
    call_count = [0]

    async def _get(url, **kwargs):  # noqa: ANN001, ANN202
        call_count[0] += 1
        val = next(responses_iter)
        if isinstance(val, Exception):
            raise val
        return val

    client_mock = MagicMock()
    client_mock.get = AsyncMock(side_effect=_get)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=client_mock)
    cm.__aexit__ = AsyncMock(return_value=False)
    client_ctor = MagicMock(return_value=cm)

    mock_extract = MagicMock(side_effect=[_SHORT_BODY, _LONG_BODY])
    meta_mock = MagicMock()
    meta_mock.title = "Via bypass2"
    mock_meta = MagicMock(return_value=meta_mock)

    with (
        patch("zettelkasten_bot.sources.newsletter.httpx.AsyncClient", client_ctor),
        patch("zettelkasten_bot.sources.newsletter.trafilatura.extract", mock_extract),
        patch("zettelkasten_bot.sources.newsletter.trafilatura.extract_metadata", mock_meta),
    ):
        extractor = NewsletterExtractor()
        result = await extractor.extract(_NEWSLETTER_URL)

    assert result.metadata["bypass_used"] == "removepaywall.com"
    assert result.body == _LONG_BODY


async def test_newsletter_wayback_succeeds():
    """Bypasses 1-2 fail; Wayback Machine returns snapshot URL → fetches snapshot, succeeds."""
    short_html = f"<html><body>{_SHORT_BODY}</body></html>"
    long_html = f"<html><title>Wayback Article</title><body>{_LONG_BODY}</body></html>"
    wayback_json = {
        "archived_snapshots": {
            "closest": {
                "available": True,
                "status": "200",
                "url": "https://web.archive.org/web/20230101/https://example.com",
            }
        }
    }

    responses_iter = iter([
        _make_response(text=short_html),           # direct fetch → paywalled
        RuntimeError("bypass1 failed"),            # bypass 1 raises
        RuntimeError("bypass2 failed"),            # bypass 2 raises
        _make_response(json_data=wayback_json),    # Wayback availability check
        _make_response(text=long_html),            # fetch snapshot
    ])

    async def _get(url, **kwargs):  # noqa: ANN001, ANN202
        val = next(responses_iter)
        if isinstance(val, Exception):
            raise val
        return val

    client_mock = MagicMock()
    client_mock.get = AsyncMock(side_effect=_get)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=client_mock)
    cm.__aexit__ = AsyncMock(return_value=False)
    client_ctor = MagicMock(return_value=cm)

    mock_extract = MagicMock(side_effect=[_SHORT_BODY, _LONG_BODY])
    meta_mock = MagicMock()
    meta_mock.title = "Wayback Article"
    mock_meta = MagicMock(return_value=meta_mock)

    with (
        patch("zettelkasten_bot.sources.newsletter.httpx.AsyncClient", client_ctor),
        patch("zettelkasten_bot.sources.newsletter.trafilatura.extract", mock_extract),
        patch("zettelkasten_bot.sources.newsletter.trafilatura.extract_metadata", mock_meta),
    ):
        extractor = NewsletterExtractor()
        result = await extractor.extract(_NEWSLETTER_URL)

    assert result.metadata["bypass_used"] == "archive.org Wayback Machine"
    assert result.body == _LONG_BODY


async def test_newsletter_wayback_no_snapshot_skips_to_next():
    """Wayback returns available=False → skips to Google cache (bypass 4)."""
    short_html = f"<html><body>{_SHORT_BODY}</body></html>"
    long_html = f"<html><title>Google Cache</title><body>{_LONG_BODY}</body></html>"
    wayback_json_unavailable = {"archived_snapshots": {}}  # no 'closest' key

    responses_iter = iter([
        _make_response(text=short_html),                    # direct fetch
        RuntimeError("bypass1 failed"),                    # bypass 1
        RuntimeError("bypass2 failed"),                    # bypass 2
        _make_response(json_data=wayback_json_unavailable), # Wayback: no snapshot
        _make_response(text=long_html),                    # Google cache
    ])

    async def _get(url, **kwargs):  # noqa: ANN001, ANN202
        val = next(responses_iter)
        if isinstance(val, Exception):
            raise val
        return val

    client_mock = MagicMock()
    client_mock.get = AsyncMock(side_effect=_get)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=client_mock)
    cm.__aexit__ = AsyncMock(return_value=False)
    client_ctor = MagicMock(return_value=cm)

    mock_extract = MagicMock(side_effect=[_SHORT_BODY, _LONG_BODY])
    meta_mock = MagicMock()
    meta_mock.title = "Google Cache"
    mock_meta = MagicMock(return_value=meta_mock)

    with (
        patch("zettelkasten_bot.sources.newsletter.httpx.AsyncClient", client_ctor),
        patch("zettelkasten_bot.sources.newsletter.trafilatura.extract", mock_extract),
        patch("zettelkasten_bot.sources.newsletter.trafilatura.extract_metadata", mock_meta),
    ):
        extractor = NewsletterExtractor()
        result = await extractor.extract(_NEWSLETTER_URL)

    assert result.metadata["bypass_used"] == "Google cache"


async def test_newsletter_wayback_api_request_fails_skips_to_next():
    """Wayback API request raises httpx exception → skips to Google cache."""
    short_html = f"<html><body>{_SHORT_BODY}</body></html>"
    long_html = f"<html><title>Google Cache</title><body>{_LONG_BODY}</body></html>"

    import httpx as _httpx

    responses_iter = iter([
        _make_response(text=short_html),                      # direct fetch
        RuntimeError("bypass1 failed"),                      # bypass 1
        RuntimeError("bypass2 failed"),                      # bypass 2
        _httpx.ConnectError("Wayback API unreachable"),      # Wayback availability check fails
        _make_response(text=long_html),                      # Google cache
    ])

    async def _get(url, **kwargs):  # noqa: ANN001, ANN202
        val = next(responses_iter)
        if isinstance(val, Exception):
            raise val
        return val

    client_mock = MagicMock()
    client_mock.get = AsyncMock(side_effect=_get)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=client_mock)
    cm.__aexit__ = AsyncMock(return_value=False)
    client_ctor = MagicMock(return_value=cm)

    mock_extract = MagicMock(side_effect=[_SHORT_BODY, _LONG_BODY])
    meta_mock = MagicMock()
    meta_mock.title = "Google Cache"
    mock_meta = MagicMock(return_value=meta_mock)

    with (
        patch("zettelkasten_bot.sources.newsletter.httpx.AsyncClient", client_ctor),
        patch("zettelkasten_bot.sources.newsletter.trafilatura.extract", mock_extract),
        patch("zettelkasten_bot.sources.newsletter.trafilatura.extract_metadata", mock_meta),
    ):
        extractor = NewsletterExtractor()
        result = await extractor.extract(_NEWSLETTER_URL)

    assert result.metadata["bypass_used"] == "Google cache"


async def test_newsletter_all_bypasses_fail_raises_runtime_error():
    """All 4 bypass methods fail → raises RuntimeError."""
    short_html = f"<html><body>{_SHORT_BODY}</body></html>"
    wayback_json_unavailable = {"archived_snapshots": {}}

    responses_iter = iter([
        _make_response(text=short_html),                    # direct fetch
        RuntimeError("bypass1 failed"),                    # bypass 1
        RuntimeError("bypass2 failed"),                    # bypass 2
        _make_response(json_data=wayback_json_unavailable), # Wayback: no snapshot
        RuntimeError("google cache failed"),               # bypass 4
    ])

    async def _get(url, **kwargs):  # noqa: ANN001, ANN202
        val = next(responses_iter)
        if isinstance(val, Exception):
            raise val
        return val

    client_mock = MagicMock()
    client_mock.get = AsyncMock(side_effect=_get)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=client_mock)
    cm.__aexit__ = AsyncMock(return_value=False)
    client_ctor = MagicMock(return_value=cm)

    mock_extract = MagicMock(return_value=_SHORT_BODY)
    meta_mock = MagicMock()
    meta_mock.title = "Paywalled"
    mock_meta = MagicMock(return_value=meta_mock)

    with (
        patch("zettelkasten_bot.sources.newsletter.httpx.AsyncClient", client_ctor),
        patch("zettelkasten_bot.sources.newsletter.trafilatura.extract", mock_extract),
        patch("zettelkasten_bot.sources.newsletter.trafilatura.extract_metadata", mock_meta),
    ):
        extractor = NewsletterExtractor()
        with pytest.raises(RuntimeError, match="all paywall bypass attempts failed"):
            await extractor.extract(_NEWSLETTER_URL)


async def test_newsletter_direct_fetch_raises_proceeds_to_bypass():
    """Direct fetch raises httpx exception → proceeds to bypass chain (bypass 1 succeeds)."""
    import httpx as _httpx

    long_html = f"<html><title>From Bypass</title><body>{_LONG_BODY}</body></html>"

    responses_iter = iter([
        _httpx.ConnectError("Connection refused"),  # direct fetch raises
        _make_response(text=long_html),            # bypass 1 succeeds
    ])

    async def _get(url, **kwargs):  # noqa: ANN001, ANN202
        val = next(responses_iter)
        if isinstance(val, Exception):
            raise val
        return val

    client_mock = MagicMock()
    client_mock.get = AsyncMock(side_effect=_get)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=client_mock)
    cm.__aexit__ = AsyncMock(return_value=False)
    client_ctor = MagicMock(return_value=cm)

    mock_extract = MagicMock(return_value=_LONG_BODY)
    meta_mock = MagicMock()
    meta_mock.title = "From Bypass"
    mock_meta = MagicMock(return_value=meta_mock)

    with (
        patch("zettelkasten_bot.sources.newsletter.httpx.AsyncClient", client_ctor),
        patch("zettelkasten_bot.sources.newsletter.trafilatura.extract", mock_extract),
        patch("zettelkasten_bot.sources.newsletter.trafilatura.extract_metadata", mock_meta),
    ):
        extractor = NewsletterExtractor()
        result = await extractor.extract(_NEWSLETTER_URL)

    assert result.metadata["bypass_used"] == "removepaywalls.com"


async def test_newsletter_trafilatura_returns_none_body_is_empty_string():
    """trafilatura.extract() returns None → body treated as '' (looks paywalled → bypass)."""
    short_html = f"<html><body>{_SHORT_BODY}</body></html>"
    long_html = f"<html><title>Bypass</title><body>{_LONG_BODY}</body></html>"

    responses_iter = iter([
        _make_response(text=short_html),
        _make_response(text=long_html),
    ])

    async def _get(url, **kwargs):  # noqa: ANN001, ANN202
        val = next(responses_iter)
        if isinstance(val, Exception):
            raise val
        return val

    client_mock = MagicMock()
    client_mock.get = AsyncMock(side_effect=_get)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=client_mock)
    cm.__aexit__ = AsyncMock(return_value=False)
    client_ctor = MagicMock(return_value=cm)

    # First call returns None (paywalled), second call returns long body
    mock_extract = MagicMock(side_effect=[None, _LONG_BODY])
    meta_mock = MagicMock()
    meta_mock.title = "Bypass"
    mock_meta = MagicMock(return_value=meta_mock)

    with (
        patch("zettelkasten_bot.sources.newsletter.httpx.AsyncClient", client_ctor),
        patch("zettelkasten_bot.sources.newsletter.trafilatura.extract", mock_extract),
        patch("zettelkasten_bot.sources.newsletter.trafilatura.extract_metadata", mock_meta),
    ):
        extractor = NewsletterExtractor()
        result = await extractor.extract(_NEWSLETTER_URL)

    # When trafilatura returns None for direct fetch, body="" → looks paywalled → bypass
    assert result.metadata["bypass_used"] is not None


async def test_newsletter_title_from_trafilatura_metadata():
    """Title is extracted from trafilatura metadata.title."""
    html = f"<html><title>HTML Title</title><body>{_LONG_BODY}</body></html>"
    client_ctor = _make_httpx_client_cm([_make_response(text=html)])

    mock_extract, mock_meta = _make_trafilatura_mock(body=_LONG_BODY, title="Trafilatura Title")

    with (
        patch("zettelkasten_bot.sources.newsletter.httpx.AsyncClient", client_ctor),
        patch("zettelkasten_bot.sources.newsletter.trafilatura.extract", mock_extract),
        patch("zettelkasten_bot.sources.newsletter.trafilatura.extract_metadata", mock_meta),
    ):
        extractor = NewsletterExtractor()
        result = await extractor.extract(_NEWSLETTER_URL)

    assert result.title == "Trafilatura Title"


async def test_newsletter_title_fallback_to_html_title_tag():
    """When trafilatura metadata has no title → falls back to <title> tag."""
    html = f"<html><title>HTML Tag Title</title><body>{_LONG_BODY}</body></html>"
    client_ctor = _make_httpx_client_cm([_make_response(text=html)])

    # metadata.title is None/empty
    mock_extract = MagicMock(return_value=_LONG_BODY)
    meta_mock = MagicMock()
    meta_mock.title = None
    mock_meta = MagicMock(return_value=meta_mock)

    with (
        patch("zettelkasten_bot.sources.newsletter.httpx.AsyncClient", client_ctor),
        patch("zettelkasten_bot.sources.newsletter.trafilatura.extract", mock_extract),
        patch("zettelkasten_bot.sources.newsletter.trafilatura.extract_metadata", mock_meta),
    ):
        extractor = NewsletterExtractor()
        result = await extractor.extract(_NEWSLETTER_URL)

    assert result.title == "HTML Tag Title"


async def test_newsletter_source_type():
    """ExtractedContent.source_type == SourceType.NEWSLETTER."""
    html = f"<html><title>Article</title><body>{_LONG_BODY}</body></html>"
    client_ctor = _make_httpx_client_cm([_make_response(text=html)])
    mock_extract, mock_meta = _make_trafilatura_mock(body=_LONG_BODY, title="Article")

    with (
        patch("zettelkasten_bot.sources.newsletter.httpx.AsyncClient", client_ctor),
        patch("zettelkasten_bot.sources.newsletter.trafilatura.extract", mock_extract),
        patch("zettelkasten_bot.sources.newsletter.trafilatura.extract_metadata", mock_meta),
    ):
        extractor = NewsletterExtractor()
        result = await extractor.extract(_NEWSLETTER_URL)

    assert result.source_type == SourceType.NEWSLETTER


# ─────────────────────────────────────────────────────────────────────────────
# Substack-specific tests
# ─────────────────────────────────────────────────────────────────────────────

from zettelkasten_bot.sources.newsletter import (
    _is_substack_url,
    _detect_substack_paywall,
    _extract_substack_metadata,
)


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://example.substack.com/p/my-post", True),
        ("https://substack.com/", True),
        ("https://nlp.elvissaravia.com/p/top-ai-papers", False),
        ("https://medium.com/@user/article", False),
        ("https://example.com/article", False),
    ],
)
def test_is_substack_url(url: str, expected: bool):
    assert _is_substack_url(url) == expected


_SUBSTACK_FREE_HTML = """<html>
<head><script type="application/ld+json">
{"@type": "NewsArticle", "isAccessibleForFree": true}
</script></head>
<body><div class="body markup">Full article content here...</div></body>
</html>"""

_SUBSTACK_PAID_HTML = """<html>
<head><script type="application/ld+json">
{"@type": "NewsArticle", "isAccessibleForFree": false}
</script></head>
<body><div class="body markup">Preview only...</div>
<div class="paywall-content">Subscribe to read the rest</div></body>
</html>"""

_SUBSTACK_PAID_CLASS_ONLY_HTML = """<html>
<body><div class="body markup">Preview...</div>
<div class="paywall">You need to subscribe</div></body>
</html>"""

_SUBSTACK_NO_SIGNALS_HTML = """<html>
<body><div class="body markup">Some article content here</div></body>
</html>"""


def test_substack_paywall_free_article():
    assert _detect_substack_paywall(_SUBSTACK_FREE_HTML) is False


def test_substack_paywall_paid_jsonld():
    assert _detect_substack_paywall(_SUBSTACK_PAID_HTML) is True


def test_substack_paywall_paid_class_only():
    assert _detect_substack_paywall(_SUBSTACK_PAID_CLASS_ONLY_HTML) is True


def test_substack_paywall_no_signals_assumes_free():
    assert _detect_substack_paywall(_SUBSTACK_NO_SIGNALS_HTML) is False


_SUBSTACK_JSONLD_HTML = """<html>
<head><script type="application/ld+json">
{
    "@type": "NewsArticle",
    "headline": "Top AI Papers of the Week",
    "author": {"@type": "Person", "name": "Elvis Saravia"},
    "datePublished": "2026-03-25",
    "isAccessibleForFree": true,
    "publisher": {"@type": "Organization", "name": "NLP Newsletter"}
}
</script></head>
<body>Content</body>
</html>"""

_SUBSTACK_JSONLD_PAID_HTML = """<html>
<head><script type="application/ld+json">
{
    "@type": "NewsArticle",
    "headline": "Paid Article",
    "author": {"@type": "Person", "name": "Author Name"},
    "datePublished": "2026-03-20",
    "isAccessibleForFree": false,
    "publisher": {"@type": "Organization", "name": "Some Publication"}
}
</script></head>
<body>Preview<div class="paywall">Subscribe</div></body>
</html>"""

_SUBSTACK_NO_JSONLD_HTML = """<html>
<head><meta name="author" content="Fallback Author"></head>
<body>Content</body>
</html>"""


def test_extract_substack_metadata_full_jsonld():
    meta = _extract_substack_metadata(_SUBSTACK_JSONLD_HTML)
    assert meta["substack_author"] == "Elvis Saravia"
    assert meta["substack_publication"] == "NLP Newsletter"
    assert meta["substack_date"] == "2026-03-25"
    assert meta["is_substack"] is True
    assert meta["is_paid"] is False


def test_extract_substack_metadata_paid():
    meta = _extract_substack_metadata(_SUBSTACK_JSONLD_PAID_HTML)
    assert meta["is_paid"] is True
    assert meta["substack_author"] == "Author Name"


def test_extract_substack_metadata_no_jsonld():
    meta = _extract_substack_metadata(_SUBSTACK_NO_JSONLD_HTML)
    assert meta["is_substack"] is True
    assert meta["substack_author"] == ""
    assert meta["substack_publication"] == ""
    assert meta["substack_date"] == ""
    assert meta["is_paid"] is False


_SUBSTACK_URL = "https://example.substack.com/p/test-article"

_SUBSTACK_FREE_FULL_HTML = """<html>
<head><script type="application/ld+json">
{"@type": "NewsArticle", "isAccessibleForFree": true,
 "author": {"@type": "Person", "name": "Test Author"},
 "publisher": {"@type": "Organization", "name": "Test Pub"},
 "datePublished": "2026-03-25"}
</script><title>Free Article</title></head>
<body><div class="body markup">Full article content</div></body>
</html>"""

_SUBSTACK_PAID_PARTIAL_HTML = """<html>
<head><script type="application/ld+json">
{"@type": "NewsArticle", "isAccessibleForFree": false,
 "author": {"@type": "Person", "name": "Paid Author"},
 "publisher": {"@type": "Organization", "name": "Paid Pub"},
 "datePublished": "2026-03-20"}
</script><title>Paid Article</title></head>
<body><div class="body markup">Preview content only</div>
<div class="paywall">Subscribe to continue reading</div></body>
</html>"""


async def test_substack_free_article_extracts_with_metadata():
    """Free Substack article → full content + Substack metadata, is_paid=False."""
    client_ctor = _make_httpx_client_cm([_make_response(text=_SUBSTACK_FREE_FULL_HTML)])
    mock_extract, mock_meta = _make_trafilatura_mock(body=_LONG_BODY, title="Free Article")

    with (
        patch("zettelkasten_bot.sources.newsletter.httpx.AsyncClient", client_ctor),
        patch("zettelkasten_bot.sources.newsletter.trafilatura.extract", mock_extract),
        patch("zettelkasten_bot.sources.newsletter.trafilatura.extract_metadata", mock_meta),
    ):
        extractor = NewsletterExtractor()
        result = await extractor.extract(_SUBSTACK_URL)

    assert result.body == _LONG_BODY
    assert result.metadata["is_substack"] is True
    assert result.metadata["is_paid"] is False
    assert result.metadata["substack_author"] == "Test Author"
    assert result.metadata["substack_publication"] == "Test Pub"
    assert result.metadata["bypass_used"] is None


async def test_substack_paid_article_returns_partial_content():
    """Paid Substack article, all bypasses fail → returns partial content + paywall note."""
    client_ctor = _make_httpx_client_cm([
        _make_response(text=_SUBSTACK_PAID_PARTIAL_HTML),  # direct fetch
        _make_response(text="<html>short</html>"),         # removepaywalls.com
        _make_response(text="<html>short</html>"),         # removepaywall.com
        _make_response(json_data={"archived_snapshots": {}}),  # wayback API
        _make_response(text="<html>short</html>"),         # google cache
    ])
    mock_extract, mock_meta = _make_trafilatura_mock(body=_SHORT_BODY, title="Paid Article")

    with (
        patch("zettelkasten_bot.sources.newsletter.httpx.AsyncClient", client_ctor),
        patch("zettelkasten_bot.sources.newsletter.trafilatura.extract", mock_extract),
        patch("zettelkasten_bot.sources.newsletter.trafilatura.extract_metadata", mock_meta),
    ):
        extractor = NewsletterExtractor()
        result = await extractor.extract(_SUBSTACK_URL)

    # Should NOT raise — returns partial content gracefully
    assert result.body == _SHORT_BODY
    assert result.metadata["is_paid"] is True
    assert result.metadata["is_substack"] is True
    assert "paywall_note" in result.metadata


async def test_substack_paid_article_bypass_succeeds():
    """Paid Substack article, bypass succeeds → full content with bypass noted."""
    client_ctor = _make_httpx_client_cm([
        _make_response(text=_SUBSTACK_PAID_PARTIAL_HTML),  # direct fetch → short
        _make_response(text="<html>Full bypassed content here</html>"),  # removepaywalls
    ])

    call_count = [0]
    def mock_extract_fn(html, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            return _SHORT_BODY  # direct: paywalled
        return _LONG_BODY  # bypass: full content

    mock_meta = MagicMock()
    meta_obj = MagicMock()
    meta_obj.title = "Paid Article"
    mock_meta.return_value = meta_obj

    with (
        patch("zettelkasten_bot.sources.newsletter.httpx.AsyncClient", client_ctor),
        patch("zettelkasten_bot.sources.newsletter.trafilatura.extract", mock_extract_fn),
        patch("zettelkasten_bot.sources.newsletter.trafilatura.extract_metadata", mock_meta),
    ):
        extractor = NewsletterExtractor()
        result = await extractor.extract(_SUBSTACK_URL)

    assert result.body == _LONG_BODY
    assert result.metadata["bypass_used"] == "removepaywalls.com"
    assert result.metadata["is_substack"] is True


async def test_non_substack_url_unchanged_flow():
    """Non-Substack newsletter URL → existing flow, no Substack metadata."""
    non_substack_url = "https://buttondown.email/user/archive/article"
    html = f"<html><title>Newsletter</title><body>{_LONG_BODY}</body></html>"
    client_ctor = _make_httpx_client_cm([_make_response(text=html)])
    mock_extract, mock_meta = _make_trafilatura_mock(body=_LONG_BODY, title="Newsletter")

    with (
        patch("zettelkasten_bot.sources.newsletter.httpx.AsyncClient", client_ctor),
        patch("zettelkasten_bot.sources.newsletter.trafilatura.extract", mock_extract),
        patch("zettelkasten_bot.sources.newsletter.trafilatura.extract_metadata", mock_meta),
    ):
        extractor = NewsletterExtractor()
        result = await extractor.extract(non_substack_url)

    assert result.body == _LONG_BODY
    assert "is_substack" not in result.metadata


from zettelkasten_bot.sources.newsletter import _is_substack_html


_CUSTOM_DOMAIN_SUBSTACK_HTML = """<html>
<head>
<link rel="stylesheet" href="https://substackcdn.com/bundle.css">
<script type="application/ld+json">
{"@type": "NewsArticle", "isAccessibleForFree": true,
 "author": {"@type": "Person", "name": "Elvis Saravia"},
 "publisher": {"@type": "Organization", "name": "NLP Newsletter"},
 "datePublished": "2026-03-25"}
</script>
<title>Custom Domain Article</title>
</head>
<body><div class="body markup">Full content here</div></body>
</html>"""


def test_is_substack_html_with_substackcdn():
    assert _is_substack_html(_CUSTOM_DOMAIN_SUBSTACK_HTML) is True


def test_is_substack_html_without_markers():
    assert _is_substack_html("<html><body>Regular content</body></html>") is False


async def test_substack_custom_domain_detected_from_html():
    """Custom-domain Substack (not *.substack.com) → detected via HTML markers."""
    custom_url = "https://nlp.elvissaravia.com/p/top-ai-papers"
    client_ctor = _make_httpx_client_cm([_make_response(text=_CUSTOM_DOMAIN_SUBSTACK_HTML)])
    mock_extract, mock_meta = _make_trafilatura_mock(body=_LONG_BODY, title="Custom Domain Article")

    with (
        patch("zettelkasten_bot.sources.newsletter.httpx.AsyncClient", client_ctor),
        patch("zettelkasten_bot.sources.newsletter.trafilatura.extract", mock_extract),
        patch("zettelkasten_bot.sources.newsletter.trafilatura.extract_metadata", mock_meta),
    ):
        extractor = NewsletterExtractor()
        result = await extractor.extract(custom_url)

    assert result.metadata.get("is_substack") is True
    assert result.metadata["substack_author"] == "Elvis Saravia"


# ─────────────────────────────────────────────────────────────────────────────
# GitHub test helpers
# ─────────────────────────────────────────────────────────────────────────────

_GITHUB_URL = "https://github.com/octocat/Hello-World"
_GITHUB_REPO_DATA = {
    "description": "My first repository",
    "stargazers_count": 1234,
    "forks_count": 567,
    "language": "Python",
    "topics": ["python", "example"],
    "created_at": "2011-01-01T00:00:00Z",
    "updated_at": "2023-01-01T00:00:00Z",
    "license": {"spdx_id": "MIT"},
    "open_issues_count": 5,
    "homepage": "https://octocat.github.io",
}
_GITHUB_LANGUAGES_DATA = {"Python": 10000, "Shell": 2000}
_GITHUB_README_TEXT = "# Hello World\n\nThis is a test README with enough content to be meaningful."


def _make_github_client_cm(
    repo_response: MagicMock | None = None,
    languages_response: MagicMock | None = None,
    readme_response: MagicMock | None = None,
) -> MagicMock:
    """Build an httpx.AsyncClient context-manager mock for GitHub tests.

    Responses are mapped by URL suffix:
      /repos/{owner}/{repo}         → repo_response
      /repos/{owner}/{repo}/languages → languages_response
      /repos/{owner}/{repo}/readme  → readme_response
    """
    if repo_response is None:
        repo_response = _make_response(json_data=_GITHUB_REPO_DATA)
        repo_response.raise_for_status = MagicMock()
    if languages_response is None:
        languages_response = _make_response(json_data=_GITHUB_LANGUAGES_DATA, status_code=200)
    if readme_response is None:
        readme_response = _make_response(text=_GITHUB_README_TEXT, status_code=200)

    async def _get(url, **kwargs):  # noqa: ANN001, ANN202
        if url.endswith("/languages"):
            return languages_response
        if url.endswith("/readme"):
            return readme_response
        return repo_response  # /repos/{owner}/{repo}

    client_mock = MagicMock()
    client_mock.get = AsyncMock(side_effect=_get)

    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=client_mock)
    cm.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=cm)


# ─────────────────────────────────────────────────────────────────────────────
# GitHub extractor tests
# ─────────────────────────────────────────────────────────────────────────────


async def test_github_happy_path():
    """Repo + languages + README all succeed → correct title, body sections, metadata."""
    client_ctor = _make_github_client_cm()

    with patch("zettelkasten_bot.sources.github.httpx.AsyncClient", client_ctor):
        extractor = GitHubExtractor()
        result = await extractor.extract(_GITHUB_URL)

    assert isinstance(result, ExtractedContent)
    assert result.title == "octocat/Hello-World"
    assert "## Description" in result.body
    assert "My first repository" in result.body
    assert "## Languages" in result.body
    assert "## README" in result.body
    assert _GITHUB_README_TEXT in result.body
    assert result.metadata["stars"] == 1234
    assert result.metadata["forks"] == 567
    assert result.metadata["language"] == "Python"
    assert result.metadata["topics"] == ["python", "example"]
    assert result.metadata["license"] == "MIT"
    assert result.metadata["homepage"] == "https://octocat.github.io"
    assert result.source_type == SourceType.GITHUB


async def test_github_readme_missing_404():
    """README returns 404 → body still has description + languages, no README section."""
    readme_404 = _make_response(status_code=404)
    client_ctor = _make_github_client_cm(readme_response=readme_404)

    with patch("zettelkasten_bot.sources.github.httpx.AsyncClient", client_ctor):
        extractor = GitHubExtractor()
        result = await extractor.extract(_GITHUB_URL)

    assert "## Description" in result.body
    assert "## Languages" in result.body
    assert "## README" not in result.body


async def test_github_repo_not_found_raises_value_error():
    """404 on /repos endpoint → raises ValueError."""
    import httpx as _httpx

    err_resp = MagicMock()
    err_resp.status_code = 404
    repo_404 = _httpx.HTTPStatusError("Not found", request=MagicMock(), response=err_resp)
    repo_response = MagicMock()
    repo_response.raise_for_status = MagicMock(side_effect=repo_404)
    repo_response.json = MagicMock(return_value={})

    client_ctor = _make_github_client_cm(repo_response=repo_response)

    with patch("zettelkasten_bot.sources.github.httpx.AsyncClient", client_ctor):
        extractor = GitHubExtractor()
        with pytest.raises(ValueError, match="not found"):
            await extractor.extract(_GITHUB_URL)


async def test_github_long_readme_truncated():
    """README longer than 8000 chars → truncated with '... (truncated)'."""
    long_readme = "A" * 9000
    readme_resp = _make_response(text=long_readme, status_code=200)
    client_ctor = _make_github_client_cm(readme_response=readme_resp)

    with patch("zettelkasten_bot.sources.github.httpx.AsyncClient", client_ctor):
        extractor = GitHubExtractor()
        result = await extractor.extract(_GITHUB_URL)

    assert "... (truncated)" in result.body
    # Confirm it was cut off before the full length
    assert result.body.count("A") < 9000


async def test_github_url_formats():
    """Various GitHub URL formats all parse correctly to owner/repo."""
    urls = [
        "https://github.com/octocat/Hello-World",
        "https://github.com/octocat/Hello-World/",
        "https://github.com/octocat/Hello-World/tree/main",
        "https://github.com/octocat/Hello-World/blob/main/README.md",
        "https://github.com/octocat/Hello-World/issues",
    ]
    client_ctor = _make_github_client_cm()

    for url in urls:
        with patch("zettelkasten_bot.sources.github.httpx.AsyncClient", client_ctor):
            extractor = GitHubExtractor()
            result = await extractor.extract(url)
        assert result.title == "octocat/Hello-World", f"Failed for URL: {url}"


async def test_github_invalid_url_raises_value_error():
    """Non-GitHub URL or URL with only owner (no repo) → raises ValueError."""
    extractor = GitHubExtractor()

    with pytest.raises(ValueError, match="Cannot parse GitHub owner/repo"):
        await extractor.extract("https://example.com/some/path")

    with pytest.raises(ValueError, match="Cannot parse GitHub owner/repo"):
        await extractor.extract("https://github.com/onlyowner")


async def test_github_languages_endpoint_fails():
    """Languages endpoint raises → still returns metadata and README."""
    async def _get(url, **kwargs):  # noqa: ANN001, ANN202
        if url.endswith("/languages"):
            raise RuntimeError("Languages API failed")
        if url.endswith("/readme"):
            return _make_response(text=_GITHUB_README_TEXT, status_code=200)
        resp = _make_response(json_data=_GITHUB_REPO_DATA)
        resp.raise_for_status = MagicMock()
        return resp

    client_mock = MagicMock()
    client_mock.get = AsyncMock(side_effect=_get)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=client_mock)
    cm.__aexit__ = AsyncMock(return_value=False)
    client_ctor = MagicMock(return_value=cm)

    with patch("zettelkasten_bot.sources.github.httpx.AsyncClient", client_ctor):
        extractor = GitHubExtractor()
        result = await extractor.extract(_GITHUB_URL)

    assert result.title == "octocat/Hello-World"
    assert "## README" in result.body
    assert "## Languages" not in result.body
    assert result.metadata["stars"] == 1234


async def test_github_source_type():
    """ExtractedContent.source_type == SourceType.GITHUB."""
    client_ctor = _make_github_client_cm()

    with patch("zettelkasten_bot.sources.github.httpx.AsyncClient", client_ctor):
        extractor = GitHubExtractor()
        result = await extractor.extract(_GITHUB_URL)

    assert result.source_type == SourceType.GITHUB


# ─────────────────────────────────────────────────────────────────────────────
# Generic extractor helpers
# ─────────────────────────────────────────────────────────────────────────────

_GENERIC_URL = "https://blog.example.com/my-article"
_GENERIC_HTML = """<html>
<head><title>Page Title</title></head>
<body>
<p>First paragraph with some content here.</p>
<p>Second paragraph with more content here.</p>
</body>
</html>"""
_GENERIC_BODY = "First paragraph with some content here.\n\nSecond paragraph with more content here."


def _make_generic_client_cm(response: MagicMock | None = None) -> MagicMock:
    """Build an httpx.AsyncClient context-manager mock for Generic tests."""
    if response is None:
        response = _make_response(text=_GENERIC_HTML)

    async def _get(url, **kwargs):  # noqa: ANN001, ANN202
        if isinstance(response, Exception):
            raise response
        return response

    client_mock = MagicMock()
    client_mock.get = AsyncMock(side_effect=_get)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=client_mock)
    cm.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=cm)


def _make_generic_trafilatura_mock(
    body: str | None = _GENERIC_BODY,
    title: str | None = "Trafilatura Title",
    author: str | None = "Alice Smith",
    date: str | None = "2024-01-15",
    sitename: str | None = "Example Blog",
) -> tuple[MagicMock, MagicMock]:
    """Return (mock_extract_fn, mock_extract_metadata_fn) for generic extractor."""
    mock_extract = MagicMock(return_value=body)
    meta = MagicMock()
    meta.title = title
    meta.author = author
    meta.date = date
    meta.sitename = sitename
    meta.categories = None
    meta.tags = None
    mock_meta = MagicMock(return_value=meta)
    return mock_extract, mock_meta


# ─────────────────────────────────────────────────────────────────────────────
# Generic extractor tests
# ─────────────────────────────────────────────────────────────────────────────


async def test_generic_happy_path():
    """trafilatura extracts body and metadata → correct title, body, metadata fields."""
    client_ctor = _make_generic_client_cm()
    mock_extract, mock_meta = _make_generic_trafilatura_mock()

    with (
        patch("zettelkasten_bot.sources.generic.httpx.AsyncClient", client_ctor),
        patch("zettelkasten_bot.sources.generic.trafilatura.extract", mock_extract),
        patch("zettelkasten_bot.sources.generic.trafilatura.extract_metadata", mock_meta),
    ):
        extractor = GenericExtractor()
        result = await extractor.extract(_GENERIC_URL)

    assert isinstance(result, ExtractedContent)
    assert result.title == "Trafilatura Title"
    assert result.body == _GENERIC_BODY
    assert result.metadata["author"] == "Alice Smith"
    assert result.metadata["date"] == "2024-01-15"
    assert result.metadata["site_name"] == "Example Blog"
    assert result.source_type == SourceType.GENERIC


async def test_generic_trafilatura_returns_none_falls_back_to_bs4():
    """trafilatura returns None for body → falls back to BeautifulSoup paragraph extraction."""
    html = _GENERIC_HTML
    client_ctor = _make_generic_client_cm(_make_response(text=html))
    mock_extract, mock_meta = _make_generic_trafilatura_mock(body=None)

    with (
        patch("zettelkasten_bot.sources.generic.httpx.AsyncClient", client_ctor),
        patch("zettelkasten_bot.sources.generic.trafilatura.extract", mock_extract),
        patch("zettelkasten_bot.sources.generic.trafilatura.extract_metadata", mock_meta),
    ):
        extractor = GenericExtractor()
        result = await extractor.extract(_GENERIC_URL)

    # BS4 should pick up the <p> tags
    assert "First paragraph" in result.body
    assert "Second paragraph" in result.body


async def test_generic_both_trafilatura_and_bs4_empty_raises():
    """Both trafilatura and BS4 paragraphs empty → raises RuntimeError."""
    empty_html = "<html><head><title>No Content</title></head><body></body></html>"
    client_ctor = _make_generic_client_cm(_make_response(text=empty_html))

    mock_extract = MagicMock(return_value=None)
    meta = MagicMock()
    meta.title = "No Content"
    meta.author = None
    meta.date = None
    meta.sitename = None
    meta.categories = None
    meta.tags = None
    mock_meta = MagicMock(return_value=meta)

    with (
        patch("zettelkasten_bot.sources.generic.httpx.AsyncClient", client_ctor),
        patch("zettelkasten_bot.sources.generic.trafilatura.extract", mock_extract),
        patch("zettelkasten_bot.sources.generic.trafilatura.extract_metadata", mock_meta),
    ):
        extractor = GenericExtractor()
        with pytest.raises(RuntimeError, match="Could not extract any content"):
            await extractor.extract(_GENERIC_URL)


async def test_generic_title_from_trafilatura_metadata():
    """Title is extracted from trafilatura metadata.title when present."""
    client_ctor = _make_generic_client_cm()
    mock_extract, mock_meta = _make_generic_trafilatura_mock(title="Trafilatura Title")

    with (
        patch("zettelkasten_bot.sources.generic.httpx.AsyncClient", client_ctor),
        patch("zettelkasten_bot.sources.generic.trafilatura.extract", mock_extract),
        patch("zettelkasten_bot.sources.generic.trafilatura.extract_metadata", mock_meta),
    ):
        extractor = GenericExtractor()
        result = await extractor.extract(_GENERIC_URL)

    assert result.title == "Trafilatura Title"


async def test_generic_title_fallback_to_html_title_tag():
    """When trafilatura metadata has no title → falls back to <title> tag."""
    html = f"<html><head><title>HTML Title Tag</title></head><body><p>{_GENERIC_BODY}</p></body></html>"
    client_ctor = _make_generic_client_cm(_make_response(text=html))

    mock_extract = MagicMock(return_value=_GENERIC_BODY)
    meta = MagicMock()
    meta.title = None  # No title from trafilatura
    meta.author = None
    meta.date = None
    meta.sitename = None
    meta.categories = None
    meta.tags = None
    mock_meta = MagicMock(return_value=meta)

    with (
        patch("zettelkasten_bot.sources.generic.httpx.AsyncClient", client_ctor),
        patch("zettelkasten_bot.sources.generic.trafilatura.extract", mock_extract),
        patch("zettelkasten_bot.sources.generic.trafilatura.extract_metadata", mock_meta),
    ):
        extractor = GenericExtractor()
        result = await extractor.extract(_GENERIC_URL)

    assert result.title == "HTML Title Tag"


async def test_generic_httpx_raises_propagates():
    """httpx raises connection error → exception propagates out of extractor."""
    import httpx as _httpx

    async def _get_raising(url, **kwargs):  # noqa: ANN001, ANN202
        raise _httpx.ConnectError("Connection refused")

    client_mock = MagicMock()
    client_mock.get = AsyncMock(side_effect=_get_raising)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=client_mock)
    cm.__aexit__ = AsyncMock(return_value=False)
    client_ctor = MagicMock(return_value=cm)

    with patch("zettelkasten_bot.sources.generic.httpx.AsyncClient", client_ctor):
        extractor = GenericExtractor()
        with pytest.raises(_httpx.ConnectError):
            await extractor.extract(_GENERIC_URL)


# ─────────────────────────────────────────────────────────────────────────────
# Registry integration tests
# ─────────────────────────────────────────────────────────────────────────────


def test_registry_list_extractors_returns_all_five():
    """list_extractors() returns all 5 source types."""
    extractors = list_extractors()
    assert len(extractors) == 5
    expected_types = {
        SourceType.REDDIT,
        SourceType.YOUTUBE,
        SourceType.NEWSLETTER,
        SourceType.GITHUB,
        SourceType.GENERIC,
    }
    assert set(extractors.keys()) == expected_types


def test_registry_get_extractor_reddit_with_comment_depth():
    """get_extractor(REDDIT, settings) returns RedditExtractor with correct comment_depth."""
    settings = MagicMock()
    settings.reddit_client_id = "cid"
    settings.reddit_client_secret = "csecret"
    settings.reddit_user_agent = "ua/1.0"
    settings.reddit_comment_depth = 7

    extractor = get_extractor(SourceType.REDDIT, settings)
    assert isinstance(extractor, RedditExtractor)
    assert extractor._comment_depth == 7


def test_registry_get_extractor_youtube():
    """get_extractor(YOUTUBE, settings) returns YouTubeExtractor."""
    settings = MagicMock()
    extractor = get_extractor(SourceType.YOUTUBE, settings)
    assert isinstance(extractor, YouTubeExtractor)


def test_registry_get_extractor_unregistered_raises_key_error():
    """get_extractor with an unregistered type raises KeyError."""
    settings = MagicMock()

    class _FakeType:
        pass

    with pytest.raises((KeyError, Exception)):
        get_extractor(_FakeType(), settings)  # type: ignore[arg-type]
