"""Tests for the Slack Block Kit payload builder."""
from __future__ import annotations

from website.features.feedback.core.identity import Identity
from website.features.feedback.intake.models import FeedbackIntent
from website.features.feedback.slack.block_kit import build_feedback_blocks


def _identity(**kwargs) -> Identity:
    base = dict(
        full_name="Naruto Uzumaki",
        email="naruto@konoha.jp",
        country_label="India (IN)",   # <-- parens, not em-dash (operator 2026-05-27)
        is_anonymous=False,
    )
    base.update(kwargs)
    return Identity(**base)


def test_issue_uses_megaphone_emoji() -> None:
    blocks = build_feedback_blocks(
        intent=FeedbackIntent.ISSUE,
        subject="A subject",
        description="A description with at least ten chars.",
        identity=_identity(),
        feedback_id="FB-7K3Q",
        follow_up_email=False,
        slack_file_ids=[],
    )
    header = blocks[0]
    assert header["type"] == "header"
    assert "\U0001F4E3" in header["text"]["text"]  # 📣


def test_suggestion_uses_lightbulb_emoji() -> None:
    blocks = build_feedback_blocks(
        intent=FeedbackIntent.SUGGESTION,
        subject="A subject",
        description="A description with at least ten chars.",
        identity=_identity(),
        feedback_id="FB-ABCD",
        follow_up_email=False,
        slack_file_ids=[],
    )
    assert "\U0001F4A1" in blocks[0]["text"]["text"]  # 💡


def test_image_blocks_appear_per_file() -> None:
    blocks = build_feedback_blocks(
        intent=FeedbackIntent.ISSUE,
        subject="s",
        description="description with enough chars.",
        identity=_identity(),
        feedback_id="FB-AAAA",
        follow_up_email=False,
        slack_file_ids=["F100", "F200", "F300"],
    )
    image_blocks = [b for b in blocks if b["type"] == "image"]
    assert len(image_blocks) == 3
    assert image_blocks[0]["slack_file"]["id"] == "F100"
    assert image_blocks[2]["slack_file"]["id"] == "F300"


def test_zero_images_no_image_blocks() -> None:
    blocks = build_feedback_blocks(
        intent=FeedbackIntent.ISSUE,
        subject="s", description="description with enough chars.",
        identity=_identity(), feedback_id="FB-AAAA",
        follow_up_email=False, slack_file_ids=[],
    )
    assert not any(b["type"] == "image" for b in blocks)


def test_context_includes_name_country_id() -> None:
    blocks = build_feedback_blocks(
        intent=FeedbackIntent.ISSUE,
        subject="s", description="description with enough chars.",
        identity=_identity(), feedback_id="FB-7K3Q",
        follow_up_email=False, slack_file_ids=[],
    )
    context = next(b for b in blocks if b["type"] == "context")
    text = context["elements"][0]["text"]
    assert "Naruto Uzumaki" in text
    assert "India (IN)" in text     # <-- parens, not em-dash
    assert "FB-7K3Q" in text


def test_anonymous_context_says_anonymous() -> None:
    blocks = build_feedback_blocks(
        intent=FeedbackIntent.SUGGESTION,
        subject="s", description="description with enough chars.",
        identity=_identity(full_name="Anonymous", email=None, is_anonymous=True),
        feedback_id="FB-AAAA",
        follow_up_email=False, slack_file_ids=[],
    )
    context = next(b for b in blocks if b["type"] == "context")
    assert "Anonymous" in context["elements"][0]["text"]


def test_follow_up_email_appears_in_context_when_opted_in() -> None:
    blocks = build_feedback_blocks(
        intent=FeedbackIntent.ISSUE,
        subject="s", description="description with enough chars.",
        identity=_identity(),
        feedback_id="FB-AAAA",
        follow_up_email=True, slack_file_ids=[],
    )
    context = next(b for b in blocks if b["type"] == "context")
    assert "naruto@konoha.jp" in context["elements"][0]["text"]


def test_subject_in_section() -> None:
    blocks = build_feedback_blocks(
        intent=FeedbackIntent.ISSUE,
        subject="Add Zettel fails on long YouTube videos",
        description="Tried adding a 3-hour Lex Fridman episode and got a 504.",
        identity=_identity(),
        feedback_id="FB-AAAA",
        follow_up_email=False, slack_file_ids=[],
    )
    section = next(b for b in blocks if b["type"] == "section")
    text = section["text"]["text"]
    assert "Add Zettel fails on long YouTube videos" in text
    assert "Tried adding a 3-hour Lex Fridman" in text
