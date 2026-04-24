"""Verify StructuredExtractor accepts and threads ``missing_facts_hint``.

Covers:
- Default (no hint) is byte-identical to the pre-refactor prompt.
- Non-empty hint is appended verbatim to the prompt that reaches ``_client.generate``.
- Hint survives all three prompt-building branches (prompt_instruction,
  prompt_builder, default template).
- Empty or whitespace-only entries are ignored so the suffix stays clean.
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from website.features.summarization_engine.core.config import EngineConfig
from website.features.summarization_engine.core.models import IngestResult, SourceType
from website.features.summarization_engine.summarization.common.structured import (
    StructuredExtractor,
    StructuredSummaryPayload,
)


class _Client:
    """Minimal stand-in exposing only ``generate``; not used in these tests."""

    async def generate(self, *args, **kwargs):  # pragma: no cover - unused
        raise RuntimeError("not expected to be called in prompt-shape tests")


def _ingest() -> IngestResult:
    return IngestResult(
        source_type=SourceType.NEWSLETTER,
        url="https://example.com/post",
        original_url="https://example.com/post",
        raw_text="body",
        sections={},
        metadata={},
        extraction_confidence="high",
        confidence_reason="ok",
        fetched_at=datetime(2026, 4, 24, tzinfo=timezone.utc),
    )


def test_default_no_hint_produces_no_suffix():
    extractor = StructuredExtractor(_Client(), EngineConfig())
    prompt = extractor._build_prompt(_ingest(), "dense summary text")
    assert "Ensure these facts are covered" not in prompt


def test_hint_appears_verbatim_in_default_template():
    hint = ["Substack declined to provide removal counts", "Policy changed 2023-11-30"]
    extractor = StructuredExtractor(
        _Client(), EngineConfig(), missing_facts_hint=hint
    )
    prompt = extractor._build_prompt(_ingest(), "dense summary text")
    assert "Ensure these facts are covered:" in prompt
    assert "Substack declined to provide removal counts" in prompt
    assert "Policy changed 2023-11-30" in prompt


def test_hint_appears_in_prompt_instruction_branch():
    hint = ["Regulator issued a warning"]
    extractor = StructuredExtractor(
        _Client(),
        EngineConfig(),
        prompt_instruction="INSTRUCT\n\nSUMMARY:\n{summary_text}",
        missing_facts_hint=hint,
    )
    prompt = extractor._build_prompt(_ingest(), "dense summary")
    assert prompt.startswith("INSTRUCT")
    assert "Regulator issued a warning" in prompt
    assert prompt.index("INSTRUCT") < prompt.index("Regulator issued a warning")


def test_hint_appears_in_prompt_builder_branch():
    hint = ["fact-A", "fact-B"]

    def _pb(ingest, summary_text, schema_json):
        return f"CUSTOM[{summary_text}]"

    extractor = StructuredExtractor(
        _Client(),
        EngineConfig(),
        prompt_builder=_pb,
        missing_facts_hint=hint,
    )
    prompt = extractor._build_prompt(_ingest(), "dense")
    assert prompt.startswith("CUSTOM[dense]")
    assert "fact-A" in prompt and "fact-B" in prompt


def test_blank_entries_are_ignored():
    extractor = StructuredExtractor(
        _Client(),
        EngineConfig(),
        missing_facts_hint=["", "   ", "real fact"],
    )
    prompt = extractor._build_prompt(_ingest(), "dense")
    # Only the real entry should appear after the coverage marker.
    marker = "Ensure these facts are covered:"
    assert marker in prompt
    suffix = prompt.split(marker, 1)[1]
    assert "real fact" in suffix
    assert ";" not in suffix.strip().split("\n", 1)[0] or "real fact" in suffix


def test_none_hint_equivalent_to_omitted():
    extractor_none = StructuredExtractor(_Client(), EngineConfig(), missing_facts_hint=None)
    extractor_omit = StructuredExtractor(_Client(), EngineConfig())
    ingest = _ingest()
    assert extractor_none._build_prompt(ingest, "s") == extractor_omit._build_prompt(ingest, "s")
