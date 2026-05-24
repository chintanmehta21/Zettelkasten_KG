"""Tests for PWA manifest + service worker (iter mobile-1a Phase 6)."""
from __future__ import annotations

import json

from fastapi.testclient import TestClient

from website.app import create_app


def _client() -> TestClient:
    return TestClient(create_app())


def test_manifest_served_with_correct_content_type() -> None:
    resp = _client().get("/manifest.webmanifest")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/manifest+json")


def test_manifest_has_required_fields() -> None:
    resp = _client().get("/manifest.webmanifest")
    data = json.loads(resp.text)
    assert data["name"]
    assert data["short_name"]
    assert data["start_url"] == "/m/"
    assert data["scope"] == "/m/"
    assert data["display"] == "standalone"
    assert data.get("id") == "/m/"
    assert data["theme_color"]
    assert data["background_color"]
    sizes = {(i["sizes"], i.get("purpose", "any")) for i in data["icons"]}
    assert ("192x192", "any") in sizes
    assert ("512x512", "any") in sizes
    assert any("maskable" in s[1] for s in sizes)


def test_service_worker_served_with_correct_headers() -> None:
    resp = _client().get("/sw.js")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/javascript") or \
           resp.headers["content-type"].startswith("text/javascript")
    cache = resp.headers.get("cache-control", "")
    assert "no-cache" in cache or "max-age=0" in cache or "max-age=300" in cache


def test_service_worker_does_not_cache_api() -> None:
    """sw.js source must NOT include /api in its cache allow-list."""
    resp = _client().get("/sw.js")
    src = resp.text
    # Must explicitly skip /api/ in fetch handler — look for the marker
    assert "url.pathname.startsWith('/api/')" in src or "pathname.startsWith(\"/api/\")" in src
