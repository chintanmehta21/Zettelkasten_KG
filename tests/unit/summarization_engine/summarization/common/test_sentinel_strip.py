"""Tests for sentinel-tag stripping in the structured-extractor tag pipeline.

The ``_schema_fallback_`` sentinel (and any future ``_<name>_`` markers) must
keep flowing through the raw structured payload so evaluators can detect
schema-fallback routing bugs, but they must never reach the user-facing tag
list that hits the Obsidian note + KG node.
"""
from __future__ import annotations

import pytest

from website.features.summarization_engine.summarization.common.structured import (
    _BOILERPLATE_TAGS,
    _SENTINEL_TAG_RE,
    _normalize_tags,
    _strip_sentinel_tags,
)


class TestSentinelTagRegex:
    """``_SENTINEL_TAG_RE`` should match only single-leading + single-trailing
    underscore identifiers used for internal evaluator signalling."""

    @pytest.mark.parametrize(
        "tag",
        ["_schema_fallback_", "_raw_fallback_", "_low_confidence_"],
    )
    def test_matches_known_sentinels(self, tag: str) -> None:
        assert _SENTINEL_TAG_RE.match(tag) is not None

    @pytest.mark.parametrize(
        "tag",
        [
            "python",  # plain tag, no underscores
            "_underscore_at_start",  # leading underscore, no trailing
            "trailing_",  # trailing underscore, no leading
            "__double__",  # double-underscore on both ends
        ],
    )
    def test_rejects_non_sentinels(self, tag: str) -> None:
        assert _SENTINEL_TAG_RE.match(tag) is None


class TestStripSentinelTags:
    def test_removes_sentinels_preserving_order(self) -> None:
        tags = ["python", "_schema_fallback_", "ai", "_raw_fallback_", "ml"]
        assert _strip_sentinel_tags(tags) == ["python", "ai", "ml"]

    def test_leaves_non_sentinels_untouched(self) -> None:
        tags = ["python", "ai", "ml"]
        assert _strip_sentinel_tags(tags) == ["python", "ai", "ml"]

    def test_handles_empty_list(self) -> None:
        assert _strip_sentinel_tags([]) == []

    def test_does_not_mutate_input(self) -> None:
        tags = ["_schema_fallback_", "python"]
        original = list(tags)
        _strip_sentinel_tags(tags)
        assert tags == original

    def test_all_sentinels_returns_empty(self) -> None:
        assert _strip_sentinel_tags(["_schema_fallback_", "_raw_fallback_"]) == []


class TestNormalizeTagsStripsSentinels:
    def test_normalize_drops_schema_fallback_sentinel(self) -> None:
        result = _normalize_tags(
            ["_schema_fallback_", "python", "ai"],
            tags_min=2,
            tags_max=10,
        )
        assert "_schema_fallback_" not in result
        assert "python" in result
        assert "ai" in result

    def test_normalize_pads_after_stripping_when_fallback_path(self) -> None:
        # _schema_fallback_ is the ONLY tag in the raw payload (mirrors
        # _fallback_payload output). After stripping the sentinel, the
        # boilerplate-pad loop should still fire because allow_boilerplate_pad
        # is True and we're below tags_min.
        result = _normalize_tags(
            ["_schema_fallback_"],
            tags_min=3,
            tags_max=10,
            allow_boilerplate_pad=True,
            source_type_value="youtube",
        )
        assert "_schema_fallback_" not in result
        assert len(result) >= 3
        assert "youtube" in result
        # Remaining slots filled from boilerplate pool.
        boilerplate_hits = [t for t in result if t in _BOILERPLATE_TAGS]
        assert len(boilerplate_hits) >= 1

    def test_normalize_no_pad_when_boilerplate_disabled(self) -> None:
        # Default path (success route): no padding, sentinel still stripped.
        result = _normalize_tags(
            ["_schema_fallback_", "python"],
            tags_min=5,
            tags_max=10,
        )
        assert result == ["python"]
