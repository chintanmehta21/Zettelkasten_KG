"""Pydantic schema for YouTube-specific structured summary payload."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, StringConstraints
from typing_extensions import Annotated


MiniTitle = Annotated[str, StringConstraints(max_length=50)]


class ChapterBullet(BaseModel):
    timestamp: str
    title: str
    bullets: list[str] = Field(..., min_length=1)


class YouTubeDetailedPayload(BaseModel):
    thesis: str
    format: Literal[
        "tutorial",
        "interview",
        "commentary",
        "lecture",
        "review",
        "debate",
        "walkthrough",
        "reaction",
        "vlog",
        "other",
    ]
    chapters_or_segments: list[ChapterBullet] = Field(..., min_length=1)
    demonstrations: list[str] = Field(default_factory=list)
    closing_takeaway: str


class YouTubeStructuredPayload(BaseModel):
    mini_title: MiniTitle
    brief_summary: str
    tags: list[str] = Field(..., min_length=7, max_length=10)
    speakers: list[str] = Field(..., min_length=1)
    guests: list[str] | None = None
    entities_discussed: list[str] = Field(default_factory=list)
    detailed_summary: YouTubeDetailedPayload
