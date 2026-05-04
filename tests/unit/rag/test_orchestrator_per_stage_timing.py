"""iter-10 P17: per-stage timing surfaced via turn.token_counts.stage_timings.

Captures t_retrieval_ms, t_rerank_ms, t_synth_ms so iter-11 mid-flight abort
design has the data to pick safe abort points.
"""
import time

from website.features.rag_pipeline.orchestrator import _RetrievedContext


def test_retrieved_context_stores_per_stage_timings():
    ctx = _RetrievedContext(
        context_xml="<context></context>",
        used_candidates=[],
        t_retrieval_ms=42,
        t_rerank_ms=180,
    )
    assert ctx.t_retrieval_ms == 42
    assert ctx.t_rerank_ms == 180


def test_retrieved_context_default_timings_are_zero():
    """Backwards-compatible default — older tests don't pass timing."""
    ctx = _RetrievedContext(context_xml="<context></context>", used_candidates=[])
    assert ctx.t_retrieval_ms == 0
    assert ctx.t_rerank_ms == 0


def test_monotonic_ns_yields_nonnegative_ms():
    """Sanity for the t_synth_ms computation pattern used in _run_nonstream."""
    start = time.monotonic_ns()
    elapsed_ms = (time.monotonic_ns() - start) // 1_000_000
    assert elapsed_ms >= 0
