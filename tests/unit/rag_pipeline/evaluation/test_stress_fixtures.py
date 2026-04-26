"""Dimension B: stress fixtures (vague, out-of-corpus, multi-hop)."""
from __future__ import annotations

import pytest

from website.features.rag_pipeline.evaluation.eval_runner import (
    _REFUSAL_PHRASE, _refusal_query_score,
)
from website.features.rag_pipeline.evaluation.stress_fixtures import (
    REFUSAL_PHRASE,
    build_multi_hop_fixture,
    build_out_of_corpus_fixture,
    build_vague_query_fixture,
)


def test_vague_fixture_marks_clarification_behavior():
    q = build_vague_query_fixture()
    assert q.expected_behavior == "ask_clarification_or_refuse"
    assert q.question.strip() == "attention"
    assert q.reference_answer == REFUSAL_PHRASE
    assert REFUSAL_PHRASE == _REFUSAL_PHRASE  # boundary contract


def test_out_of_corpus_fixture_marks_refuse():
    q = build_out_of_corpus_fixture()
    assert q.expected_behavior == "refuse"
    assert "1789" in q.question  # off-corpus topic anchor
    assert q.reference_answer == REFUSAL_PHRASE


def test_multi_hop_fixture_requires_two_zettels():
    q = build_multi_hop_fixture()
    assert q.expected_behavior == "answer"
    assert "yt-andrej-karpathy-s-llm-in" in q.gold_node_ids
    assert "yt-lecun-s-vision-human-lev" in q.gold_node_ids
    assert len(q.atomic_facts) >= 2


def test_refusal_score_pass_when_canonical_phrase_present():
    q = build_out_of_corpus_fixture()
    answer = {"answer": f"{REFUSAL_PHRASE} Try a different angle."}
    assert _refusal_query_score(q, answer) == 1.0


def test_refusal_score_fail_when_hallucinated():
    q = build_out_of_corpus_fixture()
    answer = {"answer": "The Brittany delegate argued that feudal privileges..."}
    assert _refusal_query_score(q, answer) == 0.0
