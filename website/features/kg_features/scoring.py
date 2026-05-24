"""WAVE-C 1c-A.2 — Multi-signal connection-strength scorer.

Pure functions only. No DB / no network / no global mutation. The scorer
combines four signals into a single ``connection_strength`` value in [0, 1]
per locked decision **D-KG-1** (Phase 3-α #operator-approved 2026-05-23)::

    score = 0.65 * embedding + 0.20 * tag + 0.10 * structural + 0.05 * temporal
    # fast-path: if cos >= 0.80, score = max(composite, 0.85)

History: original D-KG-1 was (0.55, 0.25, 0.15, 0.05). Phase 3-α rebalanced
to dense-leaning per 3-source convergence (8-agent dispatch + kg_fixes1
Deep Research + kg_fixes2 Perplexity) so semantic-only related pairs (high
cosine, no shared tags) cross the 0.50 creation threshold.

Locked thresholds:
- D-KG-2 edge-creation threshold: ``EDGE_CREATION_THRESHOLD = 0.50`` (>=)
  (B3: re-tuned from 0.55 after the raw-cosine clamp removed the (cos+1)/2
  compression; 0.50 keeps real related-pair edges while culling noise.)
- D-KG-3 edge-render threshold:   ``EDGE_RENDER_THRESHOLD = 0.7``    (>=)

Caller contract:
- ``embeddings``: ``{node_id: list[float]}``. Missing IDs / mismatched dims
  degrade the embedding signal to 0 silently — never raise.
- ``tags``:       ``{node_id: list[str]}``. Empty sets degrade the tag
  signal to 0 (Jaccard 0/0 → 0).
- ``structural``: ``{node_id: {neighbor_id: cooccurrence_count}}``. Missing
  IDs degrade to 0.
- ``temporal_days``: float, distance between node creation timestamps in
  days. Exponential decay; 0 days → 1.0; ~30 days → ~0.37.

Status: pure, and CALLED in production. Phase B (decision Q2) wired this
scorer into the KG-population hook: ``rag_pipeline.ingest.kg_population``
imports ``compute_connection_strength`` + ``EDGE_CREATION_THRESHOLD`` and
invokes it per candidate edge. That hook is the single sanctioned prod
importer (guarded by ``tests/unit/test_kg_features_unreachable.py``'s
``SCORING_ALLOWED`` allow-list). Kept per locked decision **D-KG-1**; its
purity (no DB / network / global state) is what makes it safe to call from
the per-edge create path.
"""
from __future__ import annotations

import math
from typing import Iterable, Mapping, Sequence

# ── Locked decisions (D-KG-1 / D-KG-2 / D-KG-3) ──────────────────────────────

WEIGHTS: dict[str, float] = {
    # Phase 3-α D-KG-1 rebalance (#operator-approved 2026-05-23):
    # Original 0.55 / 0.25 / 0.15 / 0.05 left dense-pair (no shared tags)
    # scores stuck just above the 0.50 creation threshold (cos=1.0 alone
    # gave 0.55 + tiny temporal ≈ 0.60). 3-source convergence (8-agent
    # dispatch + kg_fixes1 Deep Research + kg_fixes2 Perplexity, plus
    # GraphRAG / LightRAG 2024 precedent) recommended dense-leaning +
    # semantic fast-path. Operator approved this exact set in chat.
    "embedding": 0.65,
    "tag": 0.20,
    "structural": 0.10,
    "temporal": 0.05,
}

# Phase 3-α D-KG-1 fast-path: when embedding cosine alone is very high
# (>= 0.80), the pair is semantically near-identical and MUST create an
# edge regardless of tag/structural/temporal signals. Floor the composite
# at 0.85 so the resulting edge lands in the strong tier (>= 0.70 bucket)
# with margin. Plan-3-α + Garg 2024 25M-pair study (negative cosines
# <0.5%; cos>=0.80 is high-confidence related).
EMBEDDING_FAST_PATH_THRESHOLD: float = 0.80
EMBEDDING_FAST_PATH_FLOOR: float = 0.85

EDGE_CREATION_THRESHOLD: float = 0.50
EDGE_RENDER_THRESHOLD: float = 0.7

# Temporal half-life in days. exp(-days / 30) → ~0.37 at 30d, ~0.018 at 120d.
_TEMPORAL_HALFLIFE_DAYS: float = 30.0

__all__ = [
    "WEIGHTS",
    "EDGE_CREATION_THRESHOLD",
    "EDGE_RENDER_THRESHOLD",
    "compute_connection_strength",
]


# ── Per-signal kernels ──────────────────────────────────────────────────────


def _cosine_similarity(va: Sequence[float], vb: Sequence[float]) -> float:
    """Dim-mismatch / empty / zero-norm safe cosine sim clamped to [0, 1].

    LD-4: keep the ``max(0, cos)`` clamp for L2-normalized Gemini
    RETRIEVAL_DOCUMENT embeddings — per Garg 2024 25M-pair study, negative
    cosines are <0.5% of pairs in practice and rarely carry useful signal
    for our task type. Increment the negative-cosine counter so we can
    alert on model-version drift (threshold: >2% triggers operator alert).

    B3 history: the old ``(cos+1)/2`` affine rescale compressed the usable
    band (orthogonal→0.5, mild-related→0.55-0.70) so the composite
    degenerated. The raw-clamp keeps spread for tier discrimination.
    """
    if not va or not vb or len(va) != len(vb):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for ai, bi in zip(va, vb):
        dot += ai * bi
        na += ai * ai
        nb += bi * bi
    if na <= 0.0 or nb <= 0.0:
        return 0.0
    cos = dot / math.sqrt(na * nb)
    if math.isnan(cos):
        return 0.0

    # LD-4 telemetry: count every scored pair + count negatives separately.
    # Wrapped in try/except so telemetry can never break scoring (kg_metrics
    # degrades to a no-op when prometheus_client is missing).
    try:
        from website.core.kg_metrics import cosine_negative_total, cosine_pair_total
        cosine_pair_total.inc()
        if cos < 0.0:
            cosine_negative_total.inc()
    except Exception:  # pragma: no cover
        pass

    cos = max(-1.0, min(1.0, cos))
    return max(0.0, cos)


def _jaccard(set_a: Iterable[str], set_b: Iterable[str]) -> float | None:
    """Jaccard similarity on tag sets.

    M3: distinguishes three semantics so the caller can redistribute weight:
      - both empty            → 0.0 (no signal, but both sides agree)
      - exactly one empty     → None (signal-absent; caller redistributes weight)
      - both non-empty        → |inter| / |union|
    """
    sa = {t for t in set_a if t}
    sb = {t for t in set_b if t}
    if not sa and not sb:
        return 0.0
    if not sa or not sb:
        return None  # M3: signal-absent (not signal-zero)
    inter = len(sa & sb)
    union = len(sa | sb)
    if union == 0:
        return 0.0
    return inter / union


def _structural_signal(
    a: str,
    b: str,
    structural: Mapping[str, Mapping[str, int | float]],
) -> float:
    """Co-occurrence-based structural signal mapped to [0, 1].

    Reads the symmetric pair count ``structural[a][b]`` (falling back to
    ``structural[b][a]``) and squashes via ``count / (count + k)`` with
    ``k=2`` so a single co-occurrence registers, but the signal saturates
    smoothly above ~5 co-occurrences without ever exceeding 1.0.

    M5: accepts float-valued maps so the kg_population combiner can pass
    ``co + 0.5 * adamic_adar`` directly without rounding away fractional AA
    contributions on long-tail neighbours.
    """
    count_ab = structural.get(a, {}).get(b, 0) if structural else 0
    count_ba = structural.get(b, {}).get(a, 0) if structural else 0
    count = max(float(count_ab), float(count_ba))
    if count <= 0:
        return 0.0
    return count / (count + 2.0)


def _temporal_signal(temporal_days: float | None) -> float:
    """Exponential decay with ~30d half-life: ~0.967 same minute → ~0.37 @ 30d.

    M1: applies a minimum-age floor of 1.0 day so burst-ingest pairs don't
    score temporal=1.0 (saturating the signal on every new pair). exp(-1/30)
    ≈ 0.967 — still strong, no longer perfect.
    """
    if temporal_days is None:
        return 0.0
    days = max(1.0, float(temporal_days))  # M1: floor at 1.0d
    return math.exp(-days / _TEMPORAL_HALFLIFE_DAYS)


# ── Public API ──────────────────────────────────────────────────────────────


def compute_connection_strength(
    node_a: str,
    node_b: str,
    *,
    embeddings: Mapping[str, Sequence[float]] | None = None,
    tags: Mapping[str, Sequence[str]] | None = None,
    structural: Mapping[str, Mapping[str, int]] | None = None,
    temporal_days: float = 0.0,
) -> float:
    """Combined multi-signal connection score in [0, 1] per D-KG-1.

    Pure / deterministic: same inputs always produce the same output. Never
    raises on missing keys, dim mismatches, empty containers, or zero
    vectors — pathological inputs silently degrade the offending signal to
    0 so the caller can score every candidate pair without try/except.
    """
    embeddings = embeddings or {}
    tags = tags or {}
    structural = structural or {}

    emb = _cosine_similarity(
        list(embeddings.get(node_a, ())),
        list(embeddings.get(node_b, ())),
    )
    tag = _jaccard(tags.get(node_a, ()), tags.get(node_b, ()))
    struct = _structural_signal(node_a, node_b, structural)
    temp = _temporal_signal(temporal_days)

    # M3: when tag signal is signal-absent (asymmetric empty), redistribute
    # the tag weight proportionally over the remaining 3 signals so the
    # composite is not silently penalised by missing-side metadata.
    if tag is None:
        remaining_weight = 1.0 - WEIGHTS["tag"]
        score = (
            (WEIGHTS["embedding"] / remaining_weight) * emb
            + (WEIGHTS["structural"] / remaining_weight) * struct
            + (WEIGHTS["temporal"] / remaining_weight) * temp
        )
    else:
        score = (
            WEIGHTS["embedding"] * emb
            + WEIGHTS["tag"] * tag
            + WEIGHTS["structural"] * struct
            + WEIGHTS["temporal"] * temp
        )

    # Phase 3-α D-KG-1 fast-path (#operator-approved 2026-05-23):
    # Near-identical embeddings (cos >= 0.80) bypass the weight composition
    # — floor the composite at 0.85 so the edge always creates AND renders
    # in the strong tier. The "max" keeps a perfect-everything pair at its
    # higher composite if both signals fire.
    if emb >= EMBEDDING_FAST_PATH_THRESHOLD:
        score = max(score, EMBEDDING_FAST_PATH_FLOOR)

    # Defensive clamp — weights sum to 1.0 by construction so the result is
    # already in [0, 1], but guard against future weight edits + fast-path.
    return max(0.0, min(1.0, score))


