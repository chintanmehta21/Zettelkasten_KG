"""Tests for the cross-source reserved-tag slot pattern in
``common.structured._normalize_tags``.

These cover the contract that reserved tags survive truncation, dedupe
correctly against topical tags, default behavior is unchanged when no
``reserved`` kwarg is passed, and the cap (``tags_max``) is respected even
when reserved + topical exceed it.
"""
from __future__ import annotations

from website.features.summarization_engine.summarization.common.structured import (
    _normalize_tags,
)


def test_reserved_tags_placed_first_then_topical():
    """Reserved tags appear in order at the head of the list, followed by
    topical tags in their original order."""
    out = _normalize_tags(
        ["alpha", "beta", "gamma"],
        tags_min=0,
        tags_max=10,
        reserved=["zeta", "eta"],
    )
    assert out == ["zeta", "eta", "alpha", "beta", "gamma"]


def test_reserved_tags_dedup_against_topical():
    """When a topical tag matches a reserved entry, the topical copy is
    suppressed so the tag appears only once (in its reserved slot)."""
    out = _normalize_tags(
        ["alpha", "zeta", "beta"],
        tags_min=0,
        tags_max=10,
        reserved=["zeta"],
    )
    assert out == ["zeta", "alpha", "beta"]
    assert out.count("zeta") == 1


def test_default_behavior_byte_identical_without_reserved():
    """Calling without ``reserved`` matches the legacy contract exactly:
    same cleaning, same dedupe, same cap, no padding when
    ``allow_boilerplate_pad`` defaults to False."""
    raw = ["Hello World", "hello-world", "  spaced  ", "alpha"]
    out = _normalize_tags(raw, tags_min=0, tags_max=10)
    assert out == ["hello-world", "spaced", "alpha"]


def test_default_behavior_with_boilerplate_pad_unchanged():
    """The legacy boilerplate-pad path (used by schema fallbacks) must keep
    working when ``reserved`` is None."""
    out = _normalize_tags(
        ["alpha"],
        tags_min=4,
        tags_max=10,
        allow_boilerplate_pad=True,
        source_type_value="github",
    )
    assert out[0] == "alpha"
    assert "github" in out
    assert len(out) >= 4


def test_cap_respected_when_reserved_plus_topical_exceeds_max():
    """When reserved + topical > ``tags_max``, the result is truncated to
    the cap with reserved kept intact at the head."""
    topical = [f"topic-{i}" for i in range(15)]
    out = _normalize_tags(
        topical,
        tags_min=0,
        tags_max=10,
        reserved=["alpha", "beta", "gamma"],
    )
    assert out[:3] == ["alpha", "beta", "gamma"]
    assert len(out) == 10
    # Topical fills the remaining 7 slots in original order.
    assert out[3:] == ["topic-0", "topic-1", "topic-2", "topic-3", "topic-4", "topic-5", "topic-6"]


def test_reserved_alone_truncated_to_cap():
    """Reserved exceeding ``tags_max`` is itself truncated; topical is
    dropped because there is no room left."""
    reserved = [f"r{i}" for i in range(12)]
    out = _normalize_tags(
        ["topical"],
        tags_min=0,
        tags_max=10,
        reserved=reserved,
    )
    assert len(out) == 10
    assert out == reserved[:10]


def test_reserved_empty_list_is_legacy_path():
    """``reserved=[]`` (falsy) takes the legacy path — no reordering."""
    out = _normalize_tags(
        ["alpha", "beta"],
        tags_min=0,
        tags_max=10,
        reserved=[],
    )
    assert out == ["alpha", "beta"]


def test_reserved_normalized_with_default_cleaner():
    """Reserved tags are run through the same cleaner as topical tags
    (default: lower + spaces -> dashes)."""
    out = _normalize_tags(
        ["topical"],
        tags_min=0,
        tags_max=10,
        reserved=["My Brand"],
    )
    assert out == ["my-brand", "topical"]


def test_custom_tag_cleaner_applies_to_reserved_and_topical():
    """A custom ``tag_cleaner`` is applied uniformly to both reserved and
    topical tags so they dedupe correctly after normalization."""
    import re

    def reddit_cleaner(t):
        return re.sub(r"[^a-z0-9+-]+", "-", str(t).strip().lower()).strip("-")

    out = _normalize_tags(
        ["Hello, World!", "alpha"],
        tags_min=0,
        tags_max=10,
        reserved=["r/Python", "discussion"],
        tag_cleaner=reddit_cleaner,
    )
    # "r/Python" -> "r-python", "Hello, World!" -> "hello-world"
    assert out[0] == "r-python"
    assert out[1] == "discussion"
    assert "hello-world" in out
    assert "alpha" in out


def test_reserved_with_boilerplate_pad_pads_after_reserved():
    """When reserved is set AND ``allow_boilerplate_pad=True``, padding
    fills remaining slots up to ``tags_min`` after reserved+topical."""
    out = _normalize_tags(
        ["alpha"],
        tags_min=5,
        tags_max=10,
        allow_boilerplate_pad=True,
        source_type_value="reddit",
        reserved=["r-python"],
    )
    assert out[0] == "r-python"
    assert "alpha" in out
    assert len(out) >= 5
