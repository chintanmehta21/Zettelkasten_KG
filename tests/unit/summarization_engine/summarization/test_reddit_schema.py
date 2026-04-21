import pytest
from pydantic import ValidationError

from website.features.summarization_engine.summarization.reddit.schema import (
    RedditCluster,
    RedditDetailedPayload,
    RedditStructuredPayload,
)


def _base_payload_kwargs():
    return dict(
        mini_title="r/AskHistorians Roman roads",
        brief_summary="...",
        tags=[
            "history",
            "rome",
            "infrastructure",
            "reddit",
            "askhistorians",
            "expert-reply",
            "engineering",
        ],
        detailed_summary=RedditDetailedPayload(
            op_intent="OP asks about Roman road construction.",
            reply_clusters=[
                RedditCluster(
                    theme="Construction", reasoning="Layered", examples=["concrete"]
                )
            ],
            counterarguments=["Some dispute dating"],
            unresolved_questions=["Regional variation?"],
            moderation_context=None,
        ),
    )


def test_reddit_schema_rejects_bad_label_format():
    with pytest.raises(ValidationError):
        RedditStructuredPayload(
            mini_title="Just a title without subreddit prefix",
            brief_summary="...",
            tags=["a", "b", "c", "d", "e", "f", "g"],
            detailed_summary=RedditDetailedPayload(
                op_intent="OP asks about X.",
                reply_clusters=[
                    RedditCluster(theme="Y", reasoning="...", examples=["e"])
                ],
                counterarguments=[],
                unresolved_questions=[],
                moderation_context=None,
            ),
        )


def test_reddit_schema_accepts_valid_label():
    payload = RedditStructuredPayload(**_base_payload_kwargs())
    assert payload.mini_title.startswith("r/")


def test_reddit_schema_rejects_missing_reply_clusters():
    with pytest.raises(ValidationError):
        RedditStructuredPayload(
            **{
                **_base_payload_kwargs(),
                "detailed_summary": RedditDetailedPayload(
                    op_intent="OP asks about Roman road construction.",
                    reply_clusters=[],
                    counterarguments=[],
                    unresolved_questions=[],
                    moderation_context=None,
                ),
            }
        )


def test_reddit_schema_rejects_label_past_length_limit():
    with pytest.raises(ValidationError):
        RedditStructuredPayload(
            **{
                **_base_payload_kwargs(),
                "mini_title": "r/AskHistorians " + ("a" * 61),
            }
        )
