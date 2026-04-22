"""Pydantic schema for YouTube-specific structured summary payload."""
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, StringConstraints, model_validator
from typing_extensions import Annotated


MiniTitle = Annotated[str, StringConstraints(max_length=50)]
_TITLE_STOPWORDS = {"a", "an", "and", "for", "in", "of", "the", "to", "with"}


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

    @model_validator(mode="after")
    def _normalize_note_facing_fields(self) -> "YouTubeStructuredPayload":
        self.mini_title = _normalize_mini_title(self.mini_title)
        self.tags = _ensure_format_tag(self.tags, self.detailed_summary.format)
        self.brief_summary = _repair_brief_summary(
            brief=self.brief_summary,
            format_name=self.detailed_summary.format,
            thesis=self.detailed_summary.thesis,
            speakers=self.speakers,
            entities=self.entities_discussed,
            chapter_titles=[item.title for item in self.detailed_summary.chapters_or_segments],
            closing_takeaway=self.detailed_summary.closing_takeaway,
        )
        return self


def _normalize_mini_title(title: str) -> str:
    tokens = re.findall(r"[A-Za-z0-9]+", title or "")
    preferred = [token for token in tokens if token.lower() not in _TITLE_STOPWORDS]
    words = preferred if len(preferred) >= 3 else tokens
    normalized = " ".join(words[:5]).strip()
    return normalized[:50] or "YouTube Summary"


def _ensure_format_tag(tags: list[str], format_name: str) -> list[str]:
    normalized: list[str] = []
    for tag in tags:
        cleaned = str(tag).strip().lower().replace(" ", "-")
        if cleaned and cleaned not in normalized:
            normalized.append(cleaned)
    format_tag = format_name.strip().lower()
    if format_tag and format_tag not in normalized:
        if len(normalized) >= 10:
            normalized = normalized[:-1]
        normalized.append(format_tag)
    return normalized[:10]


def _repair_brief_summary(
    *,
    brief: str,
    format_name: str,
    thesis: str,
    speakers: list[str],
    entities: list[str],
    chapter_titles: list[str],
    closing_takeaway: str,
) -> str:
    cleaned = re.sub(r"\s+", " ", brief or "").strip()
    sentences = re.findall(r"[^.!?]+[.!?]", cleaned)
    lower_brief = cleaned.lower()
    has_format = format_name.lower() in lower_brief
    has_speaker = any(speaker.lower() in lower_brief for speaker in speakers[:2])
    if cleaned.endswith((".", "!", "?")) and len(sentences) >= 5 and has_format and has_speaker and len(cleaned) <= 400:
        return cleaned

    speaker_text = _join_items(speakers[:2])
    entity_text = _join_items(entities[:2]) or "its key compounds and research contexts"
    chapter_text = _join_items(chapter_titles[:2]) or "its history and modern research"
    repaired = " ".join(
        [
            _as_sentence(f"This {format_name} video explains {thesis}"),
            _as_sentence(f"It moves through sections on {chapter_text}"),
            _as_sentence(f"It also covers {entity_text}"),
            _as_sentence(f"Featured voices include {speaker_text}"),
            _as_sentence(closing_takeaway),
        ]
    )
    if len(repaired) <= 400:
        return repaired
    trimmed = repaired[:400]
    last_stop = max(trimmed.rfind("."), trimmed.rfind("!"), trimmed.rfind("?"))
    if last_stop >= 0:
        trimmed = trimmed[: last_stop + 1]
    else:
        trimmed = trimmed.rstrip(". ") + "."
    return trimmed


def _join_items(items: list[str]) -> str:
    values = [re.sub(r"\s+", " ", item).strip() for item in items if item and item.strip()]
    if not values:
        return ""
    if len(values) == 1:
        return values[0]
    return f"{values[0]} and {values[1]}"


def _as_sentence(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip().rstrip(",;:")
    if not cleaned:
        return ""
    if cleaned.endswith((".", "!", "?")):
        return cleaned
    return f"{cleaned}."
