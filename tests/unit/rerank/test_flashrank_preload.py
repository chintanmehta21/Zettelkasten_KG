"""Iter-03 mem-bounded §2.5: FlashRank Ranker is built at module import so
gunicorn --preload + fork lets workers inherit the ~80 MB model via COW
instead of paying it private per-worker.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from website.features.rag_pipeline.rerank import cascade


def test_module_level_singleton_attribute_exists():
    assert hasattr(cascade, "_STAGE1_RANKER"), (
        "cascade.py must expose _STAGE1_RANKER at module scope (built at "
        "import) — see spec §2.5."
    )


def test_get_stage1_ranker_returns_module_singleton_when_present():
    fake_ranker = object()
    reranker = cascade.CascadeReranker(model_dir=None)
    with patch.object(cascade, "_STAGE1_RANKER", fake_ranker):
        result = reranker._get_stage1_ranker()
    assert result is fake_ranker, (
        "When the module-level singleton is loaded, _get_stage1_ranker MUST "
        "return it — not lazy-build a per-instance copy."
    )


def test_get_stage1_ranker_falls_back_when_singleton_missing(monkeypatch):
    """When _STAGE1_RANKER is None (test / smoke env without model files), the
    legacy per-instance lazy build path must still work so existing tests pass.
    """
    monkeypatch.setattr(cascade, "_STAGE1_RANKER", None)
    reranker = cascade.CascadeReranker(model_dir=None)
    fake_per_instance = object()

    def _fake_ranker_ctor(*args, **kwargs):
        return fake_per_instance

    with patch.object(cascade, "Ranker", _fake_ranker_ctor):
        result = reranker._get_stage1_ranker()

    assert result is fake_per_instance


def test_build_flashrank_ranker_returns_none_on_failure(tmp_path):
    # Force the helper to raise inside; the helper must swallow + return None
    # so import-time failures do NOT crash the whole app.
    def _explode(*_args, **_kwargs):
        raise RuntimeError("simulated cache-dir failure")

    with patch.object(cascade, "ModelManager", _explode):
        result = cascade._build_flashrank_ranker(tmp_path)
    assert result is None
