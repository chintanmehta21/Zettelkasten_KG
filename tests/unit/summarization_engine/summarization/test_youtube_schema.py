import pytest
from pydantic import ValidationError

from website.features.summarization_engine.summarization.youtube.schema import (
    ChapterBullet,
    YouTubeDetailedPayload,
    YouTubeStructuredPayload,
)


def _base_payload_kwargs():
    return dict(
        mini_title="Intro to Transformers",
        brief_summary="Covers attention math.",
        tags=[
            "transformers",
            "ml",
            "deep-learning",
            "attention",
            "llm",
            "tutorial",
            "beginner",
        ],
        speakers=["Andrej Karpathy"],
        guests=None,
        entities_discussed=["PyTorch", "GPT-2"],
        detailed_summary=YouTubeDetailedPayload(
            thesis="Attention is a kernel.",
            format="lecture",
            chapters_or_segments=[
                ChapterBullet(timestamp="0:00", title="Intro", bullets=["b"])
            ],
            demonstrations=["Live code of multi-head attention"],
            closing_takeaway="Attention as kernel regression.",
        ),
    )


def test_youtube_schema_rejects_empty_speakers():
    with pytest.raises(ValidationError):
        YouTubeStructuredPayload(
            mini_title="Intro to Transformers",
            brief_summary="Covers attention math.",
            tags=[
                "transformers",
                "ml",
                "deep-learning",
                "attention",
                "llm",
                "tutorial",
                "beginner",
            ],
            speakers=[],
            detailed_summary=YouTubeDetailedPayload(
                thesis="Attention mechanism explained.",
                format="tutorial",
                chapters_or_segments=[
                    ChapterBullet(timestamp="0:00", title="Intro", bullets=["b"])
                ],
                demonstrations=[],
                closing_takeaway="Attention is all you need.",
            ),
        )


def test_youtube_schema_accepts_single_speaker():
    payload = YouTubeStructuredPayload(**_base_payload_kwargs())
    assert payload.speakers == ["Andrej Karpathy"]
    assert payload.guests is None


def test_youtube_schema_rejects_empty_chapter_bullets():
    with pytest.raises(ValidationError):
        YouTubeStructuredPayload(
            **{
                **_base_payload_kwargs(),
                "detailed_summary": YouTubeDetailedPayload(
                    thesis="Attention is a kernel.",
                    format="lecture",
                    chapters_or_segments=[
                        ChapterBullet(timestamp="0:00", title="Intro", bullets=[])
                    ],
                    demonstrations=[],
                    closing_takeaway="Attention as kernel regression.",
                ),
            }
        )


def test_youtube_schema_rejects_title_past_limit():
    with pytest.raises(ValidationError):
        YouTubeStructuredPayload(**{**_base_payload_kwargs(), "mini_title": "x" * 51})
