from __future__ import annotations

import pytest

from website.features.summarization_engine.post_summary_transformation import (
    registry as reg,
)

_CORPUS = [
    "", " ", "x", "Format: lecture.", "r/IAmA first-time heroin risks",
    "Silk Road's Rise Fall", "Analysis of FT Piece: Rethinking Heterodox Policies in Polyc",
    "GitHub iOS arXiv NASA", "already Capitalized Title", "owner/repo",
]


@pytest.mark.parametrize("field_kind", list(reg.RULE_ORDER))
@pytest.mark.parametrize("src", [None, "youtube", "reddit", "arxiv", "newsletter", "github"])
@pytest.mark.parametrize("text", _CORPUS)
def test_every_registered_rule_pipeline_is_idempotent(field_kind, src, text):
    once = reg.apply_text_quality(text, source_type=src, field_kind=field_kind)
    twice = reg.apply_text_quality(once, source_type=src, field_kind=field_kind)
    assert once == twice, f"non-idempotent: {field_kind}/{src!r}/{text!r}"


def test_apply_sections_passthrough_when_no_rule():
    secs = [{"heading": "H", "bullets": ["b"], "sub_sections": {}}]
    assert reg.apply_sections(secs, source_type="web") == secs


def test_apply_sections_non_list_unchanged():
    assert reg.apply_sections(None, source_type="web") is None
