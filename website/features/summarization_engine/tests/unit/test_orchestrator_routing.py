"""Orchestrator routing seam (_resolve_route): WEB->newsletter probe wiring.

Tests the routing decision in isolation — no ingest, no Gemini. The probe's
own signal logic is covered in test_router.py; here we only verify the
orchestrator wires it correctly: probe WEB-with-no-override, honor explicit
caller override without probing, never probe a non-WEB family.
"""
from website.features.summarization_engine.core.models import SourceType
from website.features.summarization_engine.core.orchestrator import _resolve_route


def _fetcher(html: str):
    async def _f(_url: str) -> str:
        return html

    return _f


async def test_resolve_route_probes_web_and_upgrades_to_newsletter():
    html = '<head><meta name="generator" content="Ghost"></head>'
    d = await _resolve_route("https://blog.example/p", None, fetcher=_fetcher(html))
    assert d.source_type == SourceType.NEWSLETTER


async def test_resolve_route_keeps_web_when_no_signal():
    d = await _resolve_route(
        "https://plain.example/x", None, fetcher=_fetcher("<html><body>hi</body></html>")
    )
    assert d.source_type == SourceType.WEB


async def test_resolve_route_skips_probe_when_caller_overrides_source_type():
    calls = {"n": 0}

    async def _counting(_url: str) -> str:
        calls["n"] += 1
        return '<meta name="generator" content="Ghost">'

    d = await _resolve_route("https://blog.example/p", SourceType.WEB, fetcher=_counting)
    assert d.source_type == SourceType.WEB
    assert calls["n"] == 0


async def test_resolve_route_non_web_not_probed():
    calls = {"n": 0}

    async def _counting(_url: str) -> str:
        calls["n"] += 1
        return "<html></html>"

    d = await _resolve_route("https://github.com/foo/bar", None, fetcher=_counting)
    assert d.source_type == SourceType.GITHUB
    assert calls["n"] == 0


async def test_resolve_route_probe_failure_falls_back_to_web():
    async def _boom(_url: str) -> str:
        raise RuntimeError("network down")

    d = await _resolve_route("https://blog.example/p", None, fetcher=_boom)
    assert d.source_type == SourceType.WEB
