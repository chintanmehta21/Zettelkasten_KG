"""Unit tests for ops.scripts.lib.calibration_spearman."""
from __future__ import annotations

import logging

import pytest

from ops.scripts.lib.calibration_spearman import (
    DEFAULT_WARN_THRESHOLD,
    InsufficientCalibrationData,
    check_calibration,
    compute_spearman,
)


def test_compute_spearman_perfect_positive_correlation():
    auto = [60.0, 70.0, 80.0, 90.0, 100.0]
    manual = [62.0, 71.0, 79.0, 88.0, 95.0]
    result = compute_spearman(auto, manual)
    assert result.n == 5
    assert result.rho == pytest.approx(1.0, abs=1e-9)


def test_compute_spearman_perfect_negative_correlation():
    auto = [60.0, 70.0, 80.0, 90.0, 100.0]
    manual = [95.0, 88.0, 79.0, 71.0, 62.0]
    result = compute_spearman(auto, manual)
    assert result.n == 5
    assert result.rho == pytest.approx(-1.0, abs=1e-9)


def test_compute_spearman_requires_at_least_two_pairs():
    with pytest.raises(InsufficientCalibrationData):
        compute_spearman([90.0], [91.0])


def test_compute_spearman_rejects_length_mismatch():
    with pytest.raises(ValueError, match="must align"):
        compute_spearman([90.0, 91.0, 92.0], [91.0, 92.0])


@pytest.mark.filterwarnings("ignore::scipy.stats.ConstantInputWarning")
def test_compute_spearman_zero_variance_raises():
    with pytest.raises(InsufficientCalibrationData):
        compute_spearman([90.0, 90.0, 90.0], [80.0, 82.0, 84.0])


def test_check_calibration_warns_when_rho_below_threshold(caplog):
    # Deliberately bad correlation: auto ascends, manual is shuffled so ranks
    # diverge strongly enough to drop rho below 0.6.
    auto =   [60.0, 70.0, 80.0, 90.0, 100.0]
    manual = [88.0, 62.0, 95.0, 71.0, 79.0]  # rho well below 0.6
    caplog.set_level(logging.WARNING, logger="ops.scripts.lib.calibration_spearman")
    result = check_calibration(auto, manual, source="reddit", threshold=DEFAULT_WARN_THRESHOLD)
    assert result is not None
    assert result.rho < DEFAULT_WARN_THRESHOLD
    # Must log a WARNING (never raise).
    warn_records = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any("calibration_spearman" in r.getMessage() for r in warn_records), caplog.text
    assert any("below threshold" in r.getMessage() for r in warn_records), caplog.text


def test_check_calibration_returns_none_on_insufficient_data(caplog):
    caplog.set_level(logging.WARNING, logger="ops.scripts.lib.calibration_spearman")
    result = check_calibration([90.0], [91.0], source="github")
    assert result is None
    # Must still log a warning naming the source so CI surfaces the gap.
    warn_records = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any("insufficient_data" in r.getMessage() for r in warn_records), caplog.text
