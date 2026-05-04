"""iter-10 P4: anchor-seed un-gate + 4 defense-in-depth mitigations.

Drops the iter-09 ``(n_persons + n_entities) >= 1`` re-gate (q10 fix — NER
misses single-name surnames). Adds class exclusion, entity-length floor, and
a top-K cap so the un-gate doesn't regress THEMATIC pools.
"""
from __future__ import annotations

from website.features.rag_pipeline.retrieval.hybrid import (
    _should_inject_anchor_seeds,
)
from website.features.rag_pipeline.types import QueryClass


def test_lookup_with_anchor_nodes_injects_even_when_ner_zero():
    """q10 fix: NER may miss 'Steve Jobs' as person entity (single-name
    surname), but anchor_nodes was non-empty via tag/title match — that
    PROVES entity match at the kasten level. Don't double-filter on
    metadata.entities count."""
    decision = _should_inject_anchor_seeds(
        query_class=QueryClass.LOOKUP,
        compare_intent=False,
        anchor_nodes={"yt-steve-jobs-2005-stanford"},
        entities_resolving=["jobs"],
    )
    assert decision.fire is True


def test_thematic_class_excluded_even_with_anchor_nodes():
    """Defense-in-depth: THEMATIC must NEVER trigger anchor-seed inject so a
    misclassified q5-shape can't accidentally pull a single-name magnet."""
    decision = _should_inject_anchor_seeds(
        query_class=QueryClass.THEMATIC,
        compare_intent=False,
        anchor_nodes={"yt-steve-jobs-2005-stanford"},
        entities_resolving=["jobs"],
    )
    assert decision.fire is False
    assert "thematic" in decision.reason.lower()


def test_short_entity_length_floor_skips_inject():
    """Tag-collision protection: skip seed inject when ALL anchor-resolving
    entities are <4 chars. 'AI' or 'ML' generic tags can match every kasten."""
    decision = _should_inject_anchor_seeds(
        query_class=QueryClass.LOOKUP,
        compare_intent=False,
        anchor_nodes={"web-some-ai-thing", "gh-ml-tool"},
        entities_resolving=["AI", "ML"],
    )
    assert decision.fire is False
    assert "entity_length" in decision.reason


def test_mixed_short_and_long_entities_passes():
    """If at least one resolving entity is >=4 chars, allow inject."""
    decision = _should_inject_anchor_seeds(
        query_class=QueryClass.LOOKUP,
        compare_intent=False,
        anchor_nodes={"yt-naval-ravikant-podcast"},
        entities_resolving=["AI", "Naval"],
    )
    assert decision.fire is True


def test_compare_intent_passes_thematic_otherwise_excluded():
    """compare_intent (e.g. 'compare X and Y') is the ONLY exception that
    lets a THEMATIC-classified query inject seeds — morally a multi-LOOKUP."""
    decision = _should_inject_anchor_seeds(
        query_class=QueryClass.THEMATIC,
        compare_intent=True,
        anchor_nodes={"yt-jobs", "yt-naval"},
        entities_resolving=["Jobs", "Naval"],
    )
    assert decision.fire is True


def test_empty_anchor_nodes_no_inject():
    """Sanity: nothing to seed."""
    decision = _should_inject_anchor_seeds(
        query_class=QueryClass.LOOKUP,
        compare_intent=False,
        anchor_nodes=set(),
        entities_resolving=["whatever"],
    )
    assert decision.fire is False
