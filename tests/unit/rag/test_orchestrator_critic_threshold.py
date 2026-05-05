"""iter-11 Class F: class-conditional critic threshold (operator-approved
additive offset). LOOKUP / VAGUE keep the iter-08 floor literals
(_PARTIAL_NO_RETRY_FLOOR=0.5, _UNSUPPORTED_WITH_GOLD_SKIP_FLOOR=0.7).
THEMATIC / STEP_BACK can be tuned via env to lower the EFFECTIVE floor
(operator-approved iter-11 value -0.1 → effective 0.4 / 0.6). Hard-clamped
at 0.3 so the gate is never disabled outright.
"""
from __future__ import annotations

import os

import pytest

from website.features.rag_pipeline.orchestrator import (
    _effective_partial_floor,
    _effective_unsupported_with_gold_skip_floor,
)
from website.features.rag_pipeline.types import QueryClass


def test_lookup_keeps_default_floor():
    assert _effective_partial_floor(QueryClass.LOOKUP) == 0.5
    assert _effective_unsupported_with_gold_skip_floor(QueryClass.LOOKUP) == 0.7


def test_vague_keeps_default_floor():
    assert _effective_partial_floor(QueryClass.VAGUE) == 0.5
    assert _effective_unsupported_with_gold_skip_floor(QueryClass.VAGUE) == 0.7


def test_thematic_lowered_by_offset(monkeypatch):
    """Operator-approved iter-11 default offset is -0.1 → effective 0.4/0.6."""
    monkeypatch.setenv("RAG_PARTIAL_NO_RETRY_FLOOR_OFFSET_THEMATIC", "-0.1")
    monkeypatch.setenv("RAG_UNSUPPORTED_WITH_GOLD_SKIP_FLOOR_OFFSET_THEMATIC", "-0.1")
    assert _effective_partial_floor(QueryClass.THEMATIC) == pytest.approx(0.4)
    assert _effective_unsupported_with_gold_skip_floor(QueryClass.THEMATIC) == pytest.approx(0.6)


def test_step_back_uses_thematic_offset(monkeypatch):
    """STEP_BACK shares the cross-corpus synthesis pattern; same offset family."""
    monkeypatch.setenv("RAG_PARTIAL_NO_RETRY_FLOOR_OFFSET_THEMATIC", "-0.1")
    assert _effective_partial_floor(QueryClass.STEP_BACK) == pytest.approx(0.4)


def test_offset_respects_hard_clamp_minimum(monkeypatch):
    """Even with an extreme negative offset, never drop below 0.3 (the hard
    safety floor). Without this clamp, an env mistake could disable the gate."""
    monkeypatch.setenv("RAG_PARTIAL_NO_RETRY_FLOOR_OFFSET_THEMATIC", "-0.99")
    # 0.5 + (-0.99) = -0.49 → clamped to 0.3
    assert _effective_partial_floor(QueryClass.THEMATIC) == pytest.approx(0.3)


def test_lookup_offset_is_zero_even_if_env_set(monkeypatch):
    """The offset only applies to THEMATIC/STEP_BACK; LOOKUP MUST keep 0.5
    regardless of env (CLAUDE.md guardrail — LOOKUP floor literal is locked)."""
    monkeypatch.setenv("RAG_PARTIAL_NO_RETRY_FLOOR_OFFSET_THEMATIC", "-0.5")
    assert _effective_partial_floor(QueryClass.LOOKUP) == 0.5


def test_no_env_means_no_offset():
    """Default (env unset) is offset=0.0; effective floor equals literal."""
    # Make sure no offset env vars are set for this test.
    for k in (
        "RAG_PARTIAL_NO_RETRY_FLOOR_OFFSET_THEMATIC",
        "RAG_UNSUPPORTED_WITH_GOLD_SKIP_FLOOR_OFFSET_THEMATIC",
    ):
        os.environ.pop(k, None)
    assert _effective_partial_floor(QueryClass.THEMATIC) == 0.5
    assert _effective_unsupported_with_gold_skip_floor(QueryClass.THEMATIC) == 0.7
