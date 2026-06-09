"""Flip-metric logs (audit 2026-06-04) — watch these to decide when scale-gate
work trips: kg_graph_nodes (per-user node count) and kg_analytics_ms (igraph
wall-time). Observability only; no behavior change."""
from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient

from website.app import create_app


def test_graph_response_logs_node_count(caplog):
    with caplog.at_level(logging.INFO, logger="website.api"):
        with TestClient(create_app()) as client:
            resp = client.get("/api/graph", params={"view": "global"})
    assert resp.status_code == 200, resp.text
    assert any("kg_graph_nodes" in r.getMessage() for r in caplog.records), \
        "expected a kg_graph_nodes flip-metric log line"


def test_analytics_compute_logs_wall_time(caplog):
    """A fresh (unique) topology misses the metrics memo and computes igraph
    analytics, which must log kg_analytics_ms. Skips if igraph is unavailable."""
    from website.api.routes import _enrich_graph_with_analytics

    graph = {
        "nodes": [
            {"id": "ulo-a", "name": "A", "group": "web", "tags": []},
            {"id": "ulo-b", "name": "B", "group": "web", "tags": []},
        ],
        "links": [
            {"source": "ulo-a", "target": "ulo-b", "relation": "shared_tag",
             "connection_strength": 0.6},
        ],
    }
    with caplog.at_level(logging.INFO, logger="website.api"):
        out = _enrich_graph_with_analytics(graph, min_strength=None)
    if out.get("meta", {}).get("analytics_status") != "ok":
        pytest.skip("igraph analytics unavailable in this env")
    assert any("kg_analytics_ms" in r.getMessage() for r in caplog.records), \
        "expected a kg_analytics_ms flip-metric log line on a cache-miss compute"
