import pytest
import re
from pydantic import ValidationError

from website.features.summarization_engine.summarization.reddit.schema import (
    RedditCluster,
    RedditDetailedPayload,
    RedditStructuredPayload,
)


def _base_payload_kwargs():
    return dict(
        mini_title="r/AskHistorians Roman roads",
        brief_summary="One short sentence only",
        tags=[
            "#history",
            "rome",
            "infrastructure",
            "reddit",
            "askhistorians",
            "expert-reply",
            "engineering",
        ],
        detailed_summary=RedditDetailedPayload(
            op_intent="OP asks about Roman road construction and maintenance.",
            reply_clusters=[
                RedditCluster(
                    theme="Construction",
                    reasoning="Most replies describe layered foundations, drainage, and long-term maintenance.",
                    examples=["concrete"],
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
    assert payload.tags[0] == "r-askhistorians"
    assert "q-and-a" in payload.tags
    assert len([s for s in re.split(r"(?<=[.!?])\s+", payload.brief_summary) if s.strip()]) >= 5


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


def test_reddit_schema_compacts_label_past_length_limit():
    payload = RedditStructuredPayload(
        **{
            **_base_payload_kwargs(),
            "mini_title": "r/AskHistorians " + ("a" * 61),
        }
    )

    assert len(payload.mini_title) <= 60


def test_reddit_schema_repairs_compact_label_and_hash_tags():
    payload = RedditStructuredPayload(
        **{
            **_base_payload_kwargs(),
            "mini_title": "r/AskHistorians A very long clipped title about roman roads and empires and maintenance",
        }
    )

    assert payload.mini_title.startswith("r/AskHistorians ")
    assert len(payload.mini_title) <= 60
    assert all(not tag.startswith("#") for tag in payload.tags)


def test_reddit_schema_marks_experience_report_for_first_time_drug_thread():
    payload = RedditStructuredPayload(
        mini_title="r/IAmA long title",
        brief_summary="One short sentence only",
        tags=["heroin", "opioids", "risk", "thread", "reddit", "ama", "warning"],
        detailed_summary=RedditDetailedPayload(
            op_intent="The original poster intended to share their first-time heroin experience and reaction.",
            reply_clusters=[
                RedditCluster(
                    theme="Addiction warnings",
                    reasoning="Former users warned about addiction risk and relapse.",
                    examples=["withdrawal"],
                ),
                RedditCluster(
                    theme="Minority dissent",
                    reasoning="A few replies argued one-time use does not guarantee addiction.",
                    examples=["special occasions"],
                ),
            ],
            counterarguments=["A minority said one-time use does not guarantee addiction."],
            unresolved_questions=["Did the OP experience nausea?"],
            moderation_context="High divergence was present.",
        ),
    )

    assert payload.mini_title == "r/IAmA first-time heroin risks"
    assert "experience-report" in payload.tags


def test_reddit_schema_preserves_thread_type_when_tags_are_full():
    payload = RedditStructuredPayload(
        mini_title="r/hinduism long title",
        brief_summary="Tiny brief",
        tags=[
            "atheism",
            "advaita-vedanta",
            "modern-physics",
            "consciousness-theory",
            "nima-arkani-hamed",
            "donald-hoffman",
            "emergent-spacetime",
            "conscious-agents",
            "spirituality",
            "philosophy",
        ],
        detailed_summary=RedditDetailedPayload(
            op_intent="OP shares a personal intellectual journey from atheism to Advaita Vedanta.",
            reply_clusters=[
                RedditCluster(
                    theme="Personal journeys from materialism to spirituality",
                    reasoning="Many users resonated with the same path.",
                    examples=["similar journey"],
                ),
                RedditCluster(
                    theme="Late discovery of indigenous philosophy",
                    reasoning="Some regretted discovering Vedanta late.",
                    examples=["westernized education"],
                ),
            ],
            counterarguments=["Some replies warned against grounding philosophy in mutable science."],
            unresolved_questions=["How much should science validate a spiritual framework?"],
            moderation_context="Rendered comments covered only part of the thread.",
        ),
    )

    assert payload.tags[0] == "r-hinduism"
    assert "experience-report" in payload.tags
    assert len(payload.tags) <= 10


def test_reddit_schema_rebuilds_five_sentence_brief_with_caveat():
    payload = RedditStructuredPayload(
        mini_title="r/hinduism long title",
        brief_summary="Short fragment",
        tags=[
            "atheism",
            "advaita-vedanta",
            "modern-physics",
            "consciousness-theory",
            "nima-arkani-hamed",
            "donald-hoffman",
            "spirituality",
        ],
        detailed_summary=RedditDetailedPayload(
            op_intent="OP shares a personal intellectual journey from atheism to Advaita Vedanta through science.",
            reply_clusters=[
                RedditCluster(
                    theme="Personal journeys from materialism to spirituality",
                    reasoning="Many users resonated with the same path.",
                    examples=["similar journey"],
                ),
                RedditCluster(
                    theme="Late discovery of indigenous philosophy",
                    reasoning="Some regretted discovering Vedanta late.",
                    examples=["westernized education"],
                ),
            ],
            counterarguments=["Some replies disputed using science as validation."],
            unresolved_questions=["What is the historical relationship between Vedanta and quantum mechanics?"],
            moderation_context="Rendered comments covered only part of the thread and removed comments were recovered.",
        ),
    )

    sentences = [s for s in re.split(r"(?<=[.!?])\s+", payload.brief_summary) if s.strip()]

    assert len(sentences) >= 5
    assert "Caveat:" in payload.brief_summary
