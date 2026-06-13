"""Graceful-fallback refusal-first regression (Wave 2 review FIX 1).

The structured-extraction VALIDATION-FAILURE branch builds a deterministic
payload from README signals. Before the fix it named heuristic
`clean_surfaces` as the repository's public API — but `/sub`, `/center`, and
`--Please` (the exact fabricated tokens Wave 2 demotes in the prompt path) all
pass `_looks_clean_surface` AND are NOT caught by `_is_bogus_surface`, so they
leaked back as a "Documented public surface" on the rarer fallback branch.

These tests lock the refusal-first contract on that branch: with no
machine-verified interface artifact, none of those tokens may appear as a
named public/verified interface; a real verified manifest command still
surfaces.
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from website.features.summarization_engine.core.models import IngestResult, SourceType
from website.features.summarization_engine.summarization.github.archetype import (
    RepoArchetype,
)
from website.features.summarization_engine.summarization.github.manifest_signals import (
    build_interface_verdict,
)
from website.features.summarization_engine.summarization.github.readme_signals import (
    ReadmeSignals,
)
from website.features.summarization_engine.summarization.github.summarizer import (
    GitHubSummarizer,
    _build_graceful_fallback,
)

# The fabricated tokens, exactly as the README regexes emit them (mirrors
# test_prompt_variants._bogus_signals).
_FABRICATED = ("/sub", "/center", "--Please")


def _bogus_signals() -> ReadmeSignals:
    return ReadmeSignals(
        install_cmds=("pip install requests",),
        endpoints=("/sub", "/center"),
        cli_flags=("--Please",),
        decorators=(),
        inline_code=(),
        first_code_block="",
        stack=("Python",),
        purpose_sentence="A documented HTTP library for humans.",
    )


def _ingest() -> IngestResult:
    return IngestResult(
        source_type=SourceType.GITHUB,
        url="https://github.com/ow/thin",
        original_url="https://github.com/ow/thin",
        raw_text="README\n# Thin\n<sub>x</sub> <center>y</center> Please cite.",
        extraction_confidence="high",
        confidence_reason="ok",
        fetched_at="2026-04-21T00:00:00+00:00",
        metadata={"language": "Python"},
    )


def _payload_interface_blob(payload) -> str:
    """Concatenate every place the payload names an interface/surface."""
    parts: list[str] = [payload.brief_summary, payload.architecture_overview]
    for section in payload.detailed_summary:
        parts.extend(section.public_interfaces)
        parts.extend(section.bullets)
    return "\n".join(parts)


def test_graceful_fallback_refusal_first_drops_fabricated_surfaces():
    """No verified artifact -> fabricated README tokens must NOT be named as
    the repo's public interface; refusal-first framing is used instead."""
    refusal = build_interface_verdict({}).as_metadata()  # verified=False
    payload = _build_graceful_fallback(
        ingest=_ingest(),
        summary_text="A documented HTTP library for humans.",
        archetype=RepoArchetype.LIBRARY_THIN,
        signals=_bogus_signals(),
        verified_interface=refusal,
    )

    # The detailed section must not list any fabricated token as a public
    # interface, and the brief/bullets must not name them either.
    for section in payload.detailed_summary:
        for token in _FABRICATED:
            assert token not in section.public_interfaces, (
                f"fabricated token {token!r} leaked into public_interfaces"
            )

    blob = _payload_interface_blob(payload)
    for token in _FABRICATED:
        assert token not in blob, (
            f"fabricated token {token!r} surfaced as a named interface: {blob!r}"
        )

    # Refusal-first framing is present somewhere in the user-facing prose.
    lowered = blob.lower()
    assert "no verified interface" in lowered or "library" in lowered or "overview" in lowered


def test_graceful_fallback_names_verified_command_when_artifact_present():
    """A machine-verified manifest command MUST still surface on the fallback
    branch (the verified label is the only thing allowed to name an interface)."""
    verdict = build_interface_verdict(
        {"package.json": '{"name": "mytool", "bin": "bin/cli.js"}'}
    ).as_metadata()
    assert verdict["verified"] is True  # guard: the fixture really verifies

    payload = _build_graceful_fallback(
        ingest=_ingest(),
        summary_text="A documented CLI built in Node.",
        archetype=RepoArchetype.CLI_TOOL,
        signals=_bogus_signals(),
        verified_interface=verdict,
    )

    blob = _payload_interface_blob(payload)
    assert "mytool" in blob, f"verified command not surfaced: {blob!r}"
    # Even with a verified artifact, the fabricated regex tokens never surface.
    for token in _FABRICATED:
        assert token not in blob


@pytest.mark.asyncio
async def test_summarize_path_threads_refusal_first_into_fallback(monkeypatch):
    """End-to-end seam check: the summarizer's ``_fallback_builder`` closure
    must carry the refusal-first verdict so the fabricated tokens never reach
    the payload it returns. We capture the real builder (via fake_init) and
    invoke it the way StructuredExtractor.extract would on a validation
    failure — without needing a live Gemini client."""
    from website.features.summarization_engine.summarization.common import (
        dense_verify,
        dense_verify_runner,
        structured,
    )
    from website.features.summarization_engine.summarization.github import (
        summarizer as gh_mod,
    )

    async def _fake_run_dense_verify(*, client, ingest, precomputed_dense=None, cache=None):  # noqa: ARG001
        return dense_verify.DenseVerifyResult(
            dense_text="A documented HTTP library for humans.",
            missing_facts=[], stance=None, archetype=None,
            format_label=None, core_argument="x", closing_hook="y",
        )

    monkeypatch.setattr(gh_mod, "run_dense_verify", _fake_run_dense_verify)
    dense_verify_runner._DV_CACHE.clear()

    captured: dict = {}
    original_init = structured.StructuredExtractor.__init__

    def fake_init(self, client, config, payload_class=structured.StructuredSummaryPayload,
                  *, fallback_builder=None, prompt_builder=None,
                  prompt_instruction=None, missing_facts_hint=None):
        captured["fallback_builder"] = fallback_builder
        original_init(
            self, client, config, payload_class,
            fallback_builder=fallback_builder, prompt_builder=prompt_builder,
            prompt_instruction=prompt_instruction, missing_facts_hint=missing_facts_hint,
        )

    async def fake_extract(self, ingest, text, **kwargs):
        from website.features.summarization_engine.core.models import (
            DetailedSummarySection, SummaryMetadata, SummaryResult,
        )
        # Drive the SAME fallback the validation-failure branch would.
        payload = self._fallback_builder(ingest, text, self._config)
        captured["payload"] = payload
        return SummaryResult(
            mini_title=payload.mini_title, brief_summary=payload.brief_summary,
            tags=payload.tags,
            detailed_summary=[
                DetailedSummarySection(heading=s.heading, bullets=s.bullets)
                for s in payload.detailed_summary
            ],
            metadata=SummaryMetadata(
                source_type=SourceType.GITHUB, url=ingest.url,
                extraction_confidence="high", confidence_reason="ok",
                total_tokens_used=0, total_latency_ms=0,
            ),
        )

    monkeypatch.setattr(structured.StructuredExtractor, "__init__", fake_init)
    monkeypatch.setattr(structured.StructuredExtractor, "extract", fake_extract)

    ingest = IngestResult(
        source_type=SourceType.GITHUB,
        url="https://github.com/ow/thin",
        original_url="https://github.com/ow/thin",
        raw_text=(
            "Repository\now/thin\nREADME\n# Thin\n"
            "<sub>note</sub> <center>logo</center>\n"
            "Please cite this work. See /center for details.\n"
        ),
        extraction_confidence="high",
        confidence_reason="ok",
        fetched_at="2026-04-21T00:00:00+00:00",
        # Refusal-first verdict stamped by the ingestor (no manifest hit).
        metadata={"language": "Python", "verified_interface": build_interface_verdict({}).as_metadata()},
    )

    result = await GitHubSummarizer(_client(), {}).summarize(ingest)

    payload = captured["payload"]
    # The verdict must have reached the closure: no fabricated token may be
    # *named* as a public interface (structural check — the authoritative one).
    for section in payload.detailed_summary:
        for token in _FABRICATED:
            assert token not in section.public_interfaces, (
                f"fabricated token {token!r} leaked into public_interfaces"
            )
    # And none of the surface-naming phrasings may assert the tokens. (We do
    # NOT assert on raw README prose echoes like ``</sub>`` — those substrings
    # are the source text itself, not a named interface.)
    blob = result.brief_summary + "\n" + "\n".join(
        b for s in payload.detailed_summary for b in s.bullets
    )
    assert "documented public surfaces include /sub" not in blob.lower()
    assert "public surfaces: `/sub`" not in blob.lower()
    assert "public surfaces: `/center`" not in blob.lower()
    assert "--please" not in blob.lower()
    # Refusal-first framing is asserted in the brief instead.
    assert "no verified interface artifact" in blob.lower()


def _client():
    class Client:
        generate = AsyncMock()

    return Client()
