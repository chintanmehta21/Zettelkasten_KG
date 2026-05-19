from __future__ import annotations

from website.features.summarization_engine.post_summary_transformation import (
    registry as reg,
)


def test_unregistered_field_is_byte_identical_passthrough():
    out = reg.apply_text_quality("anything at all", source_type=None, field_kind="unknown_kind")
    assert out == "anything at all"


def test_registered_rule_applies_only_to_its_key():
    reg.register(source_type=None, field_kind="t_demo")(lambda s: s.upper())
    assert reg.apply_text_quality("ab", source_type=None, field_kind="t_demo") == "AB"
    assert reg.apply_text_quality("ab", source_type=None, field_kind="other") == "ab"


def test_source_specific_rule_does_not_fire_for_other_source():
    reg.register(source_type="youtube", field_kind="t_src")(lambda s: s + "!")
    assert reg.apply_text_quality("x", source_type="youtube", field_kind="t_src") == "x!"
    assert reg.apply_text_quality("x", source_type="reddit", field_kind="t_src") == "x"
    # a None-source rule applies to ALL sources for its field_kind
    reg.register(source_type=None, field_kind="t_all")(lambda s: s + "?")
    assert reg.apply_text_quality("x", source_type="reddit", field_kind="t_all") == "x?"


def test_non_string_input_returns_unchanged():
    assert reg.apply_text_quality(None, source_type=None, field_kind="t_demo") is None
    assert reg.apply_text_quality(123, source_type=None, field_kind="t_demo") == 123


def test_rule_exception_is_swallowed_value_unchanged():
    def boom(_s):
        raise RuntimeError("nope")

    reg.register(source_type=None, field_kind="t_boom")(boom)
    assert reg.apply_text_quality("safe", source_type=None, field_kind="t_boom") == "safe"
