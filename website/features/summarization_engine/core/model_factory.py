"""Factory that builds a config-driven SummaryResult Pydantic model."""
from __future__ import annotations

from typing import Type

from pydantic import BaseModel, Field

from website.features.summarization_engine.core.config import EngineConfig
from website.features.summarization_engine.core.models import (
    DetailedSummarySection,
    SummaryMetadata,
)


def build_summary_result_model(cfg: EngineConfig) -> Type[BaseModel]:
    """Return a SummaryResult Pydantic class with caps sourced from config."""
    caps = cfg.structured_extract

    class SummaryResult(BaseModel):
        mini_title: str = Field(..., max_length=caps.mini_title_max_chars)
        brief_summary: str = Field(..., max_length=caps.brief_summary_max_chars)
        tags: list[str] = Field(..., min_length=caps.tags_min, max_length=caps.tags_max)
        detailed_summary: list[DetailedSummarySection]
        metadata: SummaryMetadata

    SummaryResult.__name__ = "SummaryResult"
    return SummaryResult
