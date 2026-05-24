"""Tests for mobile shell injection + escape cookie (iter mobile-1a Phase 1)."""
from __future__ import annotations

import os

# Stub env BEFORE importing the FastAPI app — settings validation would
# otherwise SystemExit on missing keys.
os.environ.setdefault("GEMINI_API_KEY", "ci-stub")
os.environ.setdefault("SUPABASE_V2_URL", "https://ci-stub.supabase.co")
os.environ.setdefault("SUPABASE_V2_ANON_KEY", "ci-stub-anon")
os.environ.setdefault("SUPABASE_V2_SERVICE_ROLE_KEY", "ci-stub-service")
os.environ.setdefault(
    "NEXUS_TOKEN_ENCRYPTION_KEY",
    "7TgtMgeR5dMTnXxW6ULICwhf66A1VpzwuNFuIBqmoe4=",
)

from fastapi.testclient import TestClient

from website.app import _DESKTOP_COOKIE, create_app


def _client() -> TestClient:
    return TestClient(create_app())


def test_mobile_index_includes_shell_header() -> None:
    """`/m/` HTML must contain the shared mobile header markup."""
    resp = _client().get("/m/")
    assert resp.status_code == 200
    html = resp.text
    assert 'class="m-bottom-tabs"' in html
    assert 'data-tab="capture"' in html
    assert html.count('<meta charset="UTF-8">') == 1
    assert html.count('href="https://fonts.googleapis.com/css2?family=Inter') == 1


def test_mobile_kg_page_includes_shell_header() -> None:
    resp = _client().get("/m/knowledge-graph")
    assert resp.status_code == 200
    html = resp.text
    assert 'class="m-bottom-tabs"' in html
    assert 'data-tab="graph"' in html


def test_escape_cookie_bypasses_mobile_redirect() -> None:
    client = _client()
    iphone_ua = (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
    )
    resp = client.get("/home", headers={"User-Agent": iphone_ua}, follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "/m/"
    client.cookies.set(_DESKTOP_COOKIE, "1")
    resp = client.get(
        "/home",
        headers={"User-Agent": iphone_ua},
        follow_redirects=False,
    )
    client.cookies.clear()
    assert resp.status_code == 200
    assert "/m/" not in resp.headers.get("location", "")


def test_mobile_index_includes_oauth_modal() -> None:
    """/m/ HTML must include the OAuth modal (Phase 3)."""
    import re

    resp = _client().get("/m/")
    assert resp.status_code == 200
    html = resp.text
    assert 'id="m-auth-modal"' in html
    assert 'data-provider="google"' in html
    assert 'data-provider="apple"' in html
    # More options must be hidden by default
    assert 'id="m-auth-more-options"' in html and 'hidden' in html
    # All 6 providers must be present in the modal block
    assert 'data-provider="github"' in html
    assert 'data-provider="twitter"' in html
    assert 'data-provider="facebook"' in html
    assert 'data-provider="twitch"' in html
    # Supabase CDN + auth-core.js + auth-modal.js must be loaded. Mobile
    # pages skip auth.js (desktop landing DOM wiring) — auth-modal.js owns
    # the mobile auth chrome and just needs window.ZKAuth from auth-core.
    assert 'supabase-js@2' in html
    assert '/auth/js/auth-core.js' in html
    assert '/auth/js/auth.js' not in html, \
        "Mobile must NOT load auth.js (desktop DOM wiring); use auth-core.js"
    assert '/m/js/auth-modal.js' in html
    # Apple + Twitter are in DOM but hidden until validated (plan §0 deferrals)
    apple_btn = re.search(r'<button[^>]*data-provider="apple"[^>]*>', html)
    twitter_btn = re.search(r'<button[^>]*data-provider="twitter"[^>]*>', html)
    assert apple_btn and 'hidden' in apple_btn.group(0), "Apple chip must be hidden per plan defer"
    assert twitter_btn and 'hidden' in twitter_btn.group(0), "Twitter chip must be hidden per plan defer"


def test_mobile_kg_includes_filter_sheet() -> None:
    """/m/knowledge-graph includes the dual-mode filter sheet."""
    resp = _client().get("/m/knowledge-graph")
    assert resp.status_code == 200
    html = resp.text
    assert 'id="sheet-tab-filters"' in html
    assert 'id="kg-strength-slider"' in html
    assert 'id="kg-tag-search"' in html
    assert 'id="kg-kasten-search"' in html
    assert 'id="recenter-btn"' in html
    # Personal-view button starts disabled
    assert 'data-view="my"' in html
    assert 'aria-disabled="true"' in html


def test_query_param_sets_escape_cookie_then_serves_desktop() -> None:
    client = _client()
    iphone_ua = (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
    )
    resp = client.get("/?desktop=1", headers={"User-Agent": iphone_ua}, follow_redirects=False)
    assert resp.status_code == 200
    set_cookie = resp.headers.get("set-cookie", "")
    assert f"{_DESKTOP_COOKIE}=1" in set_cookie
    assert "Max-Age=2592000" in set_cookie
    assert "HttpOnly" in set_cookie


def test_mobile_kg_personal_view_uses_correct_api_param() -> None:
    """graph.js must use ?view=my (not ?scope=personal) per /api/graph contract."""
    import pathlib

    graph_js = pathlib.Path("website/mobile/js/graph.js").read_text(encoding="utf-8")
    assert "view=my" in graph_js, "graph.js Personal view must use ?view=my param"
    assert "scope=personal" not in graph_js, "graph.js must not use the wrong ?scope=personal param"
