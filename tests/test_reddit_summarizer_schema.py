"""Offline tests for the Reddit summarization schema (iter-09 contract).

No network/LLM calls — these exercise the Pydantic validators that enforce the
label format, tag slot reservations, and brief-sentence repair."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from website.features.summarization_engine.summarization.reddit.schema import (
    RedditCluster,
    RedditDetailedPayload,
    RedditStructuredPayload,
)
from website.features.summarization_engine.summarization.reddit.summarizer import (
    _sanitize_payload_shape,
)


def _detailed(op_intent: str = "OP asks whether Roman roads still influence modern infrastructure.") -> RedditDetailedPayload:
    return RedditDetailedPayload(
        op_intent=op_intent,
        reply_clusters=[
            RedditCluster(
                theme="Construction techniques",
                reasoning="Most replies describe layered foundations, drainage, and maintenance norms.",
                examples=["concrete base layer"],
            ),
            RedditCluster(
                theme="Regional variation",
                reasoning="Other replies emphasize that road design varied significantly by province.",
                examples=[],
            ),
        ],
        counterarguments=["A minority dispute the dating of the earliest stretches."],
        unresolved_questions=["How much of the original network survives today?"],
        moderation_context=None,
    )


def test_schema_rejects_label_without_subreddit_prefix():
    with pytest.raises(ValidationError):
        RedditStructuredPayload(
            mini_title="Roman roads overview",
            brief_summary="Any content.",
            tags=["a", "b", "c", "d", "e", "f", "g", "h"],
            detailed_summary=_detailed(),
        )


def test_schema_accepts_valid_label_and_preserves_subreddit_tag():
    payload = RedditStructuredPayload(
        mini_title="r/AskHistorians Roman roads discussion",
        brief_summary=(
            "OP asked about Roman road longevity and maintenance. "
            "Most replies emphasised layered construction and drainage practice. "
            "A secondary cluster highlighted regional variation across provinces. "
            "Dissent pushed back on the dating of early stretches. "
            "Caveat: removed or missing comments may limit what is visible. "
            "An open question was how much of the network still survives."
        ),
        tags=["history", "rome", "infrastructure", "civil-engineering", "archaeology", "roads", "empire", "askhistorians"],
        detailed_summary=_detailed(),
    )
    assert payload.mini_title.startswith("r/AskHistorians")
    assert "r-askhistorians" in payload.tags
    assert 8 <= len(payload.tags) <= 10


def test_schema_requires_at_least_one_reply_cluster():
    with pytest.raises(ValidationError):
        RedditDetailedPayload(
            op_intent="OP asks something.",
            reply_clusters=[],
            counterarguments=[],
            unresolved_questions=[],
            moderation_context=None,
        )


def test_schema_rebuilds_brief_when_too_short():
    payload = RedditStructuredPayload(
        mini_title="r/IndianStockMarket rajkot ipo",
        brief_summary="Way too short.",  # violates 5-7 sentence contract
        tags=["india", "ipo", "market", "rajkot", "gmp", "investing", "retail", "analysis"],
        detailed_summary=_detailed("OP argues that Rajkot GMP dominance drives Hyundai IPO hype."),
    )
    sentences = [s for s in payload.brief_summary.split(". ") if s.strip()]
    assert len(sentences) >= 5, f"brief should be rebuilt to ≥5 sentences, got {payload.brief_summary!r}"
    assert "Caveat" in payload.brief_summary or "caveat" in payload.brief_summary.lower()


def test_schema_enforces_8_to_10_tag_range_with_reserved_slots():
    payload = RedditStructuredPayload(
        mini_title="r/tiny one",
        brief_summary=(
            "OP asked a short question. The dominant replies focused on a single theme. "
            "Consensus stayed around one interpretation. Dissent centered on a minority view. "
            "Caveat: removed or missing comments may limit what is visible."
        ),
        tags=["just", "a", "few", "custom", "tags", "here", "x", "y"],  # 8, minimum
        detailed_summary=_detailed(),
    )
    # Subreddit canonical tag must be reserved at position 0.
    assert payload.tags[0] == "r-tiny"
    assert 8 <= len(payload.tags) <= 10


def test_sanitize_payload_shape_rescues_collapsed_cluster_key():
    """Gemini occasionally emits a single cluster as a one-key dict where the
    key is the joined field list (``{"theme, reasoning, examples": "..."}``).
    The sanitizer must rescue it into a valid cluster object so Pydantic
    never sees a bad shape and the request never 500s."""
    raw = {
        "mini_title": "r/test example",
        "brief_summary": "",
        "tags": ["a", "b", "c", "d", "e", "f", "g", "h"],
        "detailed_summary": {
            "op_intent": "OP asks a question.",
            "reply_clusters": [
                {"theme, reasoning, examples": "Most commenters agree on X."}
            ],
            "counterarguments": [],
            "unresolved_questions": [],
            "moderation_context": None,
        },
    }
    sanitized = _sanitize_payload_shape(raw)
    clusters = sanitized["detailed_summary"]["reply_clusters"]
    assert len(clusters) == 1
    assert "theme" in clusters[0] and "reasoning" in clusters[0]
    # The full original value is preserved as reasoning so no facts are lost.
    assert "Most commenters agree on X." in clusters[0]["reasoning"]
    # Must pass full validation after sanitizing.
    payload = RedditStructuredPayload(**sanitized)
    assert payload.detailed_summary.reply_clusters[0].theme


def test_sanitize_payload_shape_rescues_dict_of_clusters():
    """If the LLM wraps clusters in an outer object keyed by theme name, the
    sanitizer flattens it into the expected list."""
    raw = {
        "mini_title": "r/test example",
        "brief_summary": "",
        "tags": ["a", "b", "c", "d", "e", "f", "g", "h"],
        "detailed_summary": {
            "op_intent": "OP asks a question.",
            "reply_clusters": {
                "agreement": {"reasoning": "Most agree.", "examples": []},
                "dissent": {"reasoning": "A minority push back.", "examples": []},
            },
            "counterarguments": [],
            "unresolved_questions": [],
            "moderation_context": None,
        },
    }
    sanitized = _sanitize_payload_shape(raw)
    clusters = sanitized["detailed_summary"]["reply_clusters"]
    assert len(clusters) == 2
    themes = {c["theme"] for c in clusters}
    assert themes == {"agreement", "dissent"}
    payload = RedditStructuredPayload(**sanitized)
    assert len(payload.detailed_summary.reply_clusters) == 2


def test_sanitize_payload_shape_strips_quoted_keys():
    """LLM sometimes double-escapes and emits keys like ``'"theme"'`` with
    literal surrounding quotes. The sanitizer must strip them before Pydantic
    rejects the shape."""
    raw = {
        '"mini_title"': "r/test example",
        '"brief_summary"': "",
        '"tags"': ["a", "b", "c", "d", "e", "f", "g", "h"],
        '"detailed_summary"': {
            '"op_intent"': "OP asks a question.",
            '"reply_clusters"': [
                {'"theme"': "agreement", '"reasoning"': "Most agree.", '"examples"': []}
            ],
            '"counterarguments"': [],
            '"unresolved_questions"': [],
            '"moderation_context"': None,
        },
    }
    sanitized = _sanitize_payload_shape(raw)
    payload = RedditStructuredPayload(**sanitized)
    assert payload.detailed_summary.reply_clusters[0].theme == "agreement"
    assert payload.detailed_summary.op_intent == "OP asks a question."


def test_schema_infers_thread_type_tag_for_experience_report():
    payload = RedditStructuredPayload(
        mini_title="r/IAmA first time heroin",
        brief_summary=(
            "OP described a first-time heroin experience. Replies warned about addiction risk. "
            "Consensus emphasised the addictive potential of even one use. Dissent came from users "
            "stressing autonomy. Caveat: removed comments may limit visibility. "
            "A secondary cluster discussed harm reduction."
        ),
        tags=["drugs", "iama", "health", "addiction", "reddit-iama", "experience", "warning", "personal"],
        detailed_summary=RedditDetailedPayload(
            op_intent="OP shares a first-time heroin experience.",
            reply_clusters=[
                RedditCluster(theme="addiction warnings", reasoning="Most replies warn about the addiction risk from first-time use.", examples=[]),
                RedditCluster(theme="autonomy dissent", reasoning="A minority emphasise personal choice and autonomy.", examples=[]),
            ],
            counterarguments=["Some argue adults have the right to experiment."],
            unresolved_questions=["What harm-reduction steps were in play?"],
            moderation_context=None,
        ),
    )
    assert "experience-report" in payload.tags
