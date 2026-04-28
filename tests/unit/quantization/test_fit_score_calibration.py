"""Tests for the int8 score-calibration regressor."""
from __future__ import annotations

from ops.scripts.fit_score_calibration import fit_calibration


def test_calibration_outputs_a_b():
    int8_scores = [0.10, 0.20, 0.30, 0.40, 0.50, 0.60]
    fp32_scores = [0.12, 0.24, 0.36, 0.48, 0.60, 0.72]
    a, b = fit_calibration(int8_scores, fp32_scores)
    assert abs(a - 1.2) < 0.05
    assert abs(b - 0.0) < 0.05


def test_correction_recovers_fp32():
    int8_scores = [0.10, 0.20, 0.30, 0.40, 0.50, 0.60]
    fp32_scores = [0.12, 0.24, 0.36, 0.48, 0.60, 0.72]
    a, b = fit_calibration(int8_scores, fp32_scores)
    for i, expected in zip(int8_scores, fp32_scores):
        recovered = a * i + b
        assert abs(recovered - expected) < 0.02
