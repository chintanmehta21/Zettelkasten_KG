"""Spec 2B.1 / iter-03 plan §3.7: action-verb retrieval boost.

When a LOOKUP query contains an action verb (build, install, set up, ...),
GitHub / web sources get a +0.05 nudge and newsletter / youtube sources get
a -0.02 nudge. No effect on non-LOOKUP queries or queries without action verbs.
"""

from __future__ import annotations

import pytest

from website.features.rag_pipeline.retrieval.hybrid import _source_type_boost
from website.features.rag_pipeline.types import QueryClass


def test_action_verb_boosts_github() -> None:
    score = _source_type_boost(
        base_score=0.50,
        source_type="github",
        query_class=QueryClass.LOOKUP,
        question="how do I install zk for personal wiki?",
    )
    assert score == pytest.approx(0.55, abs=1e-6)


def test_action_verb_boosts_web() -> None:
    score = _source_type_boost(
        base_score=0.50,
        source_type="web",
        query_class=QueryClass.LOOKUP,
        question="set up a personal wiki tonight",
    )
    assert score == pytest.approx(0.55, abs=1e-6)


def test_action_verb_demotes_newsletter() -> None:
    score = _source_type_boost(
        base_score=0.50,
        source_type="newsletter",
        query_class=QueryClass.LOOKUP,
        question="set up a personal wiki tonight",
    )
    assert score == pytest.approx(0.48, abs=1e-6)


def test_action_verb_demotes_youtube_under_lookup() -> None:
    """LOOKUP + action verb on youtube -> -0.02, overriding the legacy LOOKUP-on-
    reddit path (youtube isn't reddit, so no +0.02)."""
    score = _source_type_boost(
        base_score=0.50,
        source_type="youtube",
        query_class=QueryClass.LOOKUP,
        question="how do I deploy this?",
    )
    assert score == pytest.approx(0.48, abs=1e-6)


def test_no_boost_without_action_verb() -> None:
    score = _source_type_boost(
        base_score=0.50,
        source_type="github",
        query_class=QueryClass.LOOKUP,
        question="who wrote the pragmatic engineer post?",
    )
    assert score == pytest.approx(0.50, abs=1e-6)


def test_no_action_verb_boost_for_non_lookup_class() -> None:
    """Action-verb boost is gated to LOOKUP. THEMATIC stays unchanged."""
    score = _source_type_boost(
        base_score=0.50,
        source_type="github",
        query_class=QueryClass.THEMATIC,
        question="how do I install zk?",
    )
    assert score == pytest.approx(0.50, abs=1e-6)


def test_legacy_thematic_youtube_affinity_preserved() -> None:
    """Legacy T10 affinity: THEMATIC + youtube -> +0.03. Must survive 2B.1."""
    score = _source_type_boost(
        base_score=0.50,
        source_type="youtube",
        query_class=QueryClass.THEMATIC,
        question="what are the recurring themes around personal wikis?",
    )
    assert score == pytest.approx(0.53, abs=1e-6)


def test_legacy_lookup_reddit_affinity_preserved_without_action_verb() -> None:
    """Legacy T10 affinity: LOOKUP + reddit -> +0.02 when no action verb."""
    score = _source_type_boost(
        base_score=0.50,
        source_type="reddit",
        query_class=QueryClass.LOOKUP,
        question="who wrote the pragmatic engineer post?",
    )
    assert score == pytest.approx(0.52, abs=1e-6)


def test_step_back_youtube_affinity_preserved() -> None:
    score = _source_type_boost(
        base_score=0.50,
        source_type="youtube",
        query_class=QueryClass.STEP_BACK,
        question="why does anyone build a wiki at all?",
    )
    assert score == pytest.approx(0.53, abs=1e-6)


def test_multi_word_action_verb_set_up_matches() -> None:
    """The 'set up' two-word verb must match (regex uses \\s+)."""
    score = _source_type_boost(
        base_score=1.00,
        source_type="github",
        query_class=QueryClass.LOOKUP,
        question="set up obsidian sync",
    )
    assert score == pytest.approx(1.05, abs=1e-6)


def test_action_verb_case_insensitive() -> None:
    score = _source_type_boost(
        base_score=0.50,
        source_type="github",
        query_class=QueryClass.LOOKUP,
        question="INSTALL the package",
    )
    assert score == pytest.approx(0.55, abs=1e-6)


def test_empty_question_returns_base_score() -> None:
    score = _source_type_boost(
        base_score=0.42,
        source_type="github",
        query_class=QueryClass.LOOKUP,
        question="",
    )
    assert score == pytest.approx(0.42, abs=1e-6)


def test_unknown_source_type_returns_base_score() -> None:
    score = _source_type_boost(
        base_score=0.42,
        source_type="podcast",
        query_class=QueryClass.LOOKUP,
        question="install the thing",
    )
    assert score == pytest.approx(0.42, abs=1e-6)
