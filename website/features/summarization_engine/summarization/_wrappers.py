"""Thin per-source summarizer wrappers."""
from __future__ import annotations

from website.features.summarization_engine.core.models import SourceType
from website.features.summarization_engine.summarization import register_summarizer
from website.features.summarization_engine.summarization.default.summarizer import DefaultSummarizer


def make_wrapper(name: str, source_type: SourceType):
    cls = type(name, (DefaultSummarizer,), {"source_type": source_type, "__module__": __name__})
    register_summarizer(cls)
    return cls


GitHubSummarizer = make_wrapper("GitHubSummarizer", SourceType.GITHUB)
HackerNewsSummarizer = make_wrapper("HackerNewsSummarizer", SourceType.HACKERNEWS)
ArxivSummarizer = make_wrapper("ArxivSummarizer", SourceType.ARXIV)
NewsletterSummarizer = make_wrapper("NewsletterSummarizer", SourceType.NEWSLETTER)
# RedditSummarizer lives in `reddit/summarizer.py` — the iter-09 Reddit-specific
# summarizer has its own prompt, schema, and brief-repair validators.
YouTubeSummarizer = make_wrapper("YouTubeSummarizer", SourceType.YOUTUBE)
LinkedInSummarizer = make_wrapper("LinkedInSummarizer", SourceType.LINKEDIN)
PodcastSummarizer = make_wrapper("PodcastSummarizer", SourceType.PODCAST)
TwitterSummarizer = make_wrapper("TwitterSummarizer", SourceType.TWITTER)
WebSummarizer = make_wrapper("WebSummarizer", SourceType.WEB)
