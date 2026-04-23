# tests/unit/summarization_engine/summarization/common/test_schema_fallback_floor.py
from __future__ import annotations

from datetime import datetime, timezone

from website.features.summarization_engine.core.config import EngineConfig
from website.features.summarization_engine.core.models import (
    IngestResult,
    SourceType,
)
from website.features.summarization_engine.summarization.common.structured import (
    _fallback_payload,
)


def _ingest(metadata: dict | None = None) -> IngestResult:
    return IngestResult(
        source_type=SourceType.YOUTUBE,
        url="https://youtube.com/watch?v=abc",
        original_url="https://youtube.com/watch?v=abc",
        raw_text="",
        metadata=metadata if metadata is not None else {
            "title": "Example video",
            "channel": "Example Channel",
        },
        extraction_confidence="medium",
        confidence_reason="test fixture",
        fetched_at=datetime.now(timezone.utc),
    )


def test_fallback_preserves_schema_fallback_tag():
    payload = _fallback_payload(
        _ingest(),
        "The speaker discusses X. Y is true. Z follows.",
        EngineConfig(),
    )
    assert "_schema_fallback_" in payload.tags


def test_fallback_emits_overview_section_not_bare_schema_fallback():
    payload = _fallback_payload(
        _ingest(),
        "The speaker discusses X. Y is true. Z follows.",
        EngineConfig(),
    )
    headings = [s.heading for s in payload.detailed_summary]
    assert headings[0] == "Overview"
    assert "schema_fallback" not in headings


def test_fallback_overview_contains_brief_as_bullet():
    payload = _fallback_payload(
        _ingest(),
        "First sentence. Second sentence. Third sentence.",
        EngineConfig(),
    )
    overview = payload.detailed_summary[0]
    joined = " ".join(
        overview.bullets
        + [b for _, bs in overview.sub_sections.items() for b in bs]
    )
    assert "First sentence" in joined


def test_fallback_brief_summary_is_non_empty():
    payload = _fallback_payload(_ingest(), "", EngineConfig())
    assert payload.brief_summary.strip()


def test_fallback_surfaces_channel_in_source_subsection():
    payload = _fallback_payload(
        _ingest({"title": "T", "channel": "Acme Channel"}),
        "A sentence.",
        EngineConfig(),
    )
    overview = payload.detailed_summary[0]
    assert "Source" in overview.sub_sections
    assert any("Acme Channel" in b for b in overview.sub_sections["Source"])


def test_fallback_additional_context_only_when_multi_sentence():
    single = _fallback_payload(_ingest({"title": "T"}), "Only one sentence.", EngineConfig())
    assert "Additional context" not in single.detailed_summary[0].sub_sections

    multi = _fallback_payload(
        _ingest({"title": "T"}),
        "One. Two. Three. Four. Five.",
        EngineConfig(),
    )
    assert "Additional context" in multi.detailed_summary[0].sub_sections
    assert len(multi.detailed_summary[0].sub_sections["Additional context"]) <= 3
