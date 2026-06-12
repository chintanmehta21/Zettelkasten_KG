# tests/unit/summarization_engine/summarization/test_youtube_attribution.py
"""Wave 1B: YouTube attribution gating, idempotent composer, format-verb map.

Pure deterministic string/threshold logic — NO model call, NO network.
"""
from __future__ import annotations

from website.features.summarization_engine.summarization.youtube.attribution import (
    reconcile_attribution_confidence,
)


def test_reconcile_all_real_names_is_high():
    assert reconcile_attribution_confidence(["Lex Fridman", "Andrej Karpathy"]) == "high"


def test_reconcile_mixed_real_and_placeholder_is_low():
    # one real + one placeholder/geographic survivor pattern -> "low"
    assert reconcile_attribution_confidence(["Lex Fridman", "the host"]) == "low"


def test_reconcile_all_placeholder_is_missing():
    assert reconcile_attribution_confidence(["the host", "narrator"]) == "missing"


def test_reconcile_sentinel_the_speaker_is_missing():
    assert reconcile_attribution_confidence(["The speaker"]) == "missing"


def test_reconcile_empty_is_missing():
    assert reconcile_attribution_confidence([]) == "missing"


# --- Task 2: canonical format label fold ----------------------------------
import pytest

from website.features.summarization_engine.summarization.youtube.attribution import (
    canonical_format,
)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("lecture", "lecture"),
        ("talk", "lecture"),
        ("tutorial", "explainer"),
        ("walkthrough", "explainer"),
        ("demo", "explainer"),
        ("explainer", "explainer"),
        ("commentary", "commentary"),
        ("review", "commentary"),
        ("reaction", "commentary"),
        ("debate", "commentary"),
        ("vlog", "commentary"),
        ("documentary", "documentary"),   # classifier-leaked label, NOT in Literal
        ("news", "news"),
        ("recap", "news"),
        ("interview", "interview"),
        ("discussion", "interview"),
        ("other", "unknown"),
        ("", "unknown"),
        ("ASMR-something-weird", "unknown"),
        ("  Commentary  ", "commentary"),  # case + whitespace tolerant
    ],
)
def test_canonical_format_folds_both_vocabularies(raw, expected):
    assert canonical_format(raw) == expected


def test_canonical_format_covers_every_literal_and_classifier_label():
    # No label from either vocabulary may fall through to a verb-map miss.
    from website.features.summarization_engine.summarization.youtube.format_classifier import (
        FORMAT_LABELS,
    )
    literal = ("tutorial", "interview", "commentary", "lecture", "review",
               "debate", "walkthrough", "reaction", "vlog", "other")
    for label in (*FORMAT_LABELS, *literal):
        key = canonical_format(label)
        assert key in {"lecture", "explainer", "commentary", "documentary", "news", "interview", "unknown"}
