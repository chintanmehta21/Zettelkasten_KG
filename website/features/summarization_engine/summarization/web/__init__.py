from website.features.summarization_engine.core.models import SourceType
from website.features.summarization_engine.summarization.default.summarizer import (
    DefaultSummarizer,
)


class WebSummarizer(DefaultSummarizer):
    source_type = SourceType.WEB


__all__ = ["WebSummarizer"]
