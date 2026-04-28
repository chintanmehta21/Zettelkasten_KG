"""Iter-03 §7: cascade.py must NOT lazily download/load fp32 BGE if int8
is missing. The image bakes int8 in; if it's gone, fail loud at first use
so deploy.sh's [stage2-assert] catches it pre-flip.

Removes the failure mode that defeated iter-03-stale: lazy ensure_bge_onnx_model
loaded the full 440 MB fp32 BGE per worker, ate 1 GB RSS, blew the cgroup.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from website.features.rag_pipeline.rerank import cascade


def test_get_stage2_session_returns_module_singleton_when_loaded():
    fake_session = object()
    reranker = cascade.CascadeReranker(model_dir=None)
    with patch.object(cascade, "_STAGE2_SESSION", fake_session):
        result = reranker._get_stage2_session()
    assert result is fake_session


def test_get_stage2_session_raises_when_singleton_missing():
    reranker = cascade.CascadeReranker(model_dir=None)
    with patch.object(cascade, "_STAGE2_SESSION", None):
        with pytest.raises(RuntimeError, match="int8"):
            reranker._get_stage2_session()


def test_get_stage2_tokenizer_returns_module_singleton_when_loaded():
    fake_tokenizer = object()
    reranker = cascade.CascadeReranker(model_dir=None)
    with patch.object(cascade, "_STAGE2_TOKENIZER", fake_tokenizer):
        result = reranker._get_stage2_tokenizer()
    assert result is fake_tokenizer


def test_get_stage2_tokenizer_raises_when_singleton_missing():
    reranker = cascade.CascadeReranker(model_dir=None)
    with patch.object(cascade, "_STAGE2_TOKENIZER", None):
        with pytest.raises(RuntimeError, match="tokenizer"):
            reranker._get_stage2_tokenizer()


def test_cascade_does_not_call_ensure_bge_onnx_model():
    """Hard guard: the lazy fp32 fallback path is gone entirely. ensure_bge_onnx_model
    must NOT appear in the cascade.py source — its presence was the silent foot-gun
    (both _get_stage2_session AND _get_stage2_tokenizer used it in iter-03-stale).
    """
    from pathlib import Path
    src = (Path(__file__).resolve().parents[4] / "website" / "features" / "rag_pipeline" / "rerank" / "cascade.py").read_text(encoding="utf-8")
    assert "ensure_bge_onnx_model" not in src, (
        "Iter-03 §7: ensure_bge_onnx_model must be ripped out of cascade.py. "
        "Both _get_stage2_session and _get_stage2_tokenizer must use the eager "
        "module-level singletons (_STAGE2_SESSION + _STAGE2_TOKENIZER)."
    )
