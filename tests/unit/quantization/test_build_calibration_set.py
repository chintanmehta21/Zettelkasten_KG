"""Tests for the calibration-pair builder."""
from __future__ import annotations

import pandas as pd
import pytest

from ops.scripts.build_calibration_set import (
    QUERY_CLASSES,
    build_calibration_pairs,
    iter_03_eval_anchor_queries,
)

EXPECTED_PAIRS = 500
EXPECTED_PER_CLASS = 100  # 500 / 5 classes


@pytest.fixture
def fake_chunks_df() -> pd.DataFrame:
    rows = []
    for i in range(2000):
        rows.append({
            "chunk_id": f"c_{i}",
            "text": f"chunk text {i}",
            "source_type": ["github", "youtube", "reddit", "newsletter", "web"][i % 5],
        })
    return pd.DataFrame(rows)


def test_pair_count_is_500(fake_chunks_df):
    pairs = build_calibration_pairs(fake_chunks_df, seed=42)
    assert len(pairs) == EXPECTED_PAIRS


def test_balanced_per_class(fake_chunks_df):
    pairs = build_calibration_pairs(fake_chunks_df, seed=42)
    counts = pairs.groupby("query_class").size()
    for cls in QUERY_CLASSES:
        assert counts[cls] == EXPECTED_PER_CLASS, f"{cls} != {EXPECTED_PER_CLASS}"


def test_balanced_positive_negative(fake_chunks_df):
    pairs = build_calibration_pairs(fake_chunks_df, seed=42)
    pos = (pairs["label"] == 1).sum()
    neg = (pairs["label"] == 0).sum()
    assert pos == 250 and neg == 250


def test_iter_03_anchors_included(fake_chunks_df):
    """Every anchor query for a known class must appear in the produced pairs.

    When the live eval JSON files are unavailable in the test environment the
    builder synthesises one anchor per class. Either way, all anchor queries
    must surface in the calibration set.
    """
    pairs = build_calibration_pairs(fake_chunks_df, seed=42)
    pair_qs = set(pairs["query"].tolist())
    for anchor in iter_03_eval_anchor_queries():
        cls = anchor.get("query_class")
        if cls not in QUERY_CLASSES:
            continue
        assert anchor["query"] in pair_qs, f"missing anchor: {anchor['query']}"


def test_deterministic_with_seed(fake_chunks_df):
    p1 = build_calibration_pairs(fake_chunks_df, seed=42)
    p2 = build_calibration_pairs(fake_chunks_df, seed=42)
    pd.testing.assert_frame_equal(p1, p2)
