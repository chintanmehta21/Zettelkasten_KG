"""4-step speaker fallback chain (P5 carryover).

Verifies the order: placeholder strip -> real names -> entity fallback ->
'The speaker' default. Each test exercises one branch in isolation.
"""
from __future__ import annotations

from website.features.summarization_engine.summarization.youtube.schema import (
    ChapterBullet,
    YouTubeDetailedPayload,
    YouTubeStructuredPayload,
    _looks_like_named_human,
)


def _payload(*, speakers, entities=None):
    return YouTubeStructuredPayload(
        mini_title="test title",
        brief_summary=(
            "A. B. C. D. E. Full brief needed to pass repair helpers."
        ),
        tags=["a", "b", "c", "d", "e", "f", "g"],
        speakers=speakers,
        entities_discussed=entities or [],
        detailed_summary=YouTubeDetailedPayload(
            thesis="Thesis.",
            format="lecture",
            chapters_or_segments=[
                ChapterBullet(timestamp="00:00", title="X", bullets=["a.", "b.", "c.", "d.", "e."])
            ],
            demonstrations=[],
            closing_takeaway="Done.",
        ),
    )


def test_step2_real_speaker_preserved():
    payload = _payload(speakers=["Joe Rogan"])
    assert payload.speakers == ["Joe Rogan"]


def test_step1_placeholders_stripped_but_real_kept():
    payload = _payload(speakers=["unidentified host", "Joe Rogan"])
    assert payload.speakers == ["Joe Rogan"]


def test_step3_falls_back_to_named_entity_when_placeholders_only():
    payload = _payload(
        speakers=["unidentified host"],
        entities=["MAPS", "Rick Strassman", "FDA"],
    )
    # MAPS and FDA are acronyms; Rick Strassman is a named human.
    assert payload.speakers == ["Rick Strassman"]


def test_step4_falls_back_to_neutral_label_when_no_human_entity():
    payload = _payload(
        speakers=["unidentified"],
        entities=["MAPS", "FDA"],
    )
    assert payload.speakers == ["The speaker"]


def test_looks_like_named_human_rejects_single_token():
    assert not _looks_like_named_human("Madonna")


def test_looks_like_named_human_rejects_acronym_pair():
    assert not _looks_like_named_human("IBM CORP")


def test_looks_like_named_human_accepts_two_token_name():
    assert _looks_like_named_human("Rick Strassman")
    assert _looks_like_named_human("Joe Rogan")
