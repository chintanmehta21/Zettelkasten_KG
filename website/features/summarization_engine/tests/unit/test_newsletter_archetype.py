"""Tests for the local-heuristic newsletter archetype classifier.

These tests assert:
  1. Every documented archetype label is reachable from at least one
     plausible (title + brief + bullets) fixture — 2-3 fixtures per label.
  2. Empty / whitespace-only inputs return the default (never raise).
  3. URL hints tip close-score ties without overriding strong body signal.
  4. The result set is exactly the documented ``VALID_ARCHETYPES`` tuple.
"""
from __future__ import annotations

import pytest

from website.features.summarization_engine.summarization.newsletter.archetype import (
    VALID_ARCHETYPES,
    archetype_from_signals,
)


# ── happy-path fixtures ──────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "title, brief, bullets",
    [
        (
            "Scaling Postgres at 1M writes per second",
            "An engineering deep dive into partitioning, throughput, and latency.",
            [
                "Database write throughput bottlenecks under high fan-out.",
                "Architecture notes on sharding and replication protocols.",
            ],
        ),
        (
            "Designing a distributed kernel scheduler",
            "Microservice architecture notes on scaling and latency budgets.",
            ["Distributed tracing reveals protocol-level API bottlenecks."],
        ),
    ],
)
def test_engineering_essay(title, brief, bullets):
    assert archetype_from_signals(
        title=title, brief_summary=brief, detailed_bullets=bullets
    ) == "engineering_essay"


@pytest.mark.parametrize(
    "title, brief, bullets",
    [
        (
            "Q3 earnings: margins shrink as competition heats up",
            "Business analysis of revenue, valuation, and acquisition strategy.",
            [
                "Market cap reflects investor skepticism about margins.",
                "Competitive business model pressures are mounting.",
            ],
        ),
        (
            "Why this acquisition changes the market",
            "Strategy notes on revenue, margins, and competitive positioning.",
            ["Investors read earnings as a strategy signal."],
        ),
    ],
)
def test_business_analysis(title, brief, bullets):
    assert archetype_from_signals(
        title=title, brief_summary=brief, detailed_bullets=bullets
    ) == "business_analysis"


@pytest.mark.parametrize(
    "title, brief, bullets, url",
    [
        (
            "How I got promoted to Staff Engineer",
            "Career advice on hiring, interviews, and the engineering ladder.",
            [
                "My resume rewrite unlocked three job offers.",
                "Promoted after rewriting my promotion packet.",
            ],
            "",
        ),
        (
            "Hiring guide for new managers",
            "Step through the interview loop and what makes a manager promote-ready.",
            ["Career ladder expectations at each level."],
            "https://example.com/career/manager-guide",
        ),
    ],
)
def test_career_advice(title, brief, bullets, url):
    assert archetype_from_signals(
        title=title,
        brief_summary=brief,
        detailed_bullets=bullets,
        url=url,
    ) == "career_advice"


@pytest.mark.parametrize(
    "title, brief, bullets, url",
    [
        (
            "How to set up your first Rust project",
            "A step-by-step walkthrough and hands-on tutorial.",
            [
                "Getting started with cargo init.",
                "How to structure modules.",
            ],
            "https://example.com/tutorial/rust-setup",
        ),
        (
            "Walkthrough: deploy a Next.js app",
            "Hands-on tutorial, step by step.",
            ["How to configure environment variables."],
            "",
        ),
    ],
)
def test_tutorial(title, brief, bullets, url):
    assert archetype_from_signals(
        title=title,
        brief_summary=brief,
        detailed_bullets=bullets,
        url=url,
    ) == "tutorial"


@pytest.mark.parametrize(
    "title, brief, bullets, url",
    [
        (
            "This week in AI: issue #42",
            "Weekly digest — headlines, roundup, and in the news.",
            [
                "Newsletter #42: model launches, GPU shortages.",
                "In the news: chip export controls expand.",
            ],
            "",
        ),
        (
            "Weekly roundup: May highlights",
            "Digest of this week's developer news headlines.",
            ["Weekly issue #7 drops tomorrow."],
            "https://example.com/weekly/may-7",
        ),
    ],
)
def test_news_roundup(title, brief, bullets, url):
    assert archetype_from_signals(
        title=title,
        brief_summary=brief,
        detailed_bullets=bullets,
        url=url,
    ) == "news_roundup"


@pytest.mark.parametrize(
    "title, brief, bullets",
    [
        (
            "A hot take on remote work",
            "In my opinion, remote-first should be the default.",
            [
                "I think the hot take holds: companies should commit.",
                "IMO, the manifesto must be that people should choose.",
            ],
        ),
    ],
)
def test_opinion_piece(title, brief, bullets):
    assert archetype_from_signals(
        title=title, brief_summary=brief, detailed_bullets=bullets
    ) == "opinion_piece"


@pytest.mark.parametrize(
    "title, brief, bullets",
    [
        (
            "Looking back on my twenties",
            "Reflections on my journey — a memoir.",
            [
                "My story: when I was twenty, I grew up thinking work was everything.",
                "Looking back, the journey mattered more than the destination.",
            ],
        ),
    ],
)
def test_personal_essay(title, brief, bullets):
    assert archetype_from_signals(
        title=title, brief_summary=brief, detailed_bullets=bullets
    ) == "personal_essay"


# ── edge cases ───────────────────────────────────────────────────────────────


def test_empty_returns_default():
    assert archetype_from_signals(
        title="",
        brief_summary="",
        detailed_bullets=[],
    ) == "engineering_essay"


def test_whitespace_returns_default():
    assert archetype_from_signals(
        title="   ",
        brief_summary="\n\t ",
        detailed_bullets=["  "],
    ) == "engineering_essay"


def test_none_bullets_tolerated():
    assert archetype_from_signals(
        title="Architecture notes",
        brief_summary="Latency budget discussion.",
        detailed_bullets=None,
    ) == "engineering_essay"


def test_valid_archetypes_taxonomy():
    # Lock the exact taxonomy so a typo can't silently slip in.
    assert VALID_ARCHETYPES == (
        "engineering_essay",
        "business_analysis",
        "career_advice",
        "tutorial",
        "news_roundup",
        "opinion_piece",
        "personal_essay",
        "other",
    )


def test_url_hint_tips_close_tie():
    # Body text alone is archetype-neutral (no keywords). The URL hint
    # ``/weekly/`` should tip the result toward news_roundup.
    result = archetype_from_signals(
        title="May update",
        brief_summary="Some thoughts.",
        detailed_bullets=["Nothing notable."],
        url="https://example.com/weekly/may",
    )
    assert result == "news_roundup"


def test_strong_body_signal_beats_url_hint():
    # Body text is overwhelmingly engineering; a lone /tutorial/ URL
    # should NOT override it. Engineering keywords appear 5 times so the
    # +2 URL tip cannot flip the winner.
    result = archetype_from_signals(
        title="Architecture latency microservice throughput",
        brief_summary="Database scaling distributed architecture notes.",
        detailed_bullets=["Kernel protocol API code throughput."],
        url="https://example.com/tutorial/foo",
    )
    assert result == "engineering_essay"
