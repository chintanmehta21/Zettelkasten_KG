"""Pydantic schema for GitHub-specific structured summary payload."""
from __future__ import annotations

from pydantic import BaseModel, Field, StringConstraints
from typing_extensions import Annotated

from website.features.summarization_engine.core.models import DetailedSummarySection


GitHubLabel = Annotated[str, StringConstraints(pattern=r"^[^/]+/[^/]+$", max_length=60)]


class GitHubDetailedSection(DetailedSummarySection):
    module_or_feature: str
    main_stack: list[str] = Field(default_factory=list)
    public_interfaces: list[str] = Field(default_factory=list)
    usability_signals: list[str] = Field(default_factory=list)


class GitHubStructuredPayload(BaseModel):
    mini_title: GitHubLabel
    architecture_overview: str = Field(..., min_length=50, max_length=500)
    brief_summary: str
    tags: list[str] = Field(..., min_length=7, max_length=10)
    benchmarks_tests_examples: list[str] | None = None
    detailed_summary: list[GitHubDetailedSection] = Field(..., min_length=1)
