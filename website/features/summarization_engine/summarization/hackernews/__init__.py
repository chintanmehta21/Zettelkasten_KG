from website.features.summarization_engine.core.models import SourceType
from website.features.summarization_engine.summarization.default.summarizer import (
    DefaultSummarizer,
)


class HackerNewsSummarizer(DefaultSummarizer):
    source_type = SourceType.HACKERNEWS


__all__ = ["HackerNewsSummarizer"]
