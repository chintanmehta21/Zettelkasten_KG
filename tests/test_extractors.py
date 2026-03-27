"""Offline tests for Reddit and YouTube content extractors.

All mocks use unittest.mock — no real API calls are made.
asyncio_mode=auto (pytest.ini) — no @pytest.mark.asyncio needed.

Patch sites:
  - Reddit: zettelkasten_bot.sources.reddit.praw.Reddit
  - YouTube yt_dlp: yt_dlp.YoutubeDL  (imported locally inside extract())
  - YouTube transcript: youtube_transcript_api.YouTubeTranscriptApi  (imported locally)
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from zettelkasten_bot.models.capture import ExtractedContent, SourceType
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


def _make_yt_dlp_mock(
    info: dict | None = None,
    raise_exc: Exception | None = None,
) -> MagicMock:
    """Build a MagicMock for yt_dlp.YoutubeDL used as a context manager.

    Returns a mock that, when used as ``with yt_dlp.YoutubeDL(...) as ydl:``,
    yields a mock whose ``extract_info`` either returns *info* or raises *raise_exc*.
    """
    ydl_instance = MagicMock()
    if raise_exc is not None:
        ydl_instance.extract_info.side_effect = raise_exc
    else:
        ydl_instance.extract_info.return_value = info

    # The mock returned by YoutubeDL(...) must act as a context manager
    cm_mock = MagicMock()
    cm_mock.__enter__ = MagicMock(return_value=ydl_instance)
    cm_mock.__exit__ = MagicMock(return_value=False)
    return cm_mock


def _make_transcript_snippet(text: str) -> MagicMock:
    snippet = MagicMock()
    snippet.text = text
    return snippet


_DEFAULT_YDL_INFO: dict = {
    "title": "Never Gonna Give You Up",
    "channel": "Rick Astley",
    "duration": 213,
    "view_count": 1_000_000,
    "upload_date": "20091025",
    "description": "The official video for Never Gonna Give You Up",
    "like_count": 50000,
}

_DEFAULT_TRANSCRIPT = [
    _make_transcript_snippet("We're no strangers to love"),
    _make_transcript_snippet("You know the rules and so do I"),
]


# ─────────────────────────────────────────────────────────────────────────────
# YouTube extractor tests
# ─────────────────────────────────────────────────────────────────────────────


async def test_youtube_happy_path():
    """Metadata + transcript available → correct title, body, all metadata fields."""
    ydl_cm = _make_yt_dlp_mock(info=_DEFAULT_YDL_INFO)
    transcript_api_cls = MagicMock()
    transcript_api_cls.return_value.fetch.return_value = _DEFAULT_TRANSCRIPT

    with (
        patch("yt_dlp.YoutubeDL", return_value=ydl_cm),
        patch("youtube_transcript_api.YouTubeTranscriptApi", transcript_api_cls),
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
    """Transcript unavailable → body has fallback text, has_transcript==False."""
    ydl_cm = _make_yt_dlp_mock(info=_DEFAULT_YDL_INFO)
    transcript_api_cls = MagicMock()
    transcript_api_cls.return_value.fetch.side_effect = Exception("No transcript")

    with (
        patch("yt_dlp.YoutubeDL", return_value=ydl_cm),
        patch("youtube_transcript_api.YouTubeTranscriptApi", transcript_api_cls),
    ):
        extractor = YouTubeExtractor()
        result = await extractor.extract(_YOUTUBE_URL)

    assert "(Transcript not available" in result.body
    assert result.metadata["has_transcript"] is False
    assert result.title == "Never Gonna Give You Up"


async def test_youtube_ytdlp_fails_transcript_succeeds():
    """yt-dlp fails → title falls back to 'YouTube Video {id}', transcript still extracted."""
    ydl_cm = _make_yt_dlp_mock(raise_exc=Exception("yt-dlp fail"))
    transcript_api_cls = MagicMock()
    transcript_api_cls.return_value.fetch.return_value = _DEFAULT_TRANSCRIPT

    with (
        patch("yt_dlp.YoutubeDL", return_value=ydl_cm),
        patch("youtube_transcript_api.YouTubeTranscriptApi", transcript_api_cls),
    ):
        extractor = YouTubeExtractor()
        result = await extractor.extract(_YOUTUBE_URL)

    assert result.title == f"YouTube Video {_VIDEO_ID}"
    assert "## Transcript" in result.body
    assert result.metadata["has_transcript"] is True


async def test_youtube_both_fail():
    """Both yt-dlp and transcript fail → minimal content with video_id."""
    ydl_cm = _make_yt_dlp_mock(raise_exc=Exception("yt-dlp fail"))
    transcript_api_cls = MagicMock()
    transcript_api_cls.return_value.fetch.side_effect = Exception("Transcript fail")

    with (
        patch("yt_dlp.YoutubeDL", return_value=ydl_cm),
        patch("youtube_transcript_api.YouTubeTranscriptApi", transcript_api_cls),
    ):
        extractor = YouTubeExtractor()
        result = await extractor.extract(_YOUTUBE_URL)

    assert result.title == f"YouTube Video {_VIDEO_ID}"
    assert result.metadata["video_id"] == _VIDEO_ID
    assert result.metadata["has_transcript"] is False


async def test_youtube_invalid_url_raises():
    """URL with no extractable video ID → raises ValueError."""
    extractor = YouTubeExtractor()
    with pytest.raises(ValueError, match="Cannot extract video ID"):
        await extractor.extract("https://www.youtube.com/playlist?list=PLabc")


async def test_youtube_shorts_url():
    """YouTube Shorts URL → correctly extracts video ID."""
    shorts_url = "https://www.youtube.com/shorts/abc12345678"
    ydl_cm = _make_yt_dlp_mock(info={"title": "Short video"})
    transcript_api_cls = MagicMock()
    transcript_api_cls.return_value.fetch.side_effect = Exception("no transcript")

    with (
        patch("yt_dlp.YoutubeDL", return_value=ydl_cm),
        patch("youtube_transcript_api.YouTubeTranscriptApi", transcript_api_cls),
    ):
        extractor = YouTubeExtractor()
        result = await extractor.extract(shorts_url)

    assert result.metadata["video_id"] == "abc12345678"


async def test_youtube_short_url():
    """youtu.be short URL → correctly extracts video ID."""
    short_url = "https://youtu.be/dQw4w9WgXcQ"
    ydl_cm = _make_yt_dlp_mock(info=_DEFAULT_YDL_INFO)
    transcript_api_cls = MagicMock()
    transcript_api_cls.return_value.fetch.return_value = _DEFAULT_TRANSCRIPT

    with (
        patch("yt_dlp.YoutubeDL", return_value=ydl_cm),
        patch("youtube_transcript_api.YouTubeTranscriptApi", transcript_api_cls),
    ):
        extractor = YouTubeExtractor()
        result = await extractor.extract(short_url)

    assert result.metadata["video_id"] == _VIDEO_ID


async def test_youtube_embed_url():
    """Embed URL → correctly extracts video ID."""
    embed_url = "https://www.youtube.com/embed/dQw4w9WgXcQ"
    ydl_cm = _make_yt_dlp_mock(info=_DEFAULT_YDL_INFO)
    transcript_api_cls = MagicMock()
    transcript_api_cls.return_value.fetch.return_value = _DEFAULT_TRANSCRIPT

    with (
        patch("yt_dlp.YoutubeDL", return_value=ydl_cm),
        patch("youtube_transcript_api.YouTubeTranscriptApi", transcript_api_cls),
    ):
        extractor = YouTubeExtractor()
        result = await extractor.extract(embed_url)

    assert result.metadata["video_id"] == _VIDEO_ID


async def test_youtube_video_id_in_metadata():
    """video_id always present in metadata, regardless of API failures."""
    ydl_cm = _make_yt_dlp_mock(info=_DEFAULT_YDL_INFO)
    transcript_api_cls = MagicMock()
    transcript_api_cls.return_value.fetch.return_value = _DEFAULT_TRANSCRIPT

    with (
        patch("yt_dlp.YoutubeDL", return_value=ydl_cm),
        patch("youtube_transcript_api.YouTubeTranscriptApi", transcript_api_cls),
    ):
        extractor = YouTubeExtractor()
        result = await extractor.extract(_YOUTUBE_URL)

    assert "video_id" in result.metadata
    assert result.metadata["video_id"] == _VIDEO_ID


async def test_youtube_source_type():
    """ExtractedContent.source_type == SourceType.YOUTUBE."""
    ydl_cm = _make_yt_dlp_mock(info=_DEFAULT_YDL_INFO)
    transcript_api_cls = MagicMock()
    transcript_api_cls.return_value.fetch.return_value = _DEFAULT_TRANSCRIPT

    with (
        patch("yt_dlp.YoutubeDL", return_value=ydl_cm),
        patch("youtube_transcript_api.YouTubeTranscriptApi", transcript_api_cls),
    ):
        extractor = YouTubeExtractor()
        result = await extractor.extract(_YOUTUBE_URL)

    assert result.source_type == SourceType.YOUTUBE
