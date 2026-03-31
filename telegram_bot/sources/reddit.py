"""Reddit content extractor using PRAW.

Extracts post text, top comments, media URLs, and metadata from Reddit
threads. Falls back gracefully when credentials are missing or posts are
inaccessible.
"""

from __future__ import annotations

import logging
from typing import Any

import praw

from telegram_bot.models.capture import ExtractedContent, SourceType
from telegram_bot.sources.base import SourceExtractor

logger = logging.getLogger(__name__)


class RedditExtractor(SourceExtractor):
    """Extract content from Reddit posts via PRAW."""

    source_type = SourceType.REDDIT

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        user_agent: str,
        comment_depth: int = 10,
    ) -> None:
        self._reddit = praw.Reddit(
            client_id=client_id,
            client_secret=client_secret,
            user_agent=user_agent,
        )
        # Read-only mode — no user auth needed
        self._reddit.read_only = True
        # D001: configurable comment depth (default 10 for backward compat)
        self._comment_depth = comment_depth

    async def extract(self, url: str) -> ExtractedContent:
        """Extract Reddit post content, comments, and metadata."""
        try:
            submission = self._reddit.submission(url=url)
            # Force lazy load
            _ = submission.title

            # Build body from selftext + top comments
            parts: list[str] = []
            if submission.selftext:
                parts.append(f"## Post Content\n\n{submission.selftext}")

            # Fetch top-level comments (replace MoreComments)
            submission.comments.replace_more(limit=0)
            top_comments = submission.comments[:self._comment_depth]
            if top_comments:
                parts.append("\n## Top Comments\n")
                for i, comment in enumerate(top_comments, 1):
                    author = getattr(comment, "author", None)
                    author_name = str(author) if author else "[deleted]"
                    score = getattr(comment, "score", 0)
                    parts.append(
                        f"**Comment {i}** (u/{author_name}, {score} pts):\n{comment.body}\n"
                    )

            body = "\n".join(parts) if parts else "(No text content)"

            metadata: dict[str, Any] = {
                "subreddit": str(submission.subreddit),
                "author": str(submission.author) if submission.author else "[deleted]",
                "score": submission.score,
                "upvote_ratio": submission.upvote_ratio,
                "num_comments": submission.num_comments,
                "created_utc": submission.created_utc,
                "is_self": submission.is_self,
                "flair": submission.link_flair_text,
            }

            # Media URLs (images, videos)
            if hasattr(submission, "url") and submission.url != url:
                metadata["media_url"] = submission.url

            return ExtractedContent(
                url=url,
                source_type=SourceType.REDDIT,
                title=submission.title,
                body=body,
                metadata=metadata,
            )

        except Exception as exc:
            logger.error("Error extracting Reddit %s: %s", url, exc)
            raise
