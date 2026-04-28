"""Tests for the quantization validation gate."""
from __future__ import annotations

import numpy as np

from ops.scripts.validate_quantization import kl_divergence


def test_kl_zero_for_identical_distributions():
    rng = np.random.default_rng(42)
    a = rng.normal(0, 1, size=500)
    kl = kl_divergence(a, a)
    assert abs(kl) < 0.05


def test_kl_positive_for_shifted_distribution():
    rng = np.random.default_rng(42)
    a = rng.normal(0.0, 1.0, size=500)
    b = rng.normal(2.0, 1.0, size=500)
    kl = kl_divergence(a, b)
    assert kl > 0.05
