"""Tests for the int8-aware cascade reranker."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from website.features.rag_pipeline.rerank import cascade as cascade_mod
from website.features.rag_pipeline.rerank.cascade import (
    INT8_MODEL_PATH,
    CascadeReranker,
)


@pytest.fixture(autouse=True)
def _no_fp32_verify(monkeypatch):
    """Disable fp32 verifier for these unit tests so they don't try to load fp32."""
    monkeypatch.setenv("RAG_FP32_VERIFY", "off")


def test_cascade_uses_int8_model_path():
    cr = CascadeReranker()
    assert cr.stage2_model_path.endswith("bge-reranker-base-int8.onnx")


def test_score_calibration_applied():
    cr = CascadeReranker()
    raw = 0.50
    expected = cr._calibration_a * raw + cr._calibration_b
    assert abs(cr._apply_score_calibration(raw) - expected) < 1e-6


def test_per_class_threshold_lookup():
    cr = CascadeReranker()
    th = cr._threshold_for_class("lookup")
    assert th > 0.0
    th_default = cr._threshold_for_class("unknown_class")
    assert th_default > 0.0


def test_fp32_verify_disabled_by_env():
    os.environ["RAG_FP32_VERIFY"] = "off"
    cr = CascadeReranker()
    # With env=off the field is False regardless of session presence.
    assert cr._fp32_verify_enabled is False


@pytest.mark.skipif(
    not INT8_MODEL_PATH.exists(),
    reason="int8 ONNX not present - eager load skipped on this host",
)
def test_eager_load_at_import():
    """Spec 3.1: when the int8 model is on disk, gunicorn --preload must
    inherit the loaded session (i.e. _STAGE2_SESSION must already be set)."""
    assert cascade_mod._STAGE2_SESSION is not None


@pytest.mark.skipif(
    cascade_mod._STAGE2_SESSION is None,
    reason="stage-2 session unavailable - skipping TTA invocation test",
)
def test_strong_mode_test_time_augmentation():
    """Layer 7: high mode reranks twice (forward + reversed)."""
    cr = CascadeReranker()
    docs = [{"id": "a", "text": "doc a"}, {"id": "b", "text": "doc b"}]
    cr.score_batch("query", docs, mode="high")
    assert cr._tta_call_count_for_last_query >= 2


def test_score_batch_raises_when_int8_model_missing(monkeypatch):
    """When the int8 session is None, score_batch must surface a clear error."""
    monkeypatch.setattr(cascade_mod, "_STAGE2_SESSION", None)
    cr = CascadeReranker()
    with pytest.raises(RuntimeError, match="int8 stage-2 session is not loaded"):
        cr.score_batch("q", [{"id": "x", "text": "doc"}], mode="fast")
