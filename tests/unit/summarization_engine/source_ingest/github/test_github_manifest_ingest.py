"""Tests for the Option-B manifest fetch in the GitHub ingestor (Wave 2, M3).

Verifies: (1) only manifests PRESENT in the root /contents listing are fetched
(zero wasted GETs for absent files); (2) a real package.json bin yields a
verified verdict; (3) no token -> manifest stage skipped, refusal-first verdict;
(4) a repo with no manifests -> refusal-first verdict, no manifest GETs."""
from __future__ import annotations

import base64

import pytest

from website.features.summarization_engine.source_ingest.github import ingest as gh_ingest


def _b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


class _FakeResponse:
    def __init__(self, status_code: int, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class _FakeClient:
    """Records every GET URL; serves canned /contents listing + file bodies."""

    def __init__(self, listing, file_bodies: dict[str, str]):
        self._listing = listing
        self._file_bodies = file_bodies
        self.calls: list[str] = []

    async def get(self, url, **kwargs):
        self.calls.append(url)
        if url.endswith("/contents"):
            return _FakeResponse(200, self._listing)
        # Contents file fetch: /contents/<path>
        marker = "/contents/"
        if marker in url:
            path = url.split(marker, 1)[1]
            body = self._file_bodies.get(path)
            if body is None:
                return _FakeResponse(404, {})
            return _FakeResponse(200, {"content": _b64(body), "encoding": "base64"})
        return _FakeResponse(404, {})


@pytest.mark.asyncio
async def test_manifest_fetch_only_hits_present_files():
    listing = [
        {"name": "README.md", "type": "file"},
        {"name": "package.json", "type": "file"},
    ]
    bodies = {"package.json": '{"name": "eslint", "bin": "bin/eslint.js"}'}
    client = _FakeClient(listing, bodies)

    verdict = await gh_ingest._fetch_manifest_signals(
        client, "owner", "repo", listing, "main", token_present=True
    )

    assert verdict["verified"] is True
    assert verdict["commands"] == ["eslint"]
    # Exactly ONE manifest GET (package.json). NO GET for pyproject/cargo/etc.
    manifest_gets = [c for c in client.calls if "/contents/" in c]
    assert manifest_gets == [
        "https://api.github.com/repos/owner/repo/contents/package.json"
    ]


@pytest.mark.asyncio
async def test_absent_manifests_cause_zero_wasted_gets():
    listing = [{"name": "README.md", "type": "file"}, {"name": "LICENSE", "type": "file"}]
    client = _FakeClient(listing, {})

    verdict = await gh_ingest._fetch_manifest_signals(
        client, "owner", "repo", listing, "main", token_present=True
    )

    assert verdict["verified"] is False
    assert "no verified interface artifact" in verdict["label"].lower()
    # No /contents/<file> GET at all — we never blind-probe a missing manifest.
    assert [c for c in client.calls if "/contents/" in c] == []


@pytest.mark.asyncio
async def test_no_token_skips_manifest_fetch_refusal_first():
    listing = [{"name": "package.json", "type": "file"}]
    bodies = {"package.json": '{"name": "x", "bin": "b.js"}'}
    client = _FakeClient(listing, bodies)

    verdict = await gh_ingest._fetch_manifest_signals(
        client, "owner", "repo", listing, "main", token_present=False
    )

    assert verdict["verified"] is False
    assert verdict["kind"] == "none"
    # Anonymous: we do NOT spend the scarce 60/hr budget on manifest reads.
    assert [c for c in client.calls if "/contents/" in c] == []


@pytest.mark.asyncio
async def test_case_insensitive_filename_match():
    # GitHub preserves case; our match is via the lowercased listing map.
    listing = [{"name": "Cargo.toml", "type": "file"}]
    bodies = {"Cargo.toml": '[package]\nname="p"\n[[bin]]\nname="rg"\n'}
    client = _FakeClient(listing, bodies)

    verdict = await gh_ingest._fetch_manifest_signals(
        client, "owner", "repo", listing, "main", token_present=True
    )
    assert verdict["verified"] is True
    assert verdict["commands"] == ["rg"]
    assert client.calls[-1].endswith("/contents/Cargo.toml")
