"""/about JSON-LD structured data — machine-readable app purpose for crawlers.

The /about page is the Google OAuth consent-screen "App home page". Google's
home-page guidance asks the page to describe the app's functionality AND
explain the purpose for which it requests user data. The visible page already
describes the app; this JSON-LD block adds an explicit, machine-readable
statement of the purpose + the Google Sign-In data use, WITHOUT changing what
end users see on the rendered page (it is not displayed and not a search
snippet). Served identically to every user-agent — no cloaking.

These tests lock the block to valid JSON that states both the app purpose and
the Google Sign-In usage, so a future edit can't silently drop or break it.
"""
from __future__ import annotations

import json
import os
import re

import pytest

# Stub env BEFORE importing the app — settings validation SystemExits otherwise.
os.environ.setdefault("GEMINI_API_KEY", "ci-stub")
os.environ.setdefault("SUPABASE_V2_URL", "https://ci-stub.supabase.co")
os.environ.setdefault("SUPABASE_V2_ANON_KEY", "ci-stub-anon")
os.environ.setdefault("SUPABASE_V2_SERVICE_ROLE_KEY", "ci-stub-service")
os.environ.setdefault(
    "NEXUS_TOKEN_ENCRYPTION_KEY",
    "7TgtMgeR5dMTnXxW6ULICwhf66A1VpzwuNFuIBqmoe4=",
)

from fastapi.testclient import TestClient  # noqa: E402

from website.app import create_app  # noqa: E402


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(), follow_redirects=False)


def _extract_jsonld(html: str) -> dict:
    m = re.search(
        r'<script type="application/ld\+json">(.*?)</script>', html, re.DOTALL
    )
    assert m, "no JSON-LD <script> block found on /about"
    return json.loads(m.group(1))  # raises on malformed JSON => test fails


def test_about_serves_valid_jsonld(client):
    resp = client.get("/about")
    assert resp.status_code == 200
    data = _extract_jsonld(resp.text)
    assert data["@type"] == "WebApplication"
    assert data["name"] == "Zettelkasten"


def test_about_jsonld_states_purpose_and_google_signin(client):
    data = _extract_jsonld(client.get("/about").text)
    desc = data["description"].lower()
    # App functionality...
    assert "knowledge graph" in desc
    assert "summar" in desc
    # ...and the Google Sign-In data-use purpose Google's reviewer looks for.
    assert "google" in desc
    assert "sign in" in desc
