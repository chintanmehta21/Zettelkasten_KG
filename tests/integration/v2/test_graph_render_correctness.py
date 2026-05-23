"""Phase 1 acceptance: anonymous /api/graph returns non-zero links at default threshold."""
import pytest
from fastapi.testclient import TestClient

from website.app import create_app


@pytest.fixture(scope="module")
def client():
    return TestClient(create_app())


def test_anonymous_global_graph_has_links_at_default(client):
    """LD-1 + LD-2 + LD-3 combined: anon viewer must see edges on first paint."""
    resp = client.get("/api/graph?min_strength=0.30")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["nodes"]) > 0
    assert len(body["links"]) > 0, "LD-2 violation: anon viewer sees zero edges"


def test_anonymous_global_graph_has_links_even_at_strong_threshold(client):
    """LD-3: file-store edges backfilled to 1.0 must still appear at 0.7."""
    resp = client.get("/api/graph?min_strength=0.70")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["links"]) > 0, "LD-3 violation: file-store strong edges missing at 0.7"


def test_min_strength_above_one_returns_zero_links(client):
    """Sanity: a threshold above maximum strength culls everything."""
    resp = client.get("/api/graph?min_strength=1.5")
    assert resp.status_code == 200
    # File-store edges are exactly 1.0; threshold 1.5 should cull them.
    assert len(resp.json()["links"]) == 0
