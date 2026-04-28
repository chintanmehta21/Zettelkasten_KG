"""Iter-03 §9: check_corpus_drift compares current Supabase corpus stats to
models/calibration_baseline.json. Returns YES + breached thresholds when any
of: chunk_count delta > 10%, source_type proportion delta > 5pp, embedding
centroid L2 distance > 0.05.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ops.scripts import check_corpus_drift as ccd


def _baseline(tmp: Path, *, chunk_count=1000, src_dist=None, centroid=None) -> Path:
    payload = {
        "calibrated_at": "2026-04-01",
        "corpus_stats": {
            "chunk_count": chunk_count,
            "source_type_distribution": src_dist or {"youtube": 0.4, "github": 0.3, "newsletter": 0.2, "web": 0.1},
            "embedding_centroid_l2": 0.0,
            "embedding_centroid": centroid or [0.0] * 8,
        },
        "drift_thresholds": {
            "chunk_count_pct_delta_max": 0.10,
            "source_type_proportion_pp_max": 0.05,
            "centroid_l2_max": 0.05,
        },
    }
    p = tmp / "calibration_baseline.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def test_no_drift_returns_false(tmp_path):
    baseline = _baseline(tmp_path)
    current = {
        "chunk_count": 1050,
        "source_type_distribution": {"youtube": 0.4, "github": 0.3, "newsletter": 0.2, "web": 0.1},
        "embedding_centroid": [0.0] * 8,
    }
    drifted, reasons = ccd.detect_drift(baseline_path=baseline, current_stats=current)
    assert drifted is False
    assert reasons == []


def test_chunk_count_drift(tmp_path):
    baseline = _baseline(tmp_path, chunk_count=1000)
    current = {
        "chunk_count": 1200,
        "source_type_distribution": {"youtube": 0.4, "github": 0.3, "newsletter": 0.2, "web": 0.1},
        "embedding_centroid": [0.0] * 8,
    }
    drifted, reasons = ccd.detect_drift(baseline_path=baseline, current_stats=current)
    assert drifted is True
    assert any("chunk_count" in r for r in reasons)


def test_source_type_drift(tmp_path):
    baseline = _baseline(tmp_path, src_dist={"youtube": 0.4, "github": 0.3, "newsletter": 0.2, "web": 0.1})
    current = {
        "chunk_count": 1000,
        "source_type_distribution": {"youtube": 0.5, "github": 0.2, "newsletter": 0.2, "web": 0.1},
        "embedding_centroid": [0.0] * 8,
    }
    drifted, reasons = ccd.detect_drift(baseline_path=baseline, current_stats=current)
    assert drifted is True
    assert any("source_type" in r for r in reasons)


def test_centroid_drift(tmp_path):
    baseline = _baseline(tmp_path, centroid=[0.0] * 8)
    current = {
        "chunk_count": 1000,
        "source_type_distribution": {"youtube": 0.4, "github": 0.3, "newsletter": 0.2, "web": 0.1},
        "embedding_centroid": [0.1] * 8,
    }
    drifted, reasons = ccd.detect_drift(baseline_path=baseline, current_stats=current)
    assert drifted is True
    assert any("centroid" in r for r in reasons)
