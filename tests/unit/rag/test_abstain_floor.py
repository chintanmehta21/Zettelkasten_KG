"""F5 — calibrated pre-synthesis off-topic/insufficient-context abstention gate.

Spec: docs/research/e4_component_fix_proposal.md §Finding 5 (F5).

The gate lives in orchestrator._generate_once, immediately after the existing
NO_CONTEXT_MARKER early-refusal. It reads the cross-encoder's calibrated
sigmoid relevance prob (RetrievalCandidate.rerank_score, [0,1], None on RRF
fallback) and, when the top calibrated score sits below a conservative
per-class floor, either:

  * OBSERVE-ONLY (RAG_ABSTAIN_FLOOR_ENABLED unset/false, the shipped default):
    logs a structured ``rag_abstain_floor ... would_abstain=true`` line and
    proceeds to synthesis exactly as before (ZERO behavior change), or
  * ENABLED (RAG_ABSTAIN_FLOOR_ENABLED=true): returns the existing
    _empty_context_refusal() sink before the LLM call (eval refused=True).

Carve-outs (skip the gate entirely):
  * top score is None  -> reranker fell back to RRF (uncalibrated).
  * len(used_candidates) <= 1 -> cold-start (mirrors cascade min-keep).

Pure unit tests (no live, no model, no network) — they exercise the pure
decision helper plus one async drive of _generate_once with a fake LLM.
"""
from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from website.features.rag_pipeline.orchestrator import (
    REFUSAL_PHRASE,
    RAGOrchestrator,
    _abstain_floor_for_class,
    _abstain_floor_enabled,
    _evaluate_abstain_floor,
)
from website.features.rag_pipeline.types import QueryClass


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _cand(rerank_score):
    """Minimal stand-in for RetrievalCandidate (only rerank_score is read)."""
    return SimpleNamespace(rerank_score=rerank_score)


def _orchestrator_with_fake_llm():
    """Bare orchestrator whose LLM records whether generate() was called."""
    calls = {"n": 0}

    class _FakeLLM:
        async def generate(self, *, query, system_prompt, user_prompt):
            calls["n"] += 1
            return SimpleNamespace(
                content='synthesized answer [id="nid-1"]',
                model="fake",
                token_counts={"prompt": 1, "completion": 1, "total": 2},
                finish_reason="stop",
            )

    orch = RAGOrchestrator.__new__(RAGOrchestrator)
    orch._llm = _FakeLLM()
    return orch, calls


def _query():
    return SimpleNamespace(content="what is the tulip mania thesis?")


# ---------------------------------------------------------------------------
# pure decision helper — carve-outs & per-class floor
# ---------------------------------------------------------------------------
def test_a_all_off_topic_would_abstain_true():
    """(a) all candidates rerank ~0.05, >1 candidate, calibrated -> would_abstain."""
    decision = _evaluate_abstain_floor(
        [_cand(0.05), _cand(0.04), _cand(0.06)], QueryClass.LOOKUP
    )
    assert decision.evaluated is True
    assert decision.would_abstain is True
    assert decision.top == pytest.approx(0.06)


def test_b_one_relevant_among_off_topic_no_over_refusal():
    """(b) one relevant (0.7) among off-topic -> NOT would_abstain (answers)."""
    decision = _evaluate_abstain_floor(
        [_cand(0.05), _cand(0.7), _cand(0.04)], QueryClass.LOOKUP
    )
    assert decision.evaluated is True
    assert decision.would_abstain is False
    assert decision.top == pytest.approx(0.7)


def test_c_rrf_fallback_none_skips_gate():
    """(c) every rerank_score None (RRF fallback) -> gate skipped, never abstain."""
    decision = _evaluate_abstain_floor(
        [_cand(None), _cand(None), _cand(None)], QueryClass.LOOKUP
    )
    assert decision.evaluated is False
    assert decision.would_abstain is False
    assert decision.top is None


def test_d_single_candidate_skips_gate():
    """(d) <=1 candidate -> cold-start carve-out, gate skipped even if low."""
    decision = _evaluate_abstain_floor([_cand(0.01)], QueryClass.LOOKUP)
    assert decision.evaluated is False
    assert decision.would_abstain is False


def test_d_empty_candidates_skips_gate():
    """(d') zero candidates -> carve-out, gate skipped."""
    decision = _evaluate_abstain_floor([], QueryClass.LOOKUP)
    assert decision.evaluated is False
    assert decision.would_abstain is False


def test_mixed_none_uses_only_calibrated_scores():
    """A subset of None scores must NOT trip the None carve-out; the gate
    still evaluates using the calibrated subset (and >1 calibrated counts)."""
    decision = _evaluate_abstain_floor(
        [_cand(None), _cand(0.05), _cand(0.04)], QueryClass.LOOKUP
    )
    assert decision.evaluated is True
    assert decision.would_abstain is True
    assert decision.top == pytest.approx(0.05)


# ---------------------------------------------------------------------------
# (f) per-class floor honored from env
# ---------------------------------------------------------------------------
def _live_floor(cls: QueryClass) -> float:
    """Default floor derived from the live tuned cascade threshold table —
    keeps the test correct if tune_int8_thresholds.py re-tunes the values."""
    from website.features.rag_pipeline.rerank import cascade as _c

    t = _c._THRESHOLDS
    return 0.5 * float(t.get(cls.value, t.get("default", 0.50)))


def test_f_default_floor_is_half_class_threshold():
    """Default floor = 0.5 * cascade per-class ordering threshold.

    cascade LOOKUP threshold is currently 0.55 (tuned) -> floor 0.275.
    Asserted against the live table so a re-tune does not flake this.
    """
    assert _abstain_floor_for_class(QueryClass.LOOKUP) == pytest.approx(
        _live_floor(QueryClass.LOOKUP)
    )
    # And the spec invariant: floor is strictly below the ordering threshold.
    from website.features.rag_pipeline.rerank import cascade as _c

    assert _abstain_floor_for_class(QueryClass.LOOKUP) < _c._THRESHOLDS["lookup"]


def test_f_env_override_changes_boundary(monkeypatch):
    """RAG_ABSTAIN_FLOOR_LOOKUP override moves the decision boundary."""
    # Default LOOKUP floor 0.275; top=0.30 answers (0.30 >= 0.275).
    d_default = _evaluate_abstain_floor(
        [_cand(0.30), _cand(0.10)], QueryClass.LOOKUP
    )
    assert d_default.would_abstain is False

    # Raise the floor above 0.30 -> now the same top would abstain.
    monkeypatch.setenv("RAG_ABSTAIN_FLOOR_LOOKUP", "0.40")
    assert _abstain_floor_for_class(QueryClass.LOOKUP) == pytest.approx(0.40)
    d_override = _evaluate_abstain_floor(
        [_cand(0.30), _cand(0.10)], QueryClass.LOOKUP
    )
    assert d_override.would_abstain is True
    assert d_override.floor == pytest.approx(0.40)


def test_f_per_class_floors_are_independent(monkeypatch):
    """Overriding one class does not bleed into another class."""
    monkeypatch.setenv("RAG_ABSTAIN_FLOOR_VAGUE", "0.90")
    assert _abstain_floor_for_class(QueryClass.VAGUE) == pytest.approx(0.90)
    assert _abstain_floor_for_class(QueryClass.LOOKUP) == pytest.approx(
        _live_floor(QueryClass.LOOKUP)
    )


# ---------------------------------------------------------------------------
# master flag
# ---------------------------------------------------------------------------
def test_flag_default_is_observe_only(monkeypatch):
    monkeypatch.delenv("RAG_ABSTAIN_FLOOR_ENABLED", raising=False)
    assert _abstain_floor_enabled() is False


def test_flag_true_variants(monkeypatch):
    for v in ("true", "True", "1", "yes", "on"):
        monkeypatch.setenv("RAG_ABSTAIN_FLOOR_ENABLED", v)
        assert _abstain_floor_enabled() is True


# ---------------------------------------------------------------------------
# integration through _generate_once
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_enabled_all_off_topic_abstains_via_empty_context_refusal(monkeypatch):
    """(a) flag ON + all off-topic -> _generate_once short-circuits to the
    refusal sink WITHOUT calling the LLM."""
    monkeypatch.setenv("RAG_ABSTAIN_FLOOR_ENABLED", "true")
    orch, calls = _orchestrator_with_fake_llm()
    gen = await orch._generate_once(
        query=_query(),
        context_xml="<context><doc>off topic</doc></context>",
        used_candidates=[_cand(0.05), _cand(0.04), _cand(0.06)],
        query_class=QueryClass.LOOKUP,
    )
    assert gen.content == REFUSAL_PHRASE
    assert gen.finish_reason == "empty_context"
    assert calls["n"] == 0  # LLM never invoked — structurally prevents grounding


@pytest.mark.asyncio
async def test_enabled_one_relevant_answers(monkeypatch):
    """(b) flag ON + one relevant chunk -> proceeds to synthesis (no over-refusal)."""
    monkeypatch.setenv("RAG_ABSTAIN_FLOOR_ENABLED", "true")
    orch, calls = _orchestrator_with_fake_llm()
    gen = await orch._generate_once(
        query=_query(),
        context_xml="<context><doc>relevant</doc></context>",
        used_candidates=[_cand(0.05), _cand(0.7), _cand(0.04)],
        query_class=QueryClass.LOOKUP,
    )
    assert gen.content != REFUSAL_PHRASE
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_enabled_rrf_fallback_answers_regardless(monkeypatch):
    """(c) flag ON but rerank_score all None (RRF fallback) -> gate skipped,
    synthesis proceeds."""
    monkeypatch.setenv("RAG_ABSTAIN_FLOOR_ENABLED", "true")
    orch, calls = _orchestrator_with_fake_llm()
    gen = await orch._generate_once(
        query=_query(),
        context_xml="<context><doc>x</doc></context>",
        used_candidates=[_cand(None), _cand(None), _cand(None)],
        query_class=QueryClass.LOOKUP,
    )
    assert gen.content != REFUSAL_PHRASE
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_enabled_single_candidate_answers(monkeypatch):
    """(d) flag ON + <=1 candidate -> cold-start carve-out, synthesis proceeds."""
    monkeypatch.setenv("RAG_ABSTAIN_FLOOR_ENABLED", "true")
    orch, calls = _orchestrator_with_fake_llm()
    gen = await orch._generate_once(
        query=_query(),
        context_xml="<context><doc>x</doc></context>",
        used_candidates=[_cand(0.01)],
        query_class=QueryClass.LOOKUP,
    )
    assert gen.content != REFUSAL_PHRASE
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_observe_only_does_not_abstain_but_logs(monkeypatch, caplog):
    """(e) flag OFF (observe-only) + all off-topic -> does NOT abstain, the
    LLM IS called, but a would_abstain=true structured line is logged.
    Confirms ZERO behavior change is shipped by default."""
    monkeypatch.delenv("RAG_ABSTAIN_FLOOR_ENABLED", raising=False)
    orch, calls = _orchestrator_with_fake_llm()
    with caplog.at_level(logging.WARNING):
        gen = await orch._generate_once(
            query=_query(),
            context_xml="<context><doc>off topic</doc></context>",
            used_candidates=[_cand(0.05), _cand(0.04), _cand(0.06)],
            query_class=QueryClass.LOOKUP,
        )
    assert gen.content != REFUSAL_PHRASE  # behavior unchanged
    assert calls["n"] == 1  # LLM still called
    joined = " ".join(r.getMessage() for r in caplog.records)
    assert "rag_abstain_floor" in joined
    assert "would_abstain=true" in joined


@pytest.mark.asyncio
async def test_legacy_call_without_new_kwargs_is_unaffected(monkeypatch):
    """Backward compat: existing callers/tests that call _generate_once with
    only query+context_xml must keep working (gate skipped — no candidates)."""
    monkeypatch.setenv("RAG_ABSTAIN_FLOOR_ENABLED", "true")
    orch, calls = _orchestrator_with_fake_llm()
    gen = await orch._generate_once(
        query=_query(),
        context_xml="<context><doc>x</doc></context>",
    )
    assert gen.content != REFUSAL_PHRASE
    assert calls["n"] == 1
