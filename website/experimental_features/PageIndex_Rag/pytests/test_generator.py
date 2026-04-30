from website.experimental_features.PageIndex_Rag.generator import (
    build_answer_prompt,
    generate_three_answers,
    select_final_answer,
)
from website.experimental_features.PageIndex_Rag.types import AnswerCandidate, EvidenceItem


def _evidence(node_id="yt-effective-public-speakin", text="Patrick Winston uses cycling structure and landmarks so audience attention can recover."):
    return [
        EvidenceItem(
            node_id=node_id,
            doc_id="doc",
            title="Effective Public Speaking Strategies",
            source_url="https://example.test",
            section="Captured Content",
            line_range="10,20",
            text=text,
            score=1.0,
        )
    ]


def _answer(style, text, cited=()):
    return AnswerCandidate(
        answer_id=style,
        style=style,
        text=text,
        cited_node_ids=tuple(cited),
        citations=(),
        metrics={},
    )


def test_prompt_tells_generator_to_map_paraphrases():
    prompt = build_answer_prompt(
        query="What does verbal punctuation mean?",
        evidence=_evidence(),
        style="direct",
    )
    assert "semantic equivalent" in prompt
    assert "complete answer" in prompt


def test_select_final_answer_prefers_full_supported_answer_over_refusal():
    selected = select_final_answer(
        query="What does verbal punctuation mean in Patrick Winston's talk?",
        evidence=_evidence(),
        answers=[
            _answer("direct", "The provided evidence does not contain verbal punctuation.", ()),
            _answer(
                "comparative",
                "Winston's talk treats verbal punctuation as recurring landmarks: tell the audience what is coming, say it, then tell them what was said so drifting attention can rejoin.",
                ("yt-effective-public-speakin",),
            ),
            _answer("exploratory", "It is about audience landmarks.", ("yt-effective-public-speakin",)),
        ],
    )
    assert selected[0].style == "comparative"


def test_select_final_answer_keeps_refusal_for_absent_topic():
    selected = select_final_answer(
        query="Summarize what this Kasten says about Notion database features.",
        evidence=_evidence(text="Patrick Winston discusses communication and speaking strategy."),
        answers=[
            _answer("direct", "The supplied Kasten has no information about Notion database features.", ()),
            _answer("comparative", "Install zk for a personal wiki with Markdown notes.", ("gh-zk-org-zk",)),
            _answer("exploratory", "Communication strategy uses cycling and landmarks.", ("yt-effective-public-speakin",)),
        ],
    )
    assert selected[0].style == "direct"


def test_select_final_answer_reorders_citations_toward_answer_support():
    selected = select_final_answer(
        query="Compare Jane Jacobs and cool roofs in this Kasten.",
        evidence=[
            _evidence("yt-urban-heat-islands-explained", "Urban heat islands involve asphalt and tree canopy.")[0],
            _evidence("web-cool-roofs-urban-heat", "Cool roofs use reflective surfaces to reduce indoor heat.")[0],
        ],
        answers=[
            _answer(
                "direct",
                "Cool roofs are covered as reflective surfaces that reduce indoor heat; Jane Jacobs is not covered.",
                ("yt-urban-heat-islands-explained", "web-cool-roofs-urban-heat"),
            ),
            _answer("comparative", "Cool roofs are mentioned.", ("web-cool-roofs-urban-heat",)),
            _answer("exploratory", "The Kasten covers urban heat.", ("yt-urban-heat-islands-explained",)),
        ],
    )
    assert selected[0].cited_node_ids[0] == "web-cool-roofs-urban-heat"


class FailingKeyPool:
    async def generate_content(self, *_args, **_kwargs):
        raise RuntimeError("temporary model failure")


def test_generate_three_answers_uses_extractive_fallback_on_model_failure():
    answers = __import__("asyncio").run(
        generate_three_answers(
            key_pool=FailingKeyPool(),
            query="What do cool roofs do?",
            evidence=_evidence("web-cool-roofs-urban-heat", "Cool roofs reduce indoor heat and peak electricity demand."),
        )
    )
    assert answers[0].cited_node_ids == ("web-cool-roofs-urban-heat",)
    assert answers[0].metrics["generator_fallback"] == 1.0
