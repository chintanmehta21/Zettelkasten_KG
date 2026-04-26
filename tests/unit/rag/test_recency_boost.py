"""Unit tests for the retrieval-side recency boost helper."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from website.features.rag_pipeline.retrieval.hybrid import _recency_boost
from website.features.rag_pipeline.types import QueryClass


def test_lookup_recent_doc_high_boost():
    md = {"timestamp": datetime.now(timezone.utc).isoformat()}
    assert _recency_boost(md, QueryClass.LOOKUP) > 0.09


def test_step_back_old_doc_zero_boost():
    md = {"timestamp": (datetime.now(timezone.utc) - timedelta(days=800)).isoformat()}
    assert _recency_boost(md, QueryClass.STEP_BACK) == 0.0


def test_no_timestamp_zero_boost():
    assert _recency_boost({}, QueryClass.LOOKUP) == 0.0


def test_none_metadata_zero_boost():
    assert _recency_boost(None, QueryClass.LOOKUP) == 0.0


def test_unparseable_timestamp_zero_boost():
    md = {"timestamp": "not-a-date"}
    assert _recency_boost(md, QueryClass.LOOKUP) == 0.0


def test_future_timestamp_zero_not_negative():
    md = {"timestamp": (datetime.now(timezone.utc) + timedelta(days=10)).isoformat()}
    boost = _recency_boost(md, QueryClass.LOOKUP)
    assert boost >= 0.0


def test_z_suffix_iso_parses():
    ts = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    md = {"timestamp": ts}
    assert _recency_boost(md, QueryClass.LOOKUP) > 0.09


def test_time_span_end_used_when_timestamp_missing():
    end = datetime.now(timezone.utc).isoformat()
    md = {"time_span": {"end": end}}
    assert _recency_boost(md, QueryClass.LOOKUP) > 0.09


def test_thematic_uses_lower_scale():
    md = {"timestamp": datetime.now(timezone.utc).isoformat()}
    lookup_boost = _recency_boost(md, QueryClass.LOOKUP)
    thematic_boost = _recency_boost(md, QueryClass.THEMATIC)
    # Thematic / multi-hop / step-back use the smaller 0.05 scale
    assert thematic_boost < lookup_boost
    assert thematic_boost > 0.04


def test_vague_uses_high_scale():
    md = {"timestamp": datetime.now(timezone.utc).isoformat()}
    assert _recency_boost(md, QueryClass.VAGUE) > 0.09


def test_boost_decays_with_age():
    fresh = {"timestamp": datetime.now(timezone.utc).isoformat()}
    midaged = {"timestamp": (datetime.now(timezone.utc) - timedelta(days=365)).isoformat()}
    assert _recency_boost(fresh, QueryClass.LOOKUP) > _recency_boost(midaged, QueryClass.LOOKUP)
    assert _recency_boost(midaged, QueryClass.LOOKUP) > 0.0


def test_boost_clamped_to_scale_max():
    """Boost magnitude must never exceed the per-class scale (0.10 for LOOKUP)."""
    md = {"timestamp": datetime.now(timezone.utc).isoformat()}
    assert _recency_boost(md, QueryClass.LOOKUP) <= 0.10 + 1e-9
