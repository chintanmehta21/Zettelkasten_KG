"""Pydantic schema for YouTube-specific structured summary payload."""
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, StringConstraints, model_validator
from typing_extensions import Annotated


MiniTitle = Annotated[str, StringConstraints(max_length=50)]
_TITLE_STOPWORDS = {"a", "an", "and", "for", "in", "of", "the", "to", "with"}
_SPEAKER_PLACEHOLDERS = frozenset({
    "narrator", "host", "speaker", "analyst", "commentator",
    "voiceover", "voice over", "author of the source",
    "the host", "the speaker", "the narrator", "author",
    "presenter", "the presenter", "source", "the source",
    "channel", "the channel", "uploader", "the uploader",
    "creator", "the creator", "interviewer", "the interviewer",
    "interviewee", "the interviewee", "participant", "the participant",
    "guest", "the guest", "youtuber", "the youtuber",
})


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

    @model_validator(mode="after")
    def _reject_placeholder_only_speakers(self) -> "YouTubeStructuredPayload":
        real = [
            s.strip()
            for s in (self.speakers or [])
            if isinstance(s, str)
            and s.strip()
            and s.strip().lower() not in _SPEAKER_PLACEHOLDERS
        ]
        if not real:
            raise ValueError(
                "speakers must contain at least one non-placeholder name; "
                "got only placeholders or empty list"
            )
        self.speakers = real
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
    """Accept the LLM brief as-is when it's a plausible natural paragraph.

    Only rebuild from structured fields when the model output is empty or
    clearly malformed (no terminal punctuation, fewer than 2 complete
    sentences). The rebuilt brief uses whole source sentences — never
    word-count truncation — so it never dies mid-clause.
    """
    from website.features.summarization_engine.summarization.common.text_guards import (
        ends_with_dangling_word,
        repair_or_drop,
    )

    cleaned = re.sub(r"\s+", " ", brief or "").strip()
    sentences = _split_sentences(cleaned)
    tail_ok = bool(sentences) and not ends_with_dangling_word(sentences[-1])
    looks_complete = (
        cleaned
        and cleaned[-1] in ".!?"
        and len(sentences) >= 2
        and len(cleaned) <= 500
        and tail_ok
    )
    if looks_complete:
        return cleaned

    already_terminated = bool(cleaned) and cleaned[-1] in ".!?"
    if already_terminated:
        repaired = repair_or_drop(cleaned)
        if repaired:
            repaired_sentences = _split_sentences(repaired)
            if (
                len(repaired_sentences) >= 2
                and len(repaired) <= 500
                and not ends_with_dangling_word(repaired_sentences[-1])
            ):
                return repaired

    speaker = _primary_speaker(speakers) or "The speaker"
    parts: list[str] = []
    thesis_sentence = _first_sentence(thesis)
    if thesis_sentence:
        parts.append(f"In this {format_name}, {speaker} argues that {thesis_sentence.lower().rstrip('.')}.")
    else:
        parts.append(f"This {format_name} is delivered by {speaker}.")

    if chapter_titles:
        titles = [t for t in chapter_titles if t.strip()][:3]
        if titles:
            parts.append(f"The video moves through {_join_series(titles)}.")

    entity_text = [e for e in entities if e and e.strip()][:3]
    if entity_text:
        parts.append(f"It references {_join_series(entity_text)}.")

    closing_sentence = _first_sentence(closing_takeaway)
    if closing_sentence:
        parts.append(f"The closing takeaway: {closing_sentence.rstrip('.')}.")

    rebuilt = " ".join(parts).strip()
    if len(rebuilt) <= 500 and rebuilt:
        return rebuilt
    # Rebuilt overshoots: drop middle entity sentence first, then chapters.
    for drop_index in (2, 1):
        if drop_index < len(parts):
            trimmed = " ".join(parts[:drop_index] + parts[drop_index + 1 :]).strip()
            if len(trimmed) <= 500:
                return trimmed
    # Last resort: thesis + closing only
    fallback = " ".join([p for p in (parts[0], parts[-1]) if p])
    return fallback[:500].rstrip()


def _primary_speaker(speakers: list[str]) -> str:
    for speaker in speakers or []:
        name = re.sub(r"\s+", " ", (speaker or "")).strip()
        if name and name.lower() not in {"narrator", "host", "speaker", "presenter"}:
            return name
    return ""


def _split_sentences(text: str) -> list[str]:
    return [s.strip() for s in re.findall(r"[^.!?]+[.!?]", text or "") if s.strip()]


def _first_sentence(text: str) -> str:
    sentences = _split_sentences(text)
    if sentences:
        return sentences[0]
    cleaned = re.sub(r"\s+", " ", (text or "")).strip()
    return cleaned


def _join_series(items: list[str]) -> str:
    vals = [re.sub(r"\s+", " ", i).strip() for i in items if i and i.strip()]
    if not vals:
        return ""
    if len(vals) == 1:
        return vals[0]
    if len(vals) == 2:
        return f"{vals[0]} and {vals[1]}"
    return ", ".join(vals[:-1]) + f", and {vals[-1]}"


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
