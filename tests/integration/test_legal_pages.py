"""Standalone, server-rendered legal pages: /privacy, /terms, /data-security.

Google OAuth brand verification requires the Privacy Policy and Terms of Service
to be distinct, crawlable URLs that render server-side (viewable in incognito /
with JS disabled), require no login, and do not redirect. The /about page keeps
its modal UI; these routes expose the same documents as real pages. Copy is
single-sourced in ``website.core.legal_content`` (about.js mirrors it for the
modal).
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from website.app import create_app
from website.core.legal_content import LEGAL_DOCS, render_legal_page_html


@pytest.fixture
def client() -> TestClient:
    from website.api import routes

    routes._rate_store.clear()
    return TestClient(create_app(), follow_redirects=False)


# (path, doc-key, a section-title that must appear in the server-rendered HTML)
PAGES = [
    ("/privacy", "privacy", "What is stored"),
    ("/terms", "terms", "What you can do"),
    ("/data-security", "security", "Access model"),
]


class TestLegalPages:
    @pytest.mark.parametrize("path,key,section", PAGES)
    def test_renders_200_html_server_side(self, client, path, key, section):
        resp = client.get(path)
        assert resp.status_code == 200
        assert "html" in resp.headers.get("content-type", "").lower()
        body = resp.text
        assert "<!DOCTYPE html>" in body
        # Title + a real section body present in the INITIAL HTML (no JS needed).
        assert LEGAL_DOCS[key]["title"] in body
        assert section in body

    @pytest.mark.parametrize("path,key,section", PAGES)
    def test_no_redirect_even_for_mobile_ua(self, client, path, key, section):
        # Google requires a static URL (no redirect): the legal pages — like
        # /about (the OAuth home page) — serve content directly for any UA.
        resp = client.get(
            path,
            headers={"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15"},
        )
        assert resp.status_code == 200
        assert "<!DOCTYPE html>" in resp.text

    @pytest.mark.parametrize("path,key,section", PAGES)
    def test_requires_no_auth(self, client, path, key, section):
        # No Authorization header → still 200 (viewable in incognito).
        assert client.get(path).status_code == 200

    def test_pages_cross_link_and_link_home(self, client):
        body = client.get("/privacy").text
        for href in ('href="/privacy"', 'href="/terms"', 'href="/data-security"', 'href="/about"', 'href="/"'):
            assert href in body, f"missing {href}"

    def test_privacy_explains_account_data_use(self, client):
        # The "why we request your data" text Google's reviewer looks for.
        body = client.get("/privacy").text.lower()
        assert "email" in body
        assert "account" in body


class TestLegalContentSoT:
    def test_unknown_key_falls_back_to_privacy(self):
        html = render_legal_page_html("does-not-exist")
        assert LEGAL_DOCS["privacy"]["title"] in html

    def test_all_docs_render_self_contained(self):
        for key in ("privacy", "terms", "security"):
            html = render_legal_page_html(key)
            assert html.startswith("<!DOCTYPE html>")
            assert LEGAL_DOCS[key]["title"] in html
            assert "</html>" in html
