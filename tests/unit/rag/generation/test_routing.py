"""Spec 2C.1 / iter-03 plan §3.17: centralized Strong/Fast routing constants.

Verifies the (query_class, quality, force_pro) -> (model_chain, max_input,
max_output) lookup behaves per spec, especially the force_pro override and
the synthesis-class fast-forcing on quality="high".
"""

from __future__ import annotations

import pytest

from website.features.rag_pipeline.generation._routing import (
    ROUTING_TABLE,
    resolve_route,
    retrieval_top_k,
    use_critic,
    use_hyde,
)


# --- resolve_route -------------------------------------------------------


def test_lookup_high_uses_pro_first() -> None:
    chain, _max_in, _max_out = resolve_route("lookup", "high")
    assert chain[0] == "gemini-2.5-pro"
    assert "gemini-2.5-flash" in chain


def test_vague_high_uses_pro_first() -> None:
    chain, _max_in, _max_out = resolve_route("vague", "high")
    assert chain[0] == "gemini-2.5-pro"


def test_high_multi_hop_forced_to_fast_chain_no_pro() -> None:
    """Spec §3.17: MULTI_HOP on quality=high must NOT include Pro by default."""
    chain, _max_in, _max_out = resolve_route("multi_hop", "high")
    assert "gemini-2.5-pro" not in chain
    assert chain == ["gemini-2.5-flash"]


def test_high_thematic_forced_to_fast_chain_no_pro() -> None:
    chain, *_ = resolve_route("thematic", "high")
    assert "gemini-2.5-pro" not in chain


def test_high_step_back_forced_to_fast_chain_no_pro() -> None:
    chain, *_ = resolve_route("step_back", "high")
    assert "gemini-2.5-pro" not in chain


def test_force_pro_override_on_multi_hop_high() -> None:
    """``force_pro=True`` re-enables the Pro chain for synthesis-heavy classes
    on quality="high"."""
    chain, max_in, max_out = resolve_route("multi_hop", "high", force_pro=True)
    assert chain[0] == "gemini-2.5-pro"
    assert max_in == 8000 and max_out == 2000


def test_force_pro_ignored_on_fast_quality() -> None:
    """``force_pro=True`` is a no-op on quality="fast" — Fast tier never burns Pro."""
    chain, *_ = resolve_route("multi_hop", "fast", force_pro=True)
    assert "gemini-2.5-pro" not in chain


def test_force_pro_ignored_on_lookup_high() -> None:
    """``force_pro`` only applies to synthesis-heavy classes that were forced
    to fast — LOOKUP on high already gets Pro and is left untouched."""
    chain_with, *_ = resolve_route("lookup", "high", force_pro=True)
    chain_without, *_ = resolve_route("lookup", "high", force_pro=False)
    assert chain_with == chain_without


def test_lookup_fast_uses_flash_lite_only() -> None:
    chain, max_in, max_out = resolve_route("lookup", "fast")
    assert chain == ["gemini-2.5-flash-lite"]
    assert (max_in, max_out) == (1500, 800)


def test_vague_fast_uses_flash_with_4k_input() -> None:
    chain, max_in, max_out = resolve_route("vague", "fast")
    assert chain == ["gemini-2.5-flash"]
    assert (max_in, max_out) == (4000, 1200)


def test_routing_table_covers_all_class_quality_pairs() -> None:
    """Every (QueryClass, QualityMode) pair has an entry — no missing keys."""
    classes = ("lookup", "vague", "multi_hop", "thematic", "step_back")
    qualities = ("fast", "high")
    for c in classes:
        for q in qualities:
            assert (c, q) in ROUTING_TABLE


# --- pipeline toggles ---------------------------------------------------


def test_use_critic_only_on_high() -> None:
    assert use_critic("high") is True
    assert use_critic("fast") is False


def test_use_hyde_only_on_high_vague_or_multi_hop() -> None:
    assert use_hyde("high", "vague") is True
    assert use_hyde("high", "multi_hop") is True
    # Other classes on high: no HyDE.
    assert use_hyde("high", "lookup") is False
    assert use_hyde("high", "thematic") is False
    assert use_hyde("high", "step_back") is False
    # Fast mode: never HyDE.
    assert use_hyde("fast", "vague") is False
    assert use_hyde("fast", "multi_hop") is False


def test_retrieval_top_k_doubled_on_high() -> None:
    assert retrieval_top_k("high") == 40
    assert retrieval_top_k("fast") == 20


# --- regression guards --------------------------------------------------


@pytest.mark.parametrize(
    "synth_class",
    ["multi_hop", "thematic", "step_back"],
)
def test_synth_classes_max_tokens_match_fast_budget_on_high(synth_class) -> None:
    """Spec §3.17: even on high, forced-fast classes use the (6000, 1500)
    Fast-tier budget — NOT the (8000, 2000) Strong budget."""
    _chain, max_in, max_out = resolve_route(synth_class, "high")
    assert (max_in, max_out) == (6000, 1500)
