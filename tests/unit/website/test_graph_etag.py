"""GET /api/graph conditional-request + private-cache contract.

Ties the audit decision (docs/claude_audits/graph_loading_industry_research_2026-06-04.md):
- Per-user graph data MUST be `Cache-Control: private`. Cloudflare shipped async
  stale-while-revalidate on 2026-02-26 and would otherwise edge-cache and serve
  one user's graph to another (BOLA / data leak).
- A weak ETag + 304 collapses the 2-3 duplicate /api/graph fetches per visit.
- Weak comparison (RFC 7232) so a Cloudflare-stripped strong validator still 304s.

view=global is anonymous + deterministic (file-store), so no auth mocking needed.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from website.app import create_app


def _get(client, **headers):
    return client.get("/api/graph", params={"view": "global"}, headers=headers or None)


def test_graph_sets_private_cache_and_weak_etag():
    with TestClient(create_app()) as client:
        resp = _get(client)
    assert resp.status_code == 200, resp.text
    cc = resp.headers.get("cache-control", "")
    assert "private" in cc, f"per-user graph must be private; got {cc!r}"
    assert "max-age=30" in cc
    assert "stale-while-revalidate=300" in cc
    assert "public" not in cc, "graph must NEVER be public (CDN cross-user leak)"
    etag = resp.headers.get("etag", "")
    assert etag.startswith('W/"') and etag.endswith('"'), f"expected weak etag, got {etag!r}"


def test_graph_etag_304_roundtrip():
    with TestClient(create_app()) as client:
        first = _get(client)
        etag = first.headers["etag"]
        second = _get(client, **{"If-None-Match": etag})
    assert second.status_code == 304, second.text
    assert second.headers.get("etag") == etag
    cc = second.headers.get("cache-control", "")
    assert "private" in cc and "stale-while-revalidate=300" in cc


def test_graph_strong_inm_still_304s_under_weak_compare():
    """Cloudflare may echo our weak ETag back as its strong form; RFC 7232 weak
    comparison (shared if_none_match gate) must still 304 (mirrors /api/avatars)."""
    with TestClient(create_app()) as client:
        first = _get(client)
        weak = first.headers["etag"]      # W/"<hash>"
        strong = weak[2:]                  # "<hash>"
        second = _get(client, **{"If-None-Match": strong})
    assert second.status_code == 304, second.text
