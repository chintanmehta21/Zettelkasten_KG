"""Iter-03 mem-bounded §2.3: ONNX arena + mem_pattern must default to off
in _build_ort_session so per-call working set does not leak into a
session-lifetime arena slab. See microsoft/onnxruntime#11627.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from website.features.rag_pipeline.rerank import cascade


class _CaptureOpts:
    """Stand-in for ort.SessionOptions that just records every assignment."""

    def __init__(self) -> None:
        self.intra_op_num_threads = None
        self.inter_op_num_threads = None
        self.graph_optimization_level = None
        self.enable_cpu_mem_arena = None
        self.enable_mem_pattern = None


def test_build_ort_session_disables_arena(tmp_path: Path):
    fake_path = tmp_path / "fake.onnx"
    fake_path.write_bytes(b"")  # exists, contents irrelevant — InferenceSession is mocked

    captured = _CaptureOpts()

    def _fake_session_options():
        return captured

    def _fake_inference_session(*_args, **_kwargs):
        return object()

    with patch.object(cascade.ort, "SessionOptions", _fake_session_options), \
         patch.object(cascade.ort, "InferenceSession", _fake_inference_session):
        result = cascade._build_ort_session(fake_path)

    assert result is not None
    assert captured.enable_cpu_mem_arena is False, \
        "arena MUST be off — see spec §2.3 / onnxruntime issue #11627"
    assert captured.enable_mem_pattern is False, \
        "mem_pattern MUST be off — no perf benefit on dynamic-shape inputs"
    assert captured.intra_op_num_threads == 1
    assert captured.inter_op_num_threads == 1


def test_build_ort_session_returns_none_when_path_missing(tmp_path: Path):
    missing = tmp_path / "nope.onnx"
    assert cascade._build_ort_session(missing) is None
