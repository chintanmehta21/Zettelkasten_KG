"""Pydantic schema for Reddit-specific structured summary payload."""
from __future__ import annotations

from pydantic import BaseModel, Field, StringConstraints
from typing_extensions import Annotated


RedditLabel = Annotated[str, StringConstraints(pattern=r"^r/[^ ]+ .+$", max_length=60)]


class RedditCluster(BaseModel):
    theme: str
    reasoning: str
    examples: list[str] = Field(default_factory=list)


class RedditDetailedPayload(BaseModel):
    op_intent: str
    reply_clusters: list[RedditCluster] = Field(..., min_length=1)
    counterarguments: list[str] = Field(default_factory=list)
    unresolved_questions: list[str] = Field(default_factory=list)
    moderation_context: str | None = None


class RedditStructuredPayload(BaseModel):
    mini_title: RedditLabel
    brief_summary: str
    tags: list[str] = Field(..., min_length=7, max_length=10)
    detailed_summary: RedditDetailedPayload
