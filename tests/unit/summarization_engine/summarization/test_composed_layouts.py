"""Round-trip tests for the Reddit / GitHub / Newsletter composed layouts.

These lock the contract that every source emits Overview + Closing remarks
with populated sub_sections (no raw schema-key headings, no JSON-string
bullets) and that the shared text-guard strips dangling-tail sentences.
"""
from __future__ import annotations

from website.features.summarization_engine.summarization.common.text_guards import (
    ends_with_dangling_word,
    repair_or_drop,
)
from website.features.summarization_engine.summarization.github.layout import (
    compose_github_detailed,
)
from website.features.summarization_engine.summarization.github.schema import (
    GitHubStructuredPayload,
)
from website.features.summarization_engine.summarization.newsletter.layout import (
    compose_newsletter_detailed,
)
from website.features.summarization_engine.summarization.newsletter.schema import (
    NewsletterStructuredPayload,
)
from website.features.summarization_engine.summarization.reddit.layout import (
    compose_reddit_detailed,
)
from website.features.summarization_engine.summarization.reddit.schema import (
    RedditStructuredPayload,
)


def test_reddit_layout_emits_overview_clusters_and_closing():
    payload = RedditStructuredPayload(
        mini_title="r/india gmp-rajkot claim disputed",
        brief_summary=(
            "OP claims Rajkot drives IPO GMP numbers. "
            "Replies push back. Mumbai is cited. Data is thin. "
            "Mods removed several posts. Thread still open."
        ),
        tags=["india", "ipo", "gmp", "rajkot", "reddit-india", "investing", "grey-market"],
        detailed_summary={
            "op_intent": "seek validation for rajkot gmp claim",
            "reply_clusters": [
                {
                    "theme": "Skeptical of data",
                    "reasoning": "No primary source was provided",
                    "examples": ["GMP varies across brokers"],
                },
                {
                    "theme": "Supportive anecdotes",
                    "reasoning": "Some traders report the same",
                    "examples": [],
                },
            ],
            "counterarguments": ["Mumbai brokers dominate the grey market"],
            "unresolved_questions": ["Can anyone produce broker tape?"],
            "moderation_context": "Mods removed low-effort replies",
        },
    )
    sections = compose_reddit_detailed(payload)
    headings = [s.heading for s in sections]
    assert headings[0] == "Overview"
    assert headings[-1] == "Closing remarks"
    assert "Reply clusters" in headings
    clusters = next(s for s in sections if s.heading == "Reply clusters")
    assert "Skeptical of data" in clusters.sub_sections
    assert clusters.sub_sections["Skeptical of data"]  # non-empty
    overview = sections[0]
    assert "OP intent" in overview.sub_sections
    assert "Moderation context" in overview.sub_sections


def test_github_layout_emits_overview_features_and_closing():
    payload = GitHubStructuredPayload(
        mini_title="fastapi/fastapi",
        architecture_overview=(
            "FastAPI is an ASGI framework using pydantic for validation. "
            "It layers on top of Starlette for the request pipeline. "
            "OpenAPI schemas are generated automatically from type hints."
        ),
        brief_summary="High-performance Python API framework with type-safe routes.",
        tags=["fastapi", "python", "asgi", "starlette", "pydantic", "openapi", "webdev"],
        benchmarks_tests_examples=["pytest suite covers routing and dependencies"],
        detailed_summary=[
            {
                "heading": "Routing",
                "bullets": ["APIRouter groups endpoints", "Decorators bind HTTP verbs"],
                "module_or_feature": "routing",
                "main_stack": ["Starlette"],
                "public_interfaces": ["APIRouter", "Depends"],
                "usability_signals": ["Type hints drive validation"],
            }
        ],
    )
    sections = compose_github_detailed(payload)
    headings = [s.heading for s in sections]
    assert headings[0] == "Overview"
    assert "Features and modules" in headings
    assert "Benchmarks and examples" in headings
    assert headings[-1] == "Closing remarks"
    features = next(s for s in sections if s.heading == "Features and modules")
    assert "Routing" in features.sub_sections
    bullets = features.sub_sections["Routing"]
    assert any("Public surface" in b for b in bullets)


def test_newsletter_layout_emits_overview_sections_and_closing():
    payload = NewsletterStructuredPayload(
        mini_title="stratechery ai disruption playbook",
        brief_summary=(
            "Stratechery argues platforms lock in users. "
            "The post compares FAANG to rising AI incumbents. "
            "Distribution is the moat. Models commoditize. Subscribers keep value."
        ),
        tags=["stratechery", "ai", "platforms", "strategy", "moats", "distribution", "business-strategy"],
        detailed_summary={
            "publication_identity": "Stratechery by Ben Thompson",
            "issue_thesis": "Distribution outlasts model quality in AI platform economics",
            "sections": [
                {
                    "heading": "Why distribution wins",
                    "bullets": ["Users accrue to the default app", "Switching cost rises with data"],
                },
                {
                    "heading": "What the incumbents do next",
                    "bullets": ["Bundle AI into existing flows"],
                },
            ],
            "conclusions_or_recommendations": [
                "Operators should invest in distribution, not foundation training",
                "Evaluate OpenAI/MSFT bundling risk quarterly",
            ],
            "stance": "skeptical",
            "cta": "Subscribe for the Monday interview",
        },
    )
    sections = compose_newsletter_detailed(payload)
    headings = [s.heading for s in sections]
    assert headings[0] == "Overview"
    assert "Section walkthrough" in headings
    assert "Conclusions and recommendations" in headings
    assert headings[-1] == "Closing remarks"
    overview = sections[0]
    assert "Publication" in overview.sub_sections
    assert "Stance" in overview.sub_sections


def test_text_guard_detects_and_drops_dangling_tail():
    assert ends_with_dangling_word("The main takeaway is DMT is a powerful.")
    repaired = repair_or_drop(
        "DMT crosses the blood-brain barrier rapidly. "
        "The main takeaway is DMT is a powerful."
    )
    # The bad trailing sentence is dropped; the first complete sentence survives.
    assert repaired == "DMT crosses the blood-brain barrier rapidly."


def test_text_guard_preserves_valid_sentence():
    good = "The study found that DMT modulates serotonergic pathways."
    assert repair_or_drop(good) == good


def test_text_guard_drops_lone_dangling_sentence():
    assert repair_or_drop("It feels powerful.") == ""
