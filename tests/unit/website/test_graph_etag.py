"""GET /api/graph conditional-request + cache contract.

Ties the audit decision (docs/claude_audits/graph_loading_industry_research_2026-06-04.md):
- A weak ETag + 304 collapses the 2-3 duplicate /api/graph fetches per visit.
- Weak comparison (RFC 7232) so a Cloudflare-stripped strong validator still 304s.

CONTRACT CHANGE (Community Graph Part B, design D6/D7 — operator-approved
2026-06-16): ``view=global`` is no longer per-user data. It is the PUBLIC
community graph — deduped by canonical, ``user_id`` stripped at the DB layer,
built only from ``is_private = false`` rows — so it is deliberately served
``public, s-maxage=300, stale-while-revalidate`` and is CDN-cacheable.

The original "graph must NEVER be public (CDN cross-user leak)" assertion was
written when ``/api/graph`` served per-user data on this path. Rather than drop
that protection, it is REPLACED by the two conditions that actually make public
edge-caching safe, asserted below:
  1. the public response carries ZERO ``Set-Cookie`` (otherwise Cloudflare
     BYPASSes, and any per-user token could be cached alongside the body), and
  2. the payload carries no user identifiers.
Per-user data now lives on ``view=my``, which stays ``private, no-store`` and
hard-401s without auth (see test_graph_my_hard_401.py).
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from website.app import create_app


def _get(client, **headers):
    return client.get("/api/graph", params={"view": "global"}, headers=headers or None)


def test_global_graph_is_publicly_cacheable_with_weak_etag():
    with TestClient(create_app()) as client:
        resp = _get(client)
    assert resp.status_code == 200, resp.text
    cc = resp.headers.get("cache-control", "")
    assert "public" in cc, f"community graph is public by design (D6); got {cc!r}"
    assert "s-maxage=300" in cc
    assert "stale-while-revalidate" in cc
    assert "private" not in cc, "view=global must not claim private (it is shared)"
    etag = resp.headers.get("etag", "")
    assert etag.startswith('W/"') and etag.endswith('"'), f"expected weak etag, got {etag!r}"


def test_public_graph_sets_no_cookie_and_leaks_no_user_identifiers():
    """The conditions that make CDN edge-caching of view=global safe (D6).

    This is the replacement for the old "never public" assertion — it guards the
    same risk (a shared cache serving one user's data to another) at the point
    where it can actually occur now.
    """
    with TestClient(create_app()) as client:
        resp = _get(client)
    assert resp.status_code == 200, resp.text
    assert "set-cookie" not in {k.lower() for k in resp.headers}, (
        "view=global must emit ZERO Set-Cookie — a cookie on a public, "
        "CDN-cached response is a cross-user leak (and makes Cloudflare BYPASS)"
    )
    vary = resp.headers.get("vary", "")
    assert "authorization" not in vary.lower(), (
        "Cloudflare honours only Vary: Accept-Encoding; relying on "
        "Vary: Authorization can leak a private response to anonymous (D7)"
    )
    body = resp.json()
    for node in body.get("nodes", []):
        assert "user_id" not in node and "owner_profile_id" not in node


def test_graph_etag_304_roundtrip():
    with TestClient(create_app()) as client:
        first = _get(client)
        etag = first.headers["etag"]
        second = _get(client, **{"If-None-Match": etag})
    assert second.status_code == 304, second.text
    assert second.headers.get("etag") == etag
    cc = second.headers.get("cache-control", "")
    assert "public" in cc and "stale-while-revalidate" in cc


def test_graph_strong_inm_still_304s_under_weak_compare():
    """Cloudflare may echo our weak ETag back as its strong form; RFC 7232 weak
    comparison (shared if_none_match gate) must still 304 (mirrors /api/avatars)."""
    with TestClient(create_app()) as client:
        first = _get(client)
        weak = first.headers["etag"]      # W/"<hash>"
        strong = weak[2:]                  # "<hash>"
        second = _get(client, **{"If-None-Match": strong})
    assert second.status_code == 304, second.text
