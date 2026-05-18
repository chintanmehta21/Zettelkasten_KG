"""Phase D — RAG retrieval adaptivity tests.

Covers:
  * P2-4 score-gap-margin RRF mixing (`_channel_gap`, `_gap_adapted_weights`,
    and the `_dedup_and_fuse` integration seam) with the HARD float-EXACT
    identity guarantee.
  * D4 dense-fallback-only candidate score-basis normalization.

`tests/unit/rag/retrieval/test_hybrid.py` is module-skipped (v1 RPC mocks
retired Phase 2.4.4-2.4.6); this file targets the Phase-D additions directly
against the pure helpers + the v2 `_dedup_and_fuse` path so the coverage runs.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from website.features.rag_pipeline.retrieval.hybrid import (
    HybridRetriever,
    _GAP_CLAMP_DELTA,
    _RRF_K,
    _channel_gap,
    _gap_adapted_weights,
)
from website.features.rag_pipeline.types import QueryClass

# E4 F2: the RRF k denominator is now the env-driven module knob (was a
# hardcoded 60). These identity tests assert Phase-D *behavior* (the static
# weight is returned float-EXACT), so derive the expected RRF term from the
# live _RRF_K constant instead of re-hardcoding a magic number. rank-1 -> K+1,
# rank-2 -> K+2.
_K1 = _RRF_K + 1.0
_K2 = _RRF_K + 2.0


class _RPCResult:
    def __init__(self, client, name, payload):
        self._client = client
        self._name = name
        self._payload = payload

    def execute(self):
        self._client.calls.append((self._name, self._payload))
        return SimpleNamespace(data=self._client.responses.get(self._name, []))


class _Supabase:
    def __init__(self, responses=None):
        self.responses = responses or {}
        self.calls = []

    def rpc(self, name, payload):
        return _RPCResult(self, name, payload)


class _Embedder:
    async def embed_query_with_cache(self, query):
        return [float(len(query))]


_STATIC_THEMATIC = (0.55, 0.20, 0.25)


# ---------------------------------------------------------------------------
# _channel_gap — normalized top1/top2 gap, clamped [0, 1]
# ---------------------------------------------------------------------------


def test_channel_gap_none_for_fewer_than_two():
    assert _channel_gap([]) is None
    assert _channel_gap([0.9]) is None
    assert _channel_gap(None) is None


def test_channel_gap_peaked_channel_high_gap():
    # s1=1.0, s2=0.1 -> (1.0-0.1)/(1.0+eps) ~= 0.9
    gap = _channel_gap([0.1, 1.0, 0.05])
    assert gap == pytest.approx(0.9, abs=1e-6)


def test_channel_gap_flat_channel_zero_gap():
    # All equal -> s1==s2 -> gap == 0.0 exactly.
    assert _channel_gap([0.5, 0.5, 0.5]) == 0.0


def test_channel_gap_clamped_unit_interval():
    g = _channel_gap([0.0, 0.0])  # 0/eps -> 0.0
    assert 0.0 <= g <= 1.0


# ---------------------------------------------------------------------------
# _gap_adapted_weights — HARD float-EXACT identity guarantee
# ---------------------------------------------------------------------------


def test_identity_when_all_gaps_none():
    """Empty pool / no per-channel signal -> weights returned UNCHANGED."""
    out = _gap_adapted_weights(_STATIC_THEMATIC, (None, None, None))
    assert out == _STATIC_THEMATIC
    assert out is _STATIC_THEMATIC  # same object — provably no arithmetic ran


def test_identity_when_fewer_than_two_present():
    out = _gap_adapted_weights(_STATIC_THEMATIC, (0.7, None, None))
    assert out is _STATIC_THEMATIC


def test_identity_when_all_present_gaps_equal():
    """Degenerate: every present gap identical -> float-EXACT static tuple."""
    out = _gap_adapted_weights(_STATIC_THEMATIC, (0.4, 0.4, 0.4))
    assert out is _STATIC_THEMATIC
    out2 = _gap_adapted_weights(_STATIC_THEMATIC, (0.4, 0.4, None))
    assert out2 is _STATIC_THEMATIC


def test_peaked_channel_shifts_within_clamp_and_renormalizes():
    # sem decisive (gap 0.9), fts/graph flat-ish (0.1) -> sem up-weighted.
    out = _gap_adapted_weights(_STATIC_THEMATIC, (0.9, 0.1, 0.1))
    assert out != _STATIC_THEMATIC
    # Sum preserved (renormalized to Σ static).
    assert sum(out) == pytest.approx(sum(_STATIC_THEMATIC), abs=1e-9)
    # sem share rises, fts/graph shares fall.
    assert out[0] > _STATIC_THEMATIC[0]
    assert out[1] < _STATIC_THEMATIC[1]
    assert out[2] < _STATIC_THEMATIC[2]
    # Per-channel modifier never exceeds the clamp band [1-Δ, 1+Δ].
    for w_new, w_old in zip(out, _STATIC_THEMATIC):
        ratio = w_new / w_old
        # Renormalization can push the *post-scale* ratio slightly past the
        # raw modifier clamp, but never beyond (1+Δ)/(1-Δ) bounds overall.
        assert (1.0 - _GAP_CLAMP_DELTA) * 0.5 < ratio < (1.0 + _GAP_CLAMP_DELTA) * 1.5


def test_modifier_clamp_caps_extreme_divergence():
    """gap span 0 -> 1 still bounded by the ±Δ clamp on the raw modifier."""
    out = _gap_adapted_weights((0.4, 0.3, 0.3), (1.0, 0.0, 0.0))
    assert sum(out) == pytest.approx(1.0, abs=1e-9)
    # No weight can more than ~ (1+Δ)/(1-Δ) its neighbour purely from the modifier.
    assert all(w > 0 for w in out)


def test_none_channel_weight_passes_through_unscaled_pre_renorm():
    """A channel with no gap keeps its raw weight before renormalization."""
    out = _gap_adapted_weights((0.5, 0.3, 0.2), (0.9, 0.1, None))
    assert sum(out) == pytest.approx(1.0, abs=1e-9)


# ---------------------------------------------------------------------------
# _dedup_and_fuse integration — identity on degenerate pools, shift on peaked
# ---------------------------------------------------------------------------


def _row(
    node_id, sem_rank=None, fts_rank=None, rrf=0.0, dense=None, fts=None,
    dense_fallback=False,
):
    return {
        "kind": "chunk",
        "node_id": node_id,
        "chunk_id": None,
        "chunk_idx": 0,
        "name": node_id,
        "title": node_id,
        "source_type": "web",
        "url": "u",
        "content": "c",
        "tags": [],
        # Phase D D4: the fusion path scopes the RRF-basis normalization to
        # candidates explicitly tagged by the dense-fallback adapter.
        "metadata": {"_dense_fallback": True} if dense_fallback else {},
        "rrf_score": rrf,
        "semantic_rank": sem_rank,
        "fts_rank": fts_rank,
        "raw_dense_score": dense,
        "raw_fts_score": fts,
    }


def test_dedup_and_fuse_empty_pool_is_identity():
    """No candidates -> nothing to fuse; no crash, empty result."""
    retriever = HybridRetriever(embedder=_Embedder(), supabase=_Supabase())
    fused = retriever._dedup_and_fuse([[]], query_variants=["q"])
    assert fused == []


def test_dedup_and_fuse_single_channel_only_is_weight_identity():
    """Only ONE channel has >=2 candidates -> <2 present gaps -> identity.

    Two candidates, sem-only ranks. fts/graph channels absent -> _gaps has a
    single present entry -> _gap_adapted_weights returns the static tuple
    float-EXACT, so each candidate's rrf == sem_weight * 1/(K+rank) with the
    UNMODIFIED static sem_weight.
    """
    retriever = HybridRetriever(embedder=_Embedder(), supabase=_Supabase())
    rows = [
        _row("a", sem_rank=1, dense=0.9),
        _row("b", sem_rank=2, dense=0.1),
    ]
    fused = retriever._dedup_and_fuse(
        [rows], query_variants=["q"], query_class=QueryClass.THEMATIC,
        sem_weight=0.55, fts_weight=0.20, graph_weight=0.25,
    )
    by_id = {c.node_id: c for c in fused}
    # Static sem_weight 0.55 unmodified (identity): rrf == 0.55/(K+rank).
    assert by_id["a"].metadata["_base_rrf_score"] == pytest.approx(
        0.55 * (1.0 / _K1), abs=1e-12
    )
    assert by_id["b"].metadata["_base_rrf_score"] == pytest.approx(
        0.55 * (1.0 / _K2), abs=1e-12
    )


def test_dedup_and_fuse_two_channels_peaked_shifts_weights():
    """sem peaked + fts present (2 channels) -> modifier engages, Σw preserved.

    We assert the fused sem contribution is STRICTLY greater than the static
    identity value for the rank-1 sem candidate (sem up-weighted), proving the
    modifier fired without changing the RPC payload path.
    """
    retriever = HybridRetriever(embedder=_Embedder(), supabase=_Supabase())
    # sem: peaked (dense 0.99 vs 0.02). fts: flat (0.5 vs 0.49).
    rows = [
        _row("a", sem_rank=1, fts_rank=2, dense=0.99, fts=0.50),
        _row("b", sem_rank=2, fts_rank=1, dense=0.02, fts=0.49),
    ]
    fused = retriever._dedup_and_fuse(
        [rows], query_variants=["q"], query_class=QueryClass.THEMATIC,
        sem_weight=0.55, fts_weight=0.20, graph_weight=0.25,
    )
    by_id = {c.node_id: c for c in fused}
    # Identity baseline for "a": 0.55/(K+1) + 0.20/(K+2).
    identity_a = 0.55 * (1.0 / _K1) + 0.20 * (1.0 / _K2)
    assert by_id["a"].metadata["_base_rrf_score"] > identity_a
    # Both candidates fused (no drop), scores finite & positive.
    assert all(c.metadata["_base_rrf_score"] > 0 for c in fused)


# ---------------------------------------------------------------------------
# D4 — dense-fallback-only candidates normalized onto the RRF score basis
# ---------------------------------------------------------------------------


def test_d4_fallback_only_candidates_use_rrf_basis():
    """Fallback rows (cosine rrf_score, NO per-source ranks) must be rescaled
    onto the same ~1/(K+rank) basis as normal candidates, not left on the
    raw cosine scale."""
    retriever = HybridRetriever(embedder=_Embedder(), supabase=_Supabase())
    # Dense-fallback path: tagged rows, cosine in rrf_score, no per-source rank.
    rows = [
        _row("fb1", rrf=0.92, dense=0.92, dense_fallback=True),
        _row("fb2", rrf=0.40, dense=0.40, dense_fallback=True),
    ]
    fused = retriever._dedup_and_fuse([rows], query_variants=["q"])
    by_id = {c.node_id: c for c in fused}
    # Pre-D4 these stayed at the cosine 0.92 / 0.40. Post-D4 they fuse on the
    # sem-channel RRF term with synthesized dense rank (1, 2) at default
    # sem_weight 0.5: 0.5/(K+1) and 0.5/(K+2).
    assert by_id["fb1"].metadata["_base_rrf_score"] == pytest.approx(
        0.5 * (1.0 / _K1), abs=1e-9
    )
    assert by_id["fb2"].metadata["_base_rrf_score"] == pytest.approx(
        0.5 * (1.0 / _K2), abs=1e-9
    )
    # Ordering preserved (higher cosine -> better synthesized rank -> higher rrf).
    assert (
        by_id["fb1"].metadata["_base_rrf_score"]
        > by_id["fb2"].metadata["_base_rrf_score"]
    )


def test_d4_does_not_touch_normal_ranked_candidates():
    """Candidates WITH per-source ranks are byte-identical to pre-D4 (the
    fallback-rank synthesis must not fire for them)."""
    retriever = HybridRetriever(embedder=_Embedder(), supabase=_Supabase())
    rows = [
        _row("n1", sem_rank=1, dense=0.9),
        _row("n2", sem_rank=2, dense=0.8),
    ]
    fused = retriever._dedup_and_fuse(
        [rows], query_variants=["q"], query_class=QueryClass.LOOKUP,
        sem_weight=0.35, fts_weight=0.50, graph_weight=0.15,
    )
    by_id = {c.node_id: c for c in fused}
    # Pure sem-channel RRF, static identity weight (single channel -> identity).
    assert by_id["n1"].metadata["_base_rrf_score"] == pytest.approx(
        0.35 * (1.0 / _K1), abs=1e-12
    )
    assert by_id["n2"].metadata["_base_rrf_score"] == pytest.approx(
        0.35 * (1.0 / _K2), abs=1e-12
    )


def test_d4_untagged_rankless_rows_byte_identical_to_pre_phase_d():
    """REGRESSION GUARD: rank-less rows that are NOT dense-fallback (no
    _dense_fallback marker — e.g. SQL-only stub rows, the class-x-source
    baseline fixtures) must keep their raw SQL rrf_score exactly as pre-Phase-D
    (the D4 synthesis must NOT reclassify them)."""
    retriever = HybridRetriever(embedder=_Embedder(), supabase=_Supabase())
    rows = [
        _row("s1", rrf=0.55),  # no ranks, no _dense_fallback marker
        _row("s2", rrf=0.40),
    ]
    fused = retriever._dedup_and_fuse(
        [rows], query_variants=["q"], query_class=QueryClass.THEMATIC,
    )
    by_id = {c.node_id: c for c in fused}
    # Untouched: rrf stays the raw SQL score; _base_rrf_score mirrors it.
    assert by_id["s1"].rrf_score == pytest.approx(0.55, abs=1e-12)
    assert by_id["s2"].rrf_score == pytest.approx(0.40, abs=1e-12)
    assert by_id["s1"].metadata["_base_rrf_score"] == pytest.approx(0.55, abs=1e-12)
    assert by_id["s2"].metadata["_base_rrf_score"] == pytest.approx(0.40, abs=1e-12)
