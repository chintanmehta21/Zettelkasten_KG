"""RAG_RRF_K env knob, single source of truth at BOTH fusion sites (E4 F2).

The Python re-fusion constant ``_RRF_K`` and the SQL RPC ``p_rrf_k`` must
read the SAME value (default 24, was 60; proposal docs/research/
e4_component_fix_proposal.md Finding 1). _RRF_K is resolved at import from
RAG_RRF_K, so the env assertion is done via a fresh module import.
"""
from __future__ import annotations

import importlib
import inspect

from website.features.rag_pipeline.retrieval import hybrid


def test_rrf_k_default_is_24():
    assert hybrid._RRF_K == 24.0


def test_rrf_k_honors_env_override(monkeypatch):
    monkeypatch.setenv("RAG_RRF_K", "37")
    mod = importlib.reload(hybrid)
    try:
        assert mod._RRF_K == 37.0
    finally:
        monkeypatch.delenv("RAG_RRF_K", raising=False)
        importlib.reload(hybrid)
    assert hybrid._RRF_K == 24.0


def test_sql_call_site_sends_same_rrf_k_constant():
    """The hybrid_search_chunks_kasten RPC payload must pass _RRF_K (not a
    hardcoded literal) for ``p_rrf_k`` so both fusion sites move together,
    and no in-function _RRF_K rebind may shadow the module knob."""
    full = inspect.getsource(hybrid)
    assert '"p_rrf_k": _RRF_K' in full, (
        "p_rrf_k must be driven by the _RRF_K env knob, not a literal"
    )
    assert '"p_rrf_k": 60' not in full
    # The old function-local `_RRF_K = 60.0` rebind must be gone so the
    # Python re-fusion site reads the module constant.
    assert "_RRF_K = 60" not in full
    assert full.count("_RRF_K =") == 1  # only the module-level definition
