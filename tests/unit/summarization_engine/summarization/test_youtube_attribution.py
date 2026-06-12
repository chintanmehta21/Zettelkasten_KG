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
