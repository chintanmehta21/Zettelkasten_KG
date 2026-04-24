"""4-step speaker fallback chain (P5 carryover).

Verifies the order: placeholder strip -> real names -> entity fallback ->
'The speaker' default. Each test exercises one branch in isolation.
"""
from __future__ import annotations

from website.features.summarization_engine.summarization.youtube.schema import (
    ChapterBullet,
    YouTubeDetailedPayload,
    YouTubeStructuredPayload,
    _is_geographic_entity,
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


# ---- iter-20 regression: geographic entities must not be speakers -------- #


def test_geographic_entity_strait_of_hormuz_rejected():
    assert _is_geographic_entity("Strait of Hormuz")
    assert _is_geographic_entity("Gulf of Aden")
    assert _is_geographic_entity("Bay of Bengal")
    assert _is_geographic_entity("River Thames")
    assert _is_geographic_entity("Mount Everest")
    assert _is_geographic_entity("Lake Tahoe")
    assert _is_geographic_entity("The Persian Gulf")


def test_geographic_entity_does_not_flag_real_names():
    assert not _is_geographic_entity("Joe Rogan")
    assert not _is_geographic_entity("Rick Strassman")
    assert not _is_geographic_entity("CNBC")
    assert not _is_geographic_entity("Narrator")


def test_geographic_speaker_stripped_from_speakers_array():
    """Direct iter-20 replay: speakers=['Strait of Hormuz'] must not survive.

    Without entities_discussed fallback, the neutral label applies.
    """
    payload = _payload(
        speakers=["Strait of Hormuz"],
        entities=["Petrodollar system", "Yuan", "Patriot interceptor missiles"],
    )
    assert payload.speakers == ["The speaker"]


def test_geographic_speakers_mixed_with_real_name_keeps_only_real():
    """If Gemini emits ['Strait of Hormuz', 'Narrator', 'Joe Rogan'] the
    geographic entity is stripped, the role noun is stripped, and the
    real human is preserved.
    """
    payload = _payload(
        speakers=["Strait of Hormuz", "Gulf of Aden", "Narrator", "Joe Rogan"],
    )
    assert payload.speakers == ["Joe Rogan"]


def test_geographic_speakers_all_invalid_falls_through_to_entities():
    """When every speaker entry is a location, step-3 entity fallback runs."""
    payload = _payload(
        speakers=["Strait of Hormuz", "Gulf of Aden"],
        entities=["Petrodollar system", "Rick Strassman", "FDA"],
    )
    assert payload.speakers == ["Rick Strassman"]


def test_iter20_task_fixture_speakers_filtered():
    """Exact fixture from the iter-20 task description: geographic and
    role entries must be stripped, organization 'CNBC' preserved.
    """
    payload = _payload(
        speakers=["Strait of Hormuz", "Gulf of Aden", "Narrator", "CNBC"],
    )
    # 'Narrator' and geographic entities are stripped by _is_placeholder_speaker
    # and _is_geographic_entity respectively; 'CNBC' survives as an org name.
    assert payload.speakers == ["CNBC"]


def test_iter20_task_fixture_all_invalid_returns_neutral_label():
    """All-invalid input must produce the neutral label, never the bad strings."""
    payload = _payload(
        speakers=["Strait of Hormuz", "Gulf of Aden", "Mount Everest"],
        entities=[],
    )
    assert payload.speakers == ["The speaker"]
    assert "Strait of Hormuz" not in payload.speakers
