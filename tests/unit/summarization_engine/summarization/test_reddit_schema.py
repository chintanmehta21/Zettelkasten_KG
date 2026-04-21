import pytest
from pydantic import ValidationError

from website.features.summarization_engine.summarization.reddit.schema import (
    RedditCluster,
    RedditDetailedPayload,
    RedditStructuredPayload,
)


def test_reddit_schema_rejects_bad_label_format():
    with pytest.raises(ValidationError):
        RedditStructuredPayload(
            mini_title="Just a title without subreddit prefix",
            brief_summary="...",
            tags=["a", "b", "c", "d", "e", "f", "g"],
            detailed_summary=RedditDetailedPayload(
                op_intent="OP asks about X.",
                reply_clusters=[RedditCluster(theme="Y", reasoning="...", examples=["e"])],
                counterarguments=[],
                unresolved_questions=[],
                moderation_context=None,
            ),
        )


def test_reddit_schema_accepts_valid_label():
    payload = RedditStructuredPayload(
        mini_title="r/AskHistorians Roman roads",
        brief_summary="...",
        tags=["history", "rome", "infrastructure", "reddit", "askhistorians", "expert-reply", "engineering"],
        detailed_summary=RedditDetailedPayload(
            op_intent="OP asks about Roman road construction.",
            reply_clusters=[RedditCluster(theme="Construction", reasoning="Layered", examples=["concrete"])],
            counterarguments=["Some dispute dating"],
            unresolved_questions=["Regional variation?"],
            moderation_context=None,
        ),
    )
    assert payload.mini_title.startswith("r/")
