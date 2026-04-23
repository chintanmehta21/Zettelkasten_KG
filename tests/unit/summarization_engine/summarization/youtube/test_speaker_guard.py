"""Hard-fail tests for placeholder-only speakers on YouTubeStructuredPayload.

Regression anchor: iter-08 of docs/summary_eval/youtube shipped a payload with
speakers=["narrator"] and no channel metadata, which the soft filter could not
repair. This test locks the new hard validator in place.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from website.features.summarization_engine.summarization.youtube.schema import (
    ChapterBullet,
    YouTubeDetailedPayload,
    YouTubeStructuredPayload,
)


def _detailed(**overrides) -> YouTubeDetailedPayload:
    base = dict(
        thesis="A complete thesis sentence.",
        format="lecture",
        chapters_or_segments=[
            ChapterBullet(
                timestamp="00:15",
                title="Intro",
                bullets=["A.", "B.", "C.", "D.", "E."],
            ),
        ],
        demonstrations=[],
        closing_takeaway="A closing sentence.",
    )
    base.update(overrides)
    return YouTubeDetailedPayload(**base)


def _base_kwargs(**speaker_overrides):
    kwargs = dict(
        mini_title="Test title 60 chars",
        brief_summary=(
            "Complete sentence one here. Complete sentence two follows. "
            "Complete sentence three ends."
        ),
        tags=[
            "tag-one", "tag-two", "tag-three", "tag-four",
            "tag-five", "tag-six", "tag-seven",
        ],
        speakers=["Joe Rogan"],
        entities_discussed=["Example"],
        detailed_summary=_detailed(),
    )
    kwargs.update(speaker_overrides)
    return kwargs


def test_placeholder_only_speakers_raise():
    with pytest.raises(ValidationError):
        YouTubeStructuredPayload(**_base_kwargs(speakers=["narrator", "host"]))


def test_single_placeholder_speaker_raises():
    with pytest.raises(ValidationError):
        YouTubeStructuredPayload(**_base_kwargs(speakers=["the host"]))


def test_real_speaker_passes():
    payload = YouTubeStructuredPayload(**_base_kwargs(speakers=["Joe Rogan"]))
    assert payload.speakers == ["Joe Rogan"]


def test_mixed_placeholders_and_real_speaker_passes_with_placeholders_dropped():
    payload = YouTubeStructuredPayload(
        **_base_kwargs(speakers=["narrator", "Joe Rogan", "host"])
    )
    assert payload.speakers == ["Joe Rogan"]


def test_case_insensitive_placeholder_rejection():
    with pytest.raises(ValidationError):
        YouTubeStructuredPayload(
            **_base_kwargs(speakers=["Narrator", "HOST", "Presenter"])
        )


def test_whitespace_only_speakers_treated_as_empty_and_raise():
    with pytest.raises(ValidationError):
        YouTubeStructuredPayload(**_base_kwargs(speakers=["   ", ""]))
