"""Iter-03 §9: refresh wrapper. Runs build_calibration_set + quantize_bge_int8
+ updates calibration_baseline.json with fresh sha256s + corpus_stats.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from ops.scripts import refresh_calibration_and_int8 as refresh


def test_refresh_runs_build_calibration_then_quantize_then_updates_baseline(tmp_path):
    parquet = tmp_path / "models" / "bge_calibration_pairs.parquet"
    onnx = tmp_path / "models" / "bge-reranker-base-int8.onnx"
    baseline = tmp_path / "models" / "calibration_baseline.json"
    parquet.parent.mkdir(parents=True)
    parquet.write_bytes(b"fake-parquet")
    onnx.write_bytes(b"fake-onnx")
    baseline.write_text(json.dumps({"corpus_stats": {}, "drift_thresholds": {}}), encoding="utf-8")

    calls = []

    def _fake_run(args, **kwargs):
        # Capture joined cmd string so substring membership checks work across
        # all elements (sys.executable + script path + flags).
        calls.append(" ".join(args))
        return 0

    fake_stats = {"chunk_count": 1234, "source_type_distribution": {"a": 1.0}, "embedding_centroid": [0.1] * 8}
    with patch.object(refresh, "_run_subprocess", _fake_run), \
         patch.object(refresh, "_pull_current_corpus_stats", lambda: fake_stats):
        rc = refresh.refresh(
            calibration_path=parquet,
            int8_path=onnx,
            baseline_path=baseline,
        )
    assert rc == 0
    assert any("build_calibration_set" in c for c in calls)
    assert any("quantize_bge_int8" in c for c in calls)
    payload = json.loads(baseline.read_text(encoding="utf-8"))
    assert payload["corpus_stats"]["chunk_count"] == 1234
    assert payload["calibration_parquet_sha256"].startswith("sha256:")
    assert payload["int8_onnx_sha256"].startswith("sha256:")
