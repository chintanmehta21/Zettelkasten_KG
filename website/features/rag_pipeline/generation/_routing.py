"""Token-conscious Strong/Fast routing for generation (spec §3.17).

Centralizes the (query_class, quality_mode) -> (model_chain, max_input_tokens,
max_output_tokens) table that was previously scattered across the orchestrator
and gemini_backend. Exposes pure helpers (``resolve_route``, ``use_critic``,
``use_hyde``, ``retrieval_top_k``) so callers can adopt them incrementally
without touching the orchestrator's tier-selection logic.

Spec §3.17 / iter-03 plan §2C.1 invariants:
    - LOOKUP / VAGUE on quality="high" -> Pro-first, Flash fallback (8000/2000).
    - MULTI_HOP / THEMATIC / STEP_BACK on quality="high" are FORCED to the
      fast Flash chain (6000/1500) unless ``force_pro=True`` is passed
      explicitly. This protects Pro quota and forbids accidental Pro burn on
      synthesis-heavy classes.
    - quality="fast" never hits Pro.
    - LOOKUP on quality="fast" gets the smallest budget + flash-lite first
      (1500/800) — content-aware routing reserves Flash quota for VAGUE+ classes.
"""

from __future__ import annotations

from typing import Literal

QualityMode = Literal["fast", "high"]
QueryClass = Literal["lookup", "vague", "multi_hop", "thematic", "step_back"]

# (model_chain, max_input_tokens, max_output_tokens)
RouteTuple = tuple[list[str], int, int]


# Note: the table is the single source of truth. ``resolve_route`` is the only
# public lookup — do NOT read this dict directly from outside this module so
# that the force_pro override stays centralized.
ROUTING_TABLE: dict[tuple[QueryClass, QualityMode], RouteTuple] = {
    # ---- Fast tier ----
    ("lookup", "fast"):    (["gemini-2.5-flash-lite"],                 1500, 800),
    ("vague", "fast"):     (["gemini-2.5-flash"],                      4000, 1200),
    ("multi_hop", "fast"): (["gemini-2.5-flash"],                      6000, 1500),
    ("thematic", "fast"):  (["gemini-2.5-flash"],                      6000, 1500),
    ("step_back", "fast"): (["gemini-2.5-flash"],                      6000, 1500),
    # ---- High (Strong) tier ----
    ("lookup", "high"):    (["gemini-2.5-pro", "gemini-2.5-flash"],    8000, 2000),
    ("vague", "high"):     (["gemini-2.5-pro", "gemini-2.5-flash"],    8000, 2000),
    # NOTE: synthesis-heavy classes are FORCED to fast on "high" unless
    # force_pro=True. See spec §3.17 — protects Pro quota.
    ("multi_hop", "high"): (["gemini-2.5-flash"],                      6000, 1500),
    ("thematic", "high"):  (["gemini-2.5-flash"],                      6000, 1500),
    ("step_back", "high"): (["gemini-2.5-flash"],                      6000, 1500),
}


_FORCE_PRO_HIGH_ROUTE: RouteTuple = (
    ["gemini-2.5-pro", "gemini-2.5-flash"],
    8000,
    2000,
)


_FORCE_PRO_ELIGIBLE_CLASSES: frozenset[QueryClass] = frozenset(
    {"multi_hop", "thematic", "step_back"}
)


def resolve_route(
    query_class: QueryClass,
    quality: QualityMode,
    *,
    force_pro: bool = False,
) -> RouteTuple:
    """Return the (model_chain, max_input_tokens, max_output_tokens) tuple for
    a given (class, quality) pair.

    ``force_pro=True`` only has an effect on quality="high" + a synthesis-heavy
    class. All other cases follow ``ROUTING_TABLE`` exactly.

    Raises ``KeyError`` only if the (class, quality) pair is missing from the
    table, which would indicate a programmer error (no caller should ever
    pass an unsupported combination).
    """
    if (
        force_pro
        and quality == "high"
        and query_class in _FORCE_PRO_ELIGIBLE_CLASSES
    ):
        return _FORCE_PRO_HIGH_ROUTE
    return ROUTING_TABLE[(query_class, quality)]


# ---- Strong-mode pipeline toggles (spec §3.8) ----------------------------
#
# These helpers tell callers which expensive pipeline stages to enable per
# quality tier. Centralized here so adopters don't re-derive the logic.


def use_critic(quality: QualityMode) -> bool:
    """Critic verification only runs on Strong (``high``) mode. Fast mode
    skips it to preserve LLM quota and latency."""
    return quality == "high"


def use_hyde(quality: QualityMode, query_class: QueryClass) -> bool:
    """HyDE (hypothetical document embedding) only runs on Strong mode for
    classes that benefit most from query expansion: VAGUE and MULTI_HOP."""
    return quality == "high" and query_class in ("vague", "multi_hop")


def retrieval_top_k(quality: QualityMode) -> int:
    """Retrieval depth — Strong mode pulls more candidates so the reranker
    has a wider pool. Fast mode caps at the legacy default."""
    return 40 if quality == "high" else 20
