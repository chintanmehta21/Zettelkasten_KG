from website.features.summarization_engine.summarization.common.json_utils import (
    parse_json_object,
)


def test_parse_json_object_ignores_trailing_text_after_balanced_object():
    parsed = parse_json_object('```json\n{"a": {"b": 1}}\n```\nextra commentary')

    assert parsed == {"a": {"b": 1}}


def test_parse_json_object_keeps_braces_inside_strings():
    parsed = parse_json_object('prefix {"text": "literal { brace }", "ok": true} suffix')

    assert parsed == {"text": "literal { brace }", "ok": True}
