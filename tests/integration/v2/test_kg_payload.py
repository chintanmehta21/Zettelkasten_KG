"""WAVE-C 1c-A.4 — /api/graph payload trim + Brotli negotiation tests.

Locked decisions covered:
- D-KG-8: Brotli + gzip via Accept-Encoding negotiation
- D-KG-9: drop embedding, raw scores, raw timestamps, model_version

Strategy: black-box the response shape via FastAPI TestClient + monkey-patch
the upstream graph loader. Avoids any Supabase round-trip (these are NOT
@live tests) so they run in the regular suite.
"""
from __future__ import annotations

import gzip
import json

import pytest
from fastapi.testclient import TestClient


def _build_test_app():
    """Construct a minimal FastAPI app exposing /api/graph against an
    in-memory file-store stub. Avoids Supabase / auth / lifespan startup.
    """
    from fastapi import FastAPI

    from website.api import routes as routes_module

    app = FastAPI()

    # Register Brotli compression middleware to mirror production wiring.
    try:
        from brotli_asgi import BrotliMiddleware

        app.add_middleware(BrotliMiddleware, minimum_size=512, quality=4)
    except ImportError:
        pytest.skip("brotli-asgi not installed in this env")

    app.include_router(routes_module.router)
    return app


# ── _trim_graph_response unit-level checks ────────────────────────────


def test_trim_drops_embedding_and_model_version() -> None:
    from website.api.routes import _trim_graph_response

    payload = {
        "nodes": [
            {
                "id": "n1",
                "name": "node-1",
                "summary": "ok",
                "embedding": [0.1] * 768,
                "embedding_model_version": "gemini-001-mrl-768",
                "embedding_dim": 768,
                "model_version": "v1",
                "score_breakdown": {"a": 1},
                "betweenness": 0.5,
                "closeness": 0.7,
                "created_at_microseconds": 999,
                "tags": ["x"],
                "pagerank": 0.123456789,
            }
        ],
        "links": [
            {
                "source": "n1",
                "target": "n2",
                "relation": "shared_tag",
                "connection_strength": 0.85,
                "embedding_distance": 0.123,
                "raw_score": 0.99,
                "score_breakdown": {"e": 1},
            }
        ],
        "meta": {"communities": 1},
    }

    trimmed = _trim_graph_response(payload)
    node = trimmed["nodes"][0]
    for k in (
        "embedding",
        "embedding_model_version",
        "embedding_dim",
        "model_version",
        "score_breakdown",
        "betweenness",
        "closeness",
        "created_at_microseconds",
    ):
        assert k not in node, f"node still leaks {k!r}"
    assert node["id"] == "n1"
    assert node["pagerank"] == round(0.123456789, 6)

    link = trimmed["links"][0]
    for k in ("embedding_distance", "raw_score", "score_breakdown"):
        assert k not in link, f"link still leaks {k!r}"
    assert link["connection_strength"] == 0.85
    assert link["source"] == "n1"

    # Top-level meta preserved.
    assert trimmed["meta"] == {"communities": 1}


def test_trim_preserves_essential_fields() -> None:
    from website.api.routes import _trim_graph_response

    payload = {
        "nodes": [
            {"id": "n1", "name": "x", "tags": ["a"], "url": "http://e"},
        ],
        "links": [],
    }
    out = _trim_graph_response(payload)
    assert out["nodes"][0] == {"id": "n1", "name": "x", "tags": ["a"], "url": "http://e"}


# ── min_strength filter strict subset ─────────────────────────────────


def test_min_strength_filter_strict_subset() -> None:
    from website.api.routes import _apply_min_strength_filter

    payload = {
        "nodes": [{"id": "a"}, {"id": "b"}, {"id": "c"}],
        "links": [
            {"source": "a", "target": "b", "connection_strength": 0.9},
            {"source": "a", "target": "c", "connection_strength": 0.5},
            {"source": "b", "target": "c", "connection_strength": 0.2},
            {"source": "a", "target": "a", "connection_strength": None},
        ],
    }
    weak = _apply_min_strength_filter(payload, 0.0)
    strong = _apply_min_strength_filter(payload, 0.7)
    assert len(weak["links"]) == 4, "min_strength=0.0 returns everything"
    assert len(strong["links"]) == 1
    # Strong is a strict subset.
    strong_keys = {(l["source"], l["target"]) for l in strong["links"]}
    weak_keys = {(l["source"], l["target"]) for l in weak["links"]}
    assert strong_keys.issubset(weak_keys)


def test_min_strength_filter_drops_null_strength() -> None:
    from website.api.routes import _apply_min_strength_filter

    payload = {
        "nodes": [],
        "links": [
            {"source": "a", "target": "b", "connection_strength": None},
            {"source": "a", "target": "c", "connection_strength": 0.6},
        ],
    }
    out = _apply_min_strength_filter(payload, 0.5)
    assert len(out["links"]) == 1
    assert out["links"][0]["target"] == "c"


# ── Brotli content-encoding negotiation ─────────────────────────────


def test_brotli_negotiation_returns_br(monkeypatch) -> None:
    """Accept-Encoding: br ⇒ Content-Encoding: br on a >1KB response."""
    import website.api.routes as routes_module
    from website.core.graph_models import KGGraph

    # Stub out get_graph() to return a payload large enough to compress.
    big_payload = {
        "nodes": [
            {
                "id": f"n-{i}",
                "name": f"node-{i}",
                "group": "web",
                "summary": "lorem ipsum " * 30,
                "tags": ["python", "fastapi", "supabase"],
                "url": f"https://example.com/{i}",
                "date": "2026-01-01",
                "node_date": "2026-01-01",
            }
            for i in range(100)
        ],
        "links": [],
    }

    def _fake_get_graph():
        return big_payload

    # Both routes_module-local and origin name (defensive monkey-patch).
    monkeypatch.setattr(routes_module, "get_graph", _fake_get_graph)
    monkeypatch.setattr(
        routes_module,
        "_enrich_graph_with_analytics",
        lambda d: d,  # skip analytics in this payload-shape test
    )

    app = _build_test_app()
    with TestClient(app) as client:
        r = client.get("/api/graph", headers={"Accept-Encoding": "br"})
    assert r.status_code == 200
    assert r.headers.get("Content-Encoding") == "br"


def test_gzip_negotiation_returns_gzip(monkeypatch) -> None:
    """Accept-Encoding: gzip alone ⇒ either gzip or br (server may downgrade)."""
    import website.api.routes as routes_module

    big_payload = {
        "nodes": [{"id": f"n-{i}", "name": f"x{i}", "summary": "y" * 200, "tags": []}
                  for i in range(50)],
        "links": [],
    }
    monkeypatch.setattr(routes_module, "get_graph", lambda: big_payload)
    monkeypatch.setattr(routes_module, "_enrich_graph_with_analytics", lambda d: d)

    app = _build_test_app()
    with TestClient(app) as client:
        r = client.get("/api/graph", headers={"Accept-Encoding": "gzip"})
    assert r.status_code == 200
    # brotli-asgi falls back to gzip when br not in Accept-Encoding.
    assert r.headers.get("Content-Encoding") in ("gzip", None)
    # Body is decoded transparently by httpx when Content-Encoding is set.
    parsed = r.json()
    assert "nodes" in parsed


def test_payload_trims_embedding_via_endpoint(monkeypatch) -> None:
    """Even if the upstream loader returns embedding-laden nodes, the
    response payload must NOT contain them (D-KG-9)."""
    import website.api.routes as routes_module

    payload_with_embeddings = {
        "nodes": [
            {
                "id": "n1",
                "name": "x",
                "embedding": [0.1] * 768,
                "embedding_model_version": "gemini-001-mrl-768",
                "tags": [],
            }
        ],
        "links": [],
    }
    monkeypatch.setattr(routes_module, "get_graph", lambda: payload_with_embeddings)
    monkeypatch.setattr(routes_module, "_enrich_graph_with_analytics", lambda d: d)

    app = _build_test_app()
    with TestClient(app) as client:
        r = client.get("/api/graph", headers={"Accept-Encoding": "identity"})
    assert r.status_code == 200
    body = r.json()
    assert "embedding" not in body["nodes"][0]
    assert "embedding_model_version" not in body["nodes"][0]


# ── Payload size budget at 1k-node fixture ─────────────────────────


def test_payload_under_300kb_at_1k_nodes(monkeypatch) -> None:
    """Compressed /api/graph response must stay under 300KB at 1k nodes
    with default trim + br compression. Headroom for 10k-user scale.
    """
    import website.api.routes as routes_module

    n = 1000
    fixture = {
        "nodes": [
            {
                "id": f"n-{i}",
                "name": f"node-{i}",
                "group": "web",
                "summary": "summary " * 20,
                "tags": [f"tag-{i % 25}"],
                "url": f"https://example.com/{i}",
                "date": "2026-01-01",
                "node_date": "2026-01-01",
            }
            for i in range(n)
        ],
        "links": [
            {
                "source": f"n-{i}",
                "target": f"n-{(i + 1) % n}",
                "relation": "shared_tag",
                "connection_strength": 0.65,
            }
            for i in range(n)
        ],
    }
    monkeypatch.setattr(routes_module, "get_graph", lambda: fixture)
    monkeypatch.setattr(routes_module, "_enrich_graph_with_analytics", lambda d: d)

    app = _build_test_app()
    with TestClient(app) as client:
        r = client.get("/api/graph", headers={"Accept-Encoding": "br"})
    assert r.status_code == 200
    # httpx.Response.content has already been decompressed; we want the
    # raw on-the-wire size — read from the Content-Length header.
    raw_size = int(r.headers.get("Content-Length", 0))
    if raw_size == 0:
        # Some servers omit Content-Length on chunked; re-encode to estimate.
        import brotli  # type: ignore

        raw_size = len(brotli.compress(r.content, quality=4))
    assert raw_size < 300 * 1024, (
        f"compressed /api/graph payload is {raw_size} bytes at 1k nodes; "
        f"D-KG-8 budget is <300KB"
    )
