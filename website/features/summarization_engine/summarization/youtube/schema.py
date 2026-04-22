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
        self.detailed_summary.format = _normalize_format_name(
            self.detailed_summary.format,
            brief=self.brief_summary,
            thesis=self.detailed_summary.thesis,
            chapter_titles=[item.title for item in self.detailed_summary.chapters_or_segments],
        )
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

    entity_text = _join_items(entities[:2]) or "its key compounds and research contexts"
    chapter_text = _join_items(chapter_titles[:2]) or "its history and modern research"
    figure_text = _join_items(_select_figures_for_brief(speakers, entities))
    repaired = _fit_brief_sentences(
        [
            f"This {format_name} video explains {_trim_fragment(thesis, 18)}",
            f"It moves through sections on {_trim_fragment(chapter_text, 12)}",
            f"It also covers {_trim_fragment(entity_text, 8)}",
            f"Key voices and figures include {_trim_fragment(figure_text, 8)}",
            f"The main takeaway is {_trim_fragment(closing_takeaway, 18)}",
        ],
        max_chars=400,
    )
    return repaired or _as_sentence(_trim_fragment(thesis, 24))


def _normalize_format_name(
    format_name: str,
    *,
    brief: str,
    thesis: str,
    chapter_titles: list[str],
) -> str:
    cleaned = (format_name or "").strip().lower()
    if cleaned and cleaned != "other":
        return cleaned

    evidence = " ".join([brief or "", thesis or "", *chapter_titles]).lower()
    lexical_hints = (
        ("tutorial", "tutorial"),
        ("walkthrough", "walkthrough"),
        ("step-by-step", "tutorial"),
        ("how to", "tutorial"),
        ("interview", "interview"),
        ("q&a", "interview"),
        ("conversation", "interview"),
        ("lecture", "lecture"),
        ("seminar", "lecture"),
        ("course", "lecture"),
        ("review", "review"),
        ("verdict", "review"),
        ("reaction", "reaction"),
        ("vlog", "vlog"),
        ("debate", "debate"),
    )
    for needle, inferred in lexical_hints:
        if needle in evidence:
            return inferred
    return "commentary"


def _join_items(items: list[str]) -> str:
    values = [re.sub(r"\s+", " ", item).strip() for item in items if item and item.strip()]
    if not values:
        return ""
    if len(values) == 1:
        return values[0]
    return f"{values[0]} and {values[1]}"


def _select_figures_for_brief(speakers: list[str], entities: list[str]) -> list[str]:
    values = [re.sub(r"\s+", " ", item).strip() for item in speakers if item and item.strip()]
    meaningful = [
        value
        for value in values
        if value.lower() not in {"narrator", "author of the source"}
    ]
    if len(meaningful) >= 2:
        return meaningful[-2:]
    if len(meaningful) == 1:
        fallback_entities = [
            re.sub(r"\s+", " ", item).strip()
            for item in entities
            if item and item.strip() and item.strip() != meaningful[0]
        ]
        if fallback_entities:
            return [meaningful[0], fallback_entities[0]]
        return meaningful
    fallback_entities = [
        re.sub(r"\s+", " ", item).strip()
        for item in entities
        if item and item.strip()
    ]
    return fallback_entities[:2] or values[:2] or ["the source material"]


def _as_sentence(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip().rstrip(",;:")
    if not cleaned:
        return ""
    if cleaned.endswith((".", "!", "?")):
        return cleaned
    return f"{cleaned}."


def _trim_fragment(text: str, max_words: int) -> str:
    cleaned = re.sub(r"\s+", " ", text or "").strip().rstrip(",;:")
    for marker in ("; ", ", but ", ", while ", ", which ", ", and "):
        if marker in cleaned:
            head = cleaned.split(marker, 1)[0].strip().rstrip(",;:")
            if 4 <= len(re.findall(r"\S+", head)) <= max_words:
                return head
    words = re.findall(r"\S+", cleaned)
    if len(words) <= max_words:
        return " ".join(words).rstrip(",;:")
    return " ".join(words[:max_words]).rstrip(",;:")


def _fit_brief_sentences(sentences: list[str], *, max_chars: int) -> str:
    fitted: list[str] = []
    for sentence in sentences:
        candidate = _as_sentence(sentence)
        if not candidate:
            continue
        joined = " ".join([*fitted, candidate]).strip()
        if len(joined) <= max_chars:
            fitted.append(candidate)
            continue

        remaining = max_chars - len(" ".join(fitted)) - (1 if fitted else 0)
        if remaining <= 8:
            break
        trimmed = _as_sentence(_trim_fragment(candidate, max(3, remaining // 7)))
        joined = " ".join([*fitted, trimmed]).strip()
        if len(joined) <= max_chars:
            fitted.append(trimmed)
        break
    return " ".join(fitted).strip()
