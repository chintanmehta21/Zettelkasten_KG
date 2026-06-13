"""/about is the Google OAuth consent-screen "App home page".

Google requires that URL to be STATIC (no redirect) and reachable by ANY
user-agent — including Googlebot Smartphone, whose UA matches ``_MOBILE_RE``
(it contains both "Android" and "Mobile") and was previously 302-redirected to
``/m/``. Google crawls mobile-first, so that redirect meant its verification
fetch of the home page never saw the descriptive page. These tests lock /about
to a direct 200 for mobile + crawler UAs and assert the home-page content
clauses Google checks (app description + a link to the privacy policy).

In-process via httpx ASGITransport; no live server required. Mirrors the env
stubbing + client pattern in ``tests/unit/user_home/test_mobile_ua_redirect.py``.
"""
from __future__ import annotations

import os

import pytest

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


PIXEL_UA = (
    "Mozilla/5.0 (Linux; Android 14; Pixel 8 Pro) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36"
)
IPHONE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 "
    "Mobile/15E148 Safari/604.1"
)
# Googlebot Smartphone — the UA Google's mobile-first crawler sends. Contains
# both "Android" and "Mobile", so _MOBILE_RE matches it; this is the exact UA
# class that must NOT receive a redirect on the OAuth home page.
GOOGLEBOT_SMARTPHONE_UA = (
    "Mozilla/5.0 (Linux; Android 6.0.1; Nexus 5X Build/MMB29P) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Mobile "
    "Safari/537.36 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
)
DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


@pytest.fixture(scope="module")
def app():
    from website.app import create_app

    return create_app()


def _async_client(app):
    import httpx

    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


@pytest.mark.parametrize(
    "ua",
    [PIXEL_UA, IPHONE_UA, GOOGLEBOT_SMARTPHONE_UA, DESKTOP_UA],
    ids=["pixel", "iphone", "googlebot-smartphone", "desktop"],
)
async def test_about_homepage_never_redirects(app, ua):
    """The OAuth home page must serve 200 (never a 302) for EVERY UA."""
    async with _async_client(app) as client:
        resp = await client.get(
            "/about", headers={"User-Agent": ua}, follow_redirects=False,
        )
    assert resp.status_code == 200, (
        f"/about must not redirect (got {resp.status_code}) for UA={ua!r}"
    )
    assert "text/html" in resp.headers.get("content-type", "")


async def test_about_homepage_describes_app_and_links_privacy(app):
    """Home-page content clauses Google verifies: the page describes the app
    and links to the privacy policy (terms optional). Asserted against the
    initial server HTML fetched with the mobile-first crawler UA."""
    async with _async_client(app) as client:
        resp = await client.get(
            "/about",
            headers={"User-Agent": GOOGLEBOT_SMARTPHONE_UA},
            follow_redirects=False,
        )
    assert resp.status_code == 200
    body = resp.text
    assert "<!DOCTYPE html>" in body
    assert 'href="/privacy"' in body, "home page must link the privacy policy"
    assert 'href="/terms"' in body
    # App functionality is described in the initial HTML (no JS needed).
    assert "Zettelkasten" in body
    assert "capture" in body.lower()


async def test_about_homepage_requires_no_auth(app):
    """Publicly accessible without login (no Authorization header) → 200."""
    async with _async_client(app) as client:
        resp = await client.get("/about", follow_redirects=False)
    assert resp.status_code == 200
