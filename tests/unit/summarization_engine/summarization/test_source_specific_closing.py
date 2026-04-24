"""Source-specific closing remarks labels.

Locks the contract that each source's Closing remarks bullet is prefixed with
a source-specific verb so downstream readers can tell at a glance what kind
of wrap-up they're reading (YouTube recap vs Reddit resolution vs GitHub
roadmap vs Newsletter call-to-action).
"""
from __future__ import annotations

from website.features.summarization_engine.summarization.youtube.layout import (
    compose_youtube_detailed,
)
from website.features.summarization_engine.summarization.youtube.schema import (
    ChapterBullet,
    YouTubeDetailedPayload,
    YouTubeStructuredPayload,
)
from website.features.summarization_engine.summarization.reddit.layout import (
    compose_reddit_detailed,
)
from website.features.summarization_engine.summarization.reddit.schema import (
    RedditCluster,
    RedditDetailedPayload,
    RedditStructuredPayload,
)
from website.features.summarization_engine.summarization.github.layout import (
    compose_github_detailed,
)
from website.features.summarization_engine.summarization.github.schema import (
    GitHubDetailedSection,
    GitHubStructuredPayload,
)
from website.features.summarization_engine.summarization.newsletter.layout import (
    compose_newsletter_detailed,
)
from website.features.summarization_engine.summarization.newsletter.schema import (
    NewsletterDetailedPayload,
    NewsletterSection,
    NewsletterStructuredPayload,
)


def _closing_bullet(sections) -> str:
    closing = next(s for s in sections if s.heading == "Closing remarks")
    assert closing.bullets, "Closing remarks must have a bullet"
    return closing.bullets[0]


def test_youtube_closing_starts_with_recap():
    payload = YouTubeStructuredPayload(
        mini_title="t",
        brief_summary="A. B. C. D. E. F.",
        tags=["a", "b", "c", "d", "e", "f", "g"],
        speakers=["S"],
        entities_discussed=[],
        detailed_summary=YouTubeDetailedPayload(
            thesis="Point.",
            format="lecture",
            chapters_or_segments=[
                ChapterBullet(timestamp="00:00", title="X", bullets=["a.", "b.", "c.", "d.", "e."])
            ],
            demonstrations=[],
            closing_takeaway="Study further.",
        ),
    )
    bullet = _closing_bullet(compose_youtube_detailed(payload))
    assert bullet.lower().startswith("recap")


def test_reddit_closing_starts_with_resolution():
    payload = RedditStructuredPayload(
        mini_title="r/x topic",
        brief_summary="A. B. C. D. E. F.",
        tags=["a", "b", "c", "d", "e", "f", "g"],
        detailed_summary=RedditDetailedPayload(
            op_intent="Asking something.",
            reply_clusters=[RedditCluster(theme="t", reasoning="r")],
            counterarguments=[],
            unresolved_questions=["Does it scale"],
            moderation_context=None,
        ),
    )
    bullet = _closing_bullet(compose_reddit_detailed(payload))
    assert bullet.lower().startswith("resolution")


def test_github_closing_starts_with_roadmap():
    payload = GitHubStructuredPayload(
        mini_title="foo/bar",
        architecture_overview=(
            "The project is a Python package with a clean module split. "
            "It exposes a thin runtime API for callers to orchestrate jobs end to end."
        ),
        brief_summary=(
            "A Python library that orchestrates background jobs with a minimal surface. "
            "It emphasises type safety and structured logging for production teams."
        ),
        tags=["a", "b", "c", "d", "e", "f", "g"],
        detailed_summary=[
            GitHubDetailedSection(
                heading="Core",
                module_or_feature="core",
                main_stack=["python"],
                bullets=["does things."],
                public_interfaces=["run()"],
                usability_signals=["CI green"],
            )
        ],
        benchmarks_tests_examples=[],
    )
    bullet = _closing_bullet(compose_github_detailed(payload))
    assert bullet.lower().startswith("roadmap")


def test_newsletter_closing_starts_with_call_to_action():
    payload = NewsletterStructuredPayload(
        mini_title="Issue",
        brief_summary="A. B. C. D. E. F.",
        tags=["a", "b", "c", "d", "e", "f", "g"],
        detailed_summary=NewsletterDetailedPayload(
            publication_identity="Pub",
            issue_thesis="Thesis statement.",
            stance="neutral",
            sections=[NewsletterSection(heading="H", bullets=["pt1.", "pt2."])],
            conclusions_or_recommendations=["Keep watching."],
            cta="Subscribe now",
        ),
    )
    bullet = _closing_bullet(compose_newsletter_detailed(payload))
    assert bullet.lower().startswith("call to action")
