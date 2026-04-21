from website.features.summarization_engine.core.models import SourceType
from website.features.summarization_engine.summarization.default.summarizer import (
    DefaultSummarizer,
)


class TwitterSummarizer(DefaultSummarizer):
    source_type = SourceType.TWITTER


__all__ = ["TwitterSummarizer"]
