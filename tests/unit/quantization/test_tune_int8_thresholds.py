"""Tests for the per-class threshold grid-search helper."""
from __future__ import annotations

import numpy as np

from ops.scripts.tune_int8_thresholds import grid_search_threshold


def test_threshold_separates_well_separated_distributions():
    pos = np.array([0.7, 0.75, 0.8, 0.85, 0.9])
    neg = np.array([0.1, 0.15, 0.2, 0.25, 0.3])
    thr = grid_search_threshold(pos, neg)
    assert 0.30 <= thr <= 0.70, thr


def test_threshold_default_within_bounds():
    pos = np.array([0.4, 0.5, 0.6])
    neg = np.array([0.4, 0.5, 0.6])
    thr = grid_search_threshold(pos, neg)
    assert 0.05 <= thr <= 0.95
