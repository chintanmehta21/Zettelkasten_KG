"""Unit tests for _apply_min_strength_filter null-handling (LD-2)."""
from __future__ import annotations

from website.api.routes import _apply_min_strength_filter


def _payload(links):
    return {"nodes": [{"id": "a"}, {"id": "b"}], "links": links}


def test_no_threshold_returns_all_links():
    p = _payload([{"source": "a", "target": "b"}])
    assert _apply_min_strength_filter(p, None)["links"] == p["links"]


def test_zero_threshold_returns_all_links():
    p = _payload([{"source": "a", "target": "b"}])
    assert _apply_min_strength_filter(p, 0.0)["links"] == p["links"]


def test_null_connection_strength_passes_filter():
    """LD-2: missing connection_strength MUST be treated as visible by default."""
    p = _payload([
        {"source": "a", "target": "b", "connection_strength": None},
        {"source": "a", "target": "b", "connection_strength": 0.4},
    ])
    out = _apply_min_strength_filter(p, 0.5)
    # Null passes (visible-by-default); 0.4 is below threshold and culled.
    assert len(out["links"]) == 1
    assert out["links"][0].get("connection_strength") is None


def test_absent_key_treated_as_null():
    p = _payload([{"source": "a", "target": "b"}])  # no connection_strength key
    out = _apply_min_strength_filter(p, 0.5)
    assert len(out["links"]) == 1


def test_scored_link_below_threshold_still_culled():
    p = _payload([{"source": "a", "target": "b", "connection_strength": 0.49}])
    assert _apply_min_strength_filter(p, 0.5)["links"] == []


def test_scored_link_at_threshold_passes():
    p = _payload([{"source": "a", "target": "b", "connection_strength": 0.5}])
    assert len(_apply_min_strength_filter(p, 0.5)["links"]) == 1
