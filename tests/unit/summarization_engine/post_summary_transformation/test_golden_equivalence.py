"""Proves migrated rules don't change behavior for the cases that already
worked. Real-speaker / normal Format must be byte-identical pre/post."""
from __future__ import annotations

from website.features.summarization_engine.summarization.youtube import layout as L


# ---------------------------------------------------------------------------
# Minimal stubs — _overview_section only reads .brief_summary,
# .detailed_summary.format, .detailed_summary.thesis, and .speakers.
# No Pydantic validation needed here.
# ---------------------------------------------------------------------------

class _D:
    """Stub for YouTubeDetailedPayload (only .format + .thesis accessed)."""
    def __init__(self, fmt: str, thesis: str = ""):
        self.format = fmt
        self.thesis = thesis


class _P:
    """Stub for YouTubeStructuredPayload (only .brief_summary, .detailed_summary, .speakers)."""
    def __init__(self, fmt: str, sp: list[str], brief: str = "A summary.", thesis: str = ""):
        self.detailed_summary = _D(fmt, thesis)
        self.speakers = sp
        self.brief_summary = brief


# ---------------------------------------------------------------------------
# 1. Real-speaker path: heading stays "Format and speakers", Speakers bullet present
# ---------------------------------------------------------------------------

def test_real_speaker_path_unchanged_heading_and_speakers():
    sec = L._overview_section(_P("interview", ["Lex Fridman"]))
    subs = sec.sub_sections
    assert "Format and speakers" in subs, (
        "real-speaker path must use 'Format and speakers' heading"
    )
    assert "Format" not in subs, (
        "real-speaker path must NOT emit a bare 'Format' heading"
    )
    assert any(b.startswith("Speakers: Lex Fridman") for b in subs["Format and speakers"]), (
        "real-speaker path must include Speakers: bullet"
    )


# ---------------------------------------------------------------------------
# 2. Generic-speaker path: heading becomes "Format", Speakers bullet dropped
# ---------------------------------------------------------------------------

def test_generic_speaker_drops_and_retitles():
    sec = L._overview_section(_P("lecture", ["The speaker"]))
    subs = sec.sub_sections
    assert "Format" in subs, (
        "generic-speaker path must retitle sub-section to 'Format'"
    )
    assert "Format and speakers" not in subs, (
        "generic-speaker path must NOT keep 'Format and speakers' heading"
    )
    assert not any(b.startswith("Speakers:") for b in subs["Format"]), (
        "generic-speaker path must drop the Speakers bullet"
    )


# ---------------------------------------------------------------------------
# 3. Format value: first letter capitalized (1b)
# ---------------------------------------------------------------------------

def test_format_value_first_letter_capitalized():
    # real-speaker path: Format value is capitalized
    sec = L._overview_section(_P("lecture", ["Lex Fridman"]))
    assert "Format: Lecture" in sec.sub_sections["Format and speakers"], (
        "Format value must have first letter capitalized (got lowercase 'lecture'?)"
    )
