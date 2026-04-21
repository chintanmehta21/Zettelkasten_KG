from website.features.summarization_engine.core.models import SourceType
from website.features.summarization_engine.summarization.default.summarizer import (
    DefaultSummarizer,
)


class PodcastSummarizer(DefaultSummarizer):
    source_type = SourceType.PODCAST


__all__ = ["PodcastSummarizer"]
