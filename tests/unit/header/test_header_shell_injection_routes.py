"""HD-01 — shell-injection smoke across all 10 mounted desktop routes.

Phase 0 corrected the spec's "7 inner pages" claim — the real count is 10
(``/profile`` added by exec/DB_delete_zettel_refine--1a):

  ``/``, ``/knowledge-graph``, ``/home``, ``/home/nexus``, ``/home/zettels``,
  ``/home/kastens``, ``/home/rag``, ``/profile``, ``/about``, ``/pricing``.

All 10 are routed through ``_render_with_shell`` (``website/app.py:53-68``).
The shell function performs a *conditional* literal substitution: if the
page's HTML contains ``<!--ZK_HEADER-->``, the shared fragment is spliced
in; otherwise the raw page (which ships its own inline header) is returned.

Per-route assertions:

  (a) HTTP 200 on every route (route exists, shell didn't 500).
  (b) The ``<!--ZK_HEADER-->`` placeholder NEVER survives to the wire on
      ANY route — leaking the unsubstituted comment would be a bug.
  (c) On the SHELL_INJECTED subset (routes whose index.html carries the
      placeholder today), the response also contains the shared header
      class set ``class="header zk-header"`` AND the avatar dropdown
      marker ``id="avatar-dropdown"`` — proves substitution ran.
  (d) On the INLINE-HEADER subset (``/``, ``/home``, ``/about`` ship their
      own inline header markup), the response still carries SOME
      ``<header`` element so the page isn't decapitated.

Uses ASGI transport (no live network, no Playwright) so it runs in the
default unit-test lane with no extra runtime cost.
"""
from __future__ import annotations


import pytest

# Settings validation stubs — must precede the website.app import. Mirrors
# the pattern in tests/unit/user_home/test_shell_composition.py.
from tests.env_stub import stub_app_env_if_unconfigured

stub_app_env_if_unconfigured()


DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


# The 10 desktop routes that go through _render_with_shell. Each entry pairs
# the URL path with an expected text fragment that confirms route identity
# (so a misrouted response can't silently pass).
SHELL_ROUTES = [
    ("/",                 "Zettelkasten"),
    ("/knowledge-graph",  "knowledge"),  # case-insensitive substring check
    ("/home",             "home-vault"),
    ("/home/nexus",       "nexus"),
    ("/home/zettels",     "zettel"),
    ("/home/kastens",     "kasten"),
    ("/home/rag",         "rag"),
    ("/profile",          "profile"),
    ("/about",            "about"),
    ("/pricing",          "pricing"),
]


@pytest.fixture(scope="module")
def app():
    from website.app import create_app
    return create_app()


def _client(app):
    import httpx
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver",
    )


@pytest.mark.parametrize("path,route_marker", SHELL_ROUTES, ids=[p for p, _ in SHELL_ROUTES])
async def test_route_returns_200(app, path, route_marker):
    """Every shell'd desktop route must return 200."""
    async with _client(app) as client:
        resp = await client.get(path, headers={"User-Agent": DESKTOP_UA})
    assert resp.status_code == 200, (
        f"{path}: expected 200, got {resp.status_code} body={resp.text[:200]!r}"
    )


@pytest.mark.parametrize("path,route_marker", SHELL_ROUTES, ids=[p for p, _ in SHELL_ROUTES])
async def test_route_identity_marker(app, path, route_marker):
    """Sanity: response body actually matches the route (not a misrouted page)."""
    async with _client(app) as client:
        resp = await client.get(path, headers={"User-Agent": DESKTOP_UA})
    assert route_marker.lower() in resp.text.lower(), (
        f"{path}: expected '{route_marker}' in body — possible misroute"
    )


# Routes whose index.html carries <!--ZK_HEADER--> today (verified via grep
# on 2026-05-12): the shell fragment IS substituted in. The other 3 routes
# (/, /home, /about) ship inline header markup — substitution is a no-op
# fall-through and the inline copy serves the page.
# 2026-05-25: /knowledge-graph moved to INLINE_HEADER_ROUTES. The page's
# own <header class="kg-header"> covers the same nav footprint, and stacking
# the shared partial on top caused two visible headers + an unstyled-CSS
# giant-back-arrow flash during initial load. The literal <!--ZK_HEADER-->
# token was removed from kg/index.html so _render_with_shell skips injection.
# The "no placeholder leaks" test above still applies — there's just nothing
# to leak now.
SHELL_INJECTED_ROUTES = [
    "/home/nexus",
    "/home/zettels",
    "/home/kastens",
    "/home/rag",
    "/profile",
    "/pricing",
]
INLINE_HEADER_ROUTES = ["/", "/home", "/about", "/knowledge-graph"]


@pytest.mark.parametrize("path,_marker", SHELL_ROUTES, ids=[p for p, _ in SHELL_ROUTES])
async def test_no_zk_header_placeholder_leaks(app, path, _marker):
    """The literal <!--ZK_HEADER--> placeholder must NEVER survive to the wire."""
    async with _client(app) as client:
        resp = await client.get(path, headers={"User-Agent": DESKTOP_UA})
    assert "<!--ZK_HEADER-->" not in resp.text, (
        f"{path}: unsubstituted <!--ZK_HEADER--> leaked into the response"
    )


@pytest.mark.parametrize("path", SHELL_INJECTED_ROUTES)
async def test_shell_header_substitution_happened(app, path):
    """Shared header fragment was substituted (zk-header class + dropdown id)."""
    async with _client(app) as client:
        resp = await client.get(path, headers={"User-Agent": DESKTOP_UA})

    assert 'class="header zk-header"' in resp.text, (
        f"{path}: missing shared <header class=\"header zk-header\"> — "
        f"shell injection did not run"
    )
    assert 'id="avatar-dropdown"' in resp.text, (
        f"{path}: missing shared avatar dropdown markup"
    )


@pytest.mark.parametrize("path", INLINE_HEADER_ROUTES)
async def test_inline_header_route_has_header_element(app, path):
    """Routes that ship an inline header still render <header> markup."""
    async with _client(app) as client:
        resp = await client.get(path, headers={"User-Agent": DESKTOP_UA})
    assert resp.status_code == 200
    assert "<header" in resp.text, f"{path}: no <header> element rendered"
