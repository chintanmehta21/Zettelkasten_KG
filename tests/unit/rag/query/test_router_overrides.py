"""iter-09 RES-6: router rule-5 narrowing + new override rules."""
import pytest
from website.features.rag_pipeline.query.router import apply_class_overrides
from website.features.rag_pipeline.types import QueryClass


# Narrowed rule 5: word_count threshold is 25 (was 18).
def test_rule5_narrow_22_word_lookup_no_persons_stays_lookup():
    """22-word LOOKUP (q13-shape) must stay LOOKUP."""
    q = (
        "What does the Pragmatic Engineer newsletter mean by a product-minded "
        "engineer and how it differs from implementation-focused"
    )
    cls, reason = apply_class_overrides(q, QueryClass.LOOKUP, person_entities=[])
    assert cls is QueryClass.LOOKUP
    assert reason is None or reason != "override_long_query_upgrade"


def test_rule5_narrow_19_word_matuschak_lookup_stays_lookup():
    """19-word LOOKUP (q14-shape) must stay LOOKUP."""
    q = (
        "In Matuschak's Transformative Tools for Thought essay what specifically "
        "does he mean by an augmented book"
    )
    cls, reason = apply_class_overrides(q, QueryClass.LOOKUP, person_entities=[])
    assert cls is QueryClass.LOOKUP


def test_rule5_still_fires_at_25_words_no_persons():
    """At >=25 words rule 5 still upgrades to MULTI_HOP (q3-shape protection)."""
    q = " ".join(["word"] * 25 + ["?"])
    cls, reason = apply_class_overrides(q, QueryClass.LOOKUP, person_entities=[])
    assert cls is QueryClass.MULTI_HOP
    assert reason == "override_long_query_upgrade"


# New rules from iter-09 item 5C
def test_double_question_mark_routes_to_multi_hop():
    cls, reason = apply_class_overrides(
        "What is X? And what is Y?", QueryClass.LOOKUP, person_entities=[]
    )
    assert cls is QueryClass.MULTI_HOP
    assert reason == "override_double_question"


def test_single_question_mark_does_not_route_multi_hop():
    cls, reason = apply_class_overrides(
        "What is X?", QueryClass.LOOKUP, person_entities=[]
    )
    assert cls is QueryClass.LOOKUP


def test_how_does_relate_to_routes_multi_hop():
    cls, reason = apply_class_overrides(
        "how does X relate to Y", QueryClass.LOOKUP, person_entities=[]
    )
    assert cls is QueryClass.MULTI_HOP
    assert reason == "override_relate_pattern"


def test_how_does_work_does_not_match_relate():
    cls, reason = apply_class_overrides(
        "how does X work", QueryClass.LOOKUP, person_entities=[]
    )
    assert cls is QueryClass.LOOKUP


def test_summary_of_routes_thematic():
    cls, reason = apply_class_overrides(
        "summary of the kasten", QueryClass.LOOKUP, person_entities=[]
    )
    assert cls is QueryClass.THEMATIC
    assert reason == "override_summary_of_pattern"


def test_summary_table_does_not_match():
    cls, reason = apply_class_overrides(
        "summary table for the report", QueryClass.LOOKUP, person_entities=[]
    )
    assert cls is QueryClass.LOOKUP
