"""Tier-0 SEO hygiene contracts.

Locks: canonical + meta-description + Open Graph on the 7 public pages, a
well-formed /sitemap.xml, /robots.txt, and the crawler-exclusion that keeps
Googlebot (mobile-first UA) off the /m/ redirect so it reaches the canonical
desktop pages. In-process via httpx ASGITransport — no live server. Env is
stubbed before app import so settings validation doesn't SystemExit.
"""
from __future__ import annotations

import json
import os
import re
import xml.etree.ElementTree as ET

import pytest

os.environ.setdefault("GEMINI_API_KEY", "ci-stub")
os.environ.setdefault("SUPABASE_V2_URL", "https://ci-stub.supabase.co")
os.environ.setdefault("SUPABASE_V2_ANON_KEY", "ci-stub-anon")
os.environ.setdefault("SUPABASE_V2_SERVICE_ROLE_KEY", "ci-stub-service")
os.environ.setdefault(
    "NEXUS_TOKEN_ENCRYPTION_KEY",
    "7TgtMgeR5dMTnXxW6ULICwhf66A1VpzwuNFuIBqmoe4=",
)

ORIGIN = "https://zettelkasten.in"
OG_IMAGE = "https://zettelkasten.in/artifacts/og-cover.png"

PUBLIC_PATHS = ["/", "/about", "/pricing", "/knowledge-graph",
                "/privacy", "/terms", "/data-security"]

# Googlebot Smartphone: carries "Android" + "Mobile" (matches _MOBILE_RE) AND
# "Googlebot" (matches _CRAWLER_RE, checked first) — must NOT be redirected.
GOOGLEBOT_SMARTPHONE = (
    "Mozilla/5.0 (Linux; Android 6.0.1; Nexus 5X Build/MMB29P) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.6422.76 Mobile "
    "Safari/537.36 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
)
IPHONE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"
)
DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


@pytest.fixture(scope="module")
def app():
    from website.app import create_app

    return create_app()


def _client(app):
    import httpx

    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


# ── robots.txt ───────────────────────────────────────────────────────────
async def test_robots_txt_allows_all_and_points_at_sitemap(app):
    async with _client(app) as c:
        r = await c.get("/robots.txt")
    assert r.status_code == 200
    assert "text/plain" in r.headers.get("content-type", "")
    assert "User-agent: *" in r.text
    assert f"Sitemap: {ORIGIN}/sitemap.xml" in r.text


# ── sitemap.xml ──────────────────────────────────────────────────────────
async def test_sitemap_well_formed_and_lists_exactly_the_public_urls(app):
    async with _client(app) as c:
        r = await c.get("/sitemap.xml")
    assert r.status_code == 200
    assert "xml" in r.headers.get("content-type", "")
    root = ET.fromstring(r.text)  # raises on malformed XML
    ns = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
    locs = {el.text for el in root.iter(f"{ns}loc")}
    assert locs == {f"{ORIGIN}{p}" for p in PUBLIC_PATHS}


# ── crawler exclusion ────────────────────────────────────────────────────
@pytest.mark.parametrize("path", ["/", "/about", "/pricing", "/knowledge-graph"])
async def test_googlebot_is_not_redirected_to_mobile(app, path):
    async with _client(app) as c:
        r = await c.get(
            path, headers={"User-Agent": GOOGLEBOT_SMARTPHONE}, follow_redirects=False,
        )
    assert r.status_code == 200, f"Googlebot got {r.status_code} on {path} (redirected?)"
    assert 'rel="canonical"' in r.text


async def test_real_mobile_ua_still_redirects(app):
    # Negative control: bot-exclusion must NOT weaken the human mobile redirect.
    async with _client(app) as c:
        r = await c.get(
            "/about", headers={"User-Agent": IPHONE_UA}, follow_redirects=False,
        )
    assert r.status_code == 302
    assert r.headers["location"] == "/m/"


# ── desktop canonical + OG on every public page ──────────────────────────
@pytest.mark.parametrize("path", PUBLIC_PATHS)
async def test_public_page_has_canonical_description_and_og(app, path):
    async with _client(app) as c:
        r = await c.get(path, headers={"User-Agent": DESKTOP_UA}, follow_redirects=False)
    assert r.status_code == 200, f"{path} -> {r.status_code}"
    assert f'<link rel="canonical" href="{ORIGIN}{path}">' in r.text
    assert 'name="description"' in r.text
    assert 'property="og:title"' in r.text
    assert OG_IMAGE in r.text


# ── mobile canonical (separate-mobile-URL → desktop) ─────────────────────
async def test_mobile_public_pages_canonical_to_desktop(app):
    async with _client(app) as c:
        home = await c.get("/m/")
        kg = await c.get("/m/knowledge-graph")
    assert f'<link rel="canonical" href="{ORIGIN}/">' in home.text
    assert f'<link rel="canonical" href="{ORIGIN}/knowledge-graph">' in kg.text


async def test_mobile_private_page_has_no_canonical_and_no_leaked_placeholder(app):
    async with _client(app) as c:
        r = await c.get("/m/profile")
    assert r.status_code == 200
    assert 'rel="canonical"' not in r.text
    assert "ZK_MOBILE_CANONICAL" not in r.text  # placeholder must be consumed


# ── Sweep Part-3: OG completeness on every public page ───────────────────
@pytest.mark.parametrize("path", PUBLIC_PATHS)
async def test_public_page_has_og_image_dimensions_and_locale(app, path):
    async with _client(app) as c:
        r = await c.get(path, headers={"User-Agent": DESKTOP_UA}, follow_redirects=False)
    assert r.status_code == 200
    for tag in (
        '<meta property="og:image:width" content="1200">',
        '<meta property="og:image:height" content="630">',
        '<meta property="og:image:type" content="image/png">',
        '<meta property="og:locale" content="en_US">',
    ):
        assert tag in r.text, f"{path} missing {tag}"
    assert 'property="og:image:alt"' in r.text


# ── Organization/WebSite JSON-LD — landing only, valid JSON ──────────────
async def test_landing_has_valid_organization_jsonld(app):
    async with _client(app) as c:
        r = await c.get("/", headers={"User-Agent": DESKTOP_UA})
    m = re.search(r'<script type="application/ld\+json">(.*?)</script>', r.text, re.DOTALL)
    assert m, "no JSON-LD block on landing page"
    data = json.loads(m.group(1))  # raises on malformed JSON
    nodes = {n.get("@type") for n in data["@graph"]}
    assert {"Organization", "WebSite"} <= nodes
    org = next(n for n in data["@graph"] if n["@type"] == "Organization")
    assert org["name"] == "Zettelkasten"
    assert org["logo"].startswith("https://zettelkasten.in/")


async def test_jsonld_is_landing_only(app):
    async with _client(app) as c:
        about = await c.get("/about", headers={"User-Agent": DESKTOP_UA})
    assert "application/ld+json" not in about.text


# ── AI-crawler policy: block training, never block search/index bots ─────
async def test_robots_blocks_training_allows_search_and_citation(app):
    async with _client(app) as c:
        body = (await c.get("/robots.txt")).text
    assert body.startswith("User-agent: *\nAllow: /")
    for bot in ("GPTBot", "Google-Extended", "ClaudeBot", "anthropic-ai",
                "CCBot", "Bytespider", "Applebot-Extended", "Meta-ExternalAgent"):
        assert f"User-agent: {bot}\nDisallow: /" in body, f"{bot} block missing"
    # Search/index + answer-engine bots must NOT get their own Disallow group.
    for allowed in ("Googlebot", "Bingbot", "OAI-SearchBot", "PerplexityBot", "Claude-SearchBot"):
        assert f"User-agent: {allowed}" not in body, f"{allowed} must stay crawlable"
    assert "Sitemap: https://zettelkasten.in/sitemap.xml" in body


# ── Favicon raster (SERP insurance) ──────────────────────────────────────
async def test_favicon_ico_is_real_raster_not_svg(app):
    async with _client(app) as c:
        r = await c.get("/favicon.ico")
    assert r.status_code == 200
    assert "svg" not in r.headers.get("content-type", "")
    assert r.content[:4] == b"\x00\x00\x01\x00"  # ICO magic number


async def test_favicon_and_logo_rasters_serve(app):
    async with _client(app) as c:
        fav = await c.get("/artifacts/favicon-48.png")
        logo = await c.get("/artifacts/zettelkasten-logo-512.png")
    assert fav.status_code == 200 and fav.headers["content-type"] == "image/png"
    assert logo.status_code == 200 and logo.headers["content-type"] == "image/png"


async def test_landing_declares_raster_favicon_link(app):
    async with _client(app) as c:
        r = await c.get("/", headers={"User-Agent": DESKTOP_UA})
    assert '<link rel="icon" type="image/png" sizes="48x48" href="/artifacts/favicon-48.png">' in r.text
