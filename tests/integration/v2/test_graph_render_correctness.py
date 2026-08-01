"""Phase 1 acceptance: anonymous /api/graph returns non-zero links at default threshold.

Part B (Phase 1.5): Global is no longer the 29-node file-store seed — it is the
PUBLIC community graph, whose edges are the cross-user TAG BACKBONE
(content.community_graph_edges_v1, migration 90). The LD-1/LD-2/LD-3 intent is
unchanged — an anonymous viewer must see edges on first paint — but the fixture
now stubs the community repository instead of relying on file-store seed data,
so these assertions hold in CI where there is no Supabase.
"""
import pytest
from fastapi.testclient import TestClient

from website.app import create_app

# Two strong edges (1.0) and one mid edge (0.5), mirroring the real backbone's
# spread of IDF-cosine strengths so threshold behaviour is exercised.
_NODES = [
    {"id": "web-aaaaaaa1-000", "name": "Async Python", "group": "web",
     "url": "https://example.test/1", "author": "Naruto", "contributor_count": 1},
    {"id": "web-aaaaaaa2-000", "name": "Pydantic Models", "group": "web",
     "url": "https://example.test/2", "author": "Sasuke", "contributor_count": 1},
    {"id": "web-aaaaaaa3-000", "name": "Django ORM", "group": "web",
     "url": "https://example.test/3", "author": "Sakura", "contributor_count": 1},
]
_LINKS = [
    {"source": "web-aaaaaaa1-000", "target": "web-aaaaaaa2-000", "relation": "shared_tags",
     "weight": None, "link_type": "tag", "description": "2 shared tags",
     "connection_strength": 1.0},
    {"source": "web-aaaaaaa1-000", "target": "web-aaaaaaa3-000", "relation": "shared_tags",
     "weight": None, "link_type": "tag", "description": "1 shared tag",
     "connection_strength": 0.5},
]


class _StubCommunityRepo:
    def get_community_graph(self, *, limit=5000, min_strength=0.0):
        return {
            "nodes": [dict(n) for n in _NODES],
            "links": [dict(link) for link in _LINKS],
            "total_nodes": len(_NODES),
        }

    def read_cache_version(self) -> int:
        return 0


@pytest.fixture(scope="module")
def client():
    from website.api.module_runners import view_graph

    # K1 made the anon path share a singleton UserGraphCache; reset it so any
    # in-process stub-graph state planted by earlier unit tests doesn't bleed
    # into this integration smoke.
    from website.api.graph_cache import get_default_cache
    get_default_cache().invalidate("__anon__")
    get_default_cache().invalidate("__community__")

    original_repo = view_graph._community_repository
    original_gate = view_graph._use_supabase_v2
    # The global branch degrades to an empty graph when Supabase is
    # unconfigured (CI); force the gate on so the stub repo is reached.
    view_graph._use_supabase_v2 = lambda: True
    view_graph._community_repository = lambda: _StubCommunityRepo()
    try:
        yield TestClient(create_app())
    finally:
        view_graph._community_repository = original_repo
        view_graph._use_supabase_v2 = original_gate
        get_default_cache().invalidate("__community__")


def test_anonymous_global_graph_has_links_at_default(client):
    """LD-1 + LD-2 + LD-3 combined: anon viewer must see edges on first paint."""
    resp = client.get("/api/graph?min_strength=0.30")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["nodes"]) > 0
    assert len(body["links"]) > 0, "LD-2 violation: anon viewer sees zero edges"


def test_anonymous_global_graph_has_links_even_at_strong_threshold(client):
    """LD-3: strong community edges must still appear at 0.7."""
    resp = client.get("/api/graph?min_strength=0.70")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["links"]) > 0, "LD-3 violation: strong edges missing at 0.7"


def test_min_strength_above_one_returns_zero_links(client):
    """Sanity: a threshold above maximum strength culls everything."""
    resp = client.get("/api/graph?min_strength=1.5")
    assert resp.status_code == 200
    # Max community edge strength is 1.0; threshold 1.5 culls them all.
    assert len(resp.json()["links"]) == 0
