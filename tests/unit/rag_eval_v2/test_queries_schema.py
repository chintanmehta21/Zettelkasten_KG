"""queries.json schema validity for BOTH rag_eval_v2 Kastens.

Mirrors the iter-11 schema exactly: _meta{kasten_slug,kasten_name,
members_node_ids,source_type_breakdown,ci_gates_summary} +
queries[]{qid,class,tests,text,expected_primary_citation,
expected_minimum_citations,ground_truth}.

Also checks the gold/GoldQuery contract: _build_gold_queries must accept
every query (>=1 gold OR refusal-expected) so EvalRunner won't choke.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
RAG_EVAL_V2 = ROOT / "docs" / "rag_eval_v2"
KASTENS = ("psychedelic-drugs", "economics")
_VALID_CLASSES = {"lookup", "thematic", "multi_hop", "vague", "step_back", "adversarial"}


@pytest.fixture(params=KASTENS)
def queries_doc(request):
    path = RAG_EVAL_V2 / request.param / "queries.json"
    return request.param, json.loads(path.read_text(encoding="utf-8"))


def test_meta_block_complete(queries_doc):
    slug, doc = queries_doc
    meta = doc["_meta"]
    assert meta["kasten_slug"] == slug
    assert meta["kasten_name"]
    assert "members_node_ids" in meta            # resolved at runtime
    assert isinstance(meta["source_type_breakdown"], dict)
    assert meta["source_type_breakdown"]
    gates = meta["ci_gates_summary"]
    for k in ("end_to_end_gold_at_1_min", "synthesizer_grounding_min",
              "infra_failures_max", "max_per_source_top1_share"):
        assert k in gates


def test_query_count_and_class_coverage(queries_doc):
    _slug, doc = queries_doc
    qs = doc["queries"]
    assert 10 <= len(qs) <= 14
    classes = {q["class"] for q in qs}
    # must cover lookup / thematic / multi_hop / vague at minimum
    assert {"lookup", "thematic", "multi_hop", "vague"} <= classes
    assert classes <= _VALID_CLASSES


def test_every_query_well_formed(queries_doc):
    _slug, doc = queries_doc
    seen = set()
    for q in doc["queries"]:
        assert q["qid"] and q["qid"] not in seen
        seen.add(q["qid"])
        assert q["class"] in _VALID_CLASSES
        assert q["tests"]
        assert q["text"]
        assert "expected_primary_citation" in q
        assert isinstance(q["expected_minimum_citations"], int)
        assert q["ground_truth"]
        # adversarial/refusal: empty expected + 0 min citations
        if q["class"] == "adversarial":
            assert q["expected_primary_citation"] == []
            assert q["expected_minimum_citations"] == 0
        else:
            assert q["expected_primary_citation"]  # non-empty title substring(s)


def test_source_type_breakdown_has_three_plus_types(queries_doc):
    _slug, doc = queries_doc
    assert len(doc["_meta"]["source_type_breakdown"]) >= 3


def test_links_file_has_eight_to_ten_across_three_sources(queries_doc):
    slug, _doc = queries_doc
    links = [
        ln.strip()
        for ln in (RAG_EVAL_V2 / slug / "links.txt").read_text(encoding="utf-8").splitlines()
        if ln.strip()
    ]
    assert 8 <= len(links) <= 10
    # no google.com/search redirect wrappers, no pdf, no oup paywall
    for ln in links:
        assert "google.com/search" not in ln
        assert not ln.endswith(".pdf")
        assert "academic.oup.com" not in ln
    # >=3 distinct source hosts/types heuristic
    kinds = set()
    for ln in links:
        if "youtube.com" in ln:
            kinds.add("youtube")
        elif "reddit.com" in ln:
            kinds.add("reddit")
        elif "github.com" in ln:
            kinds.add("github")
        elif "substack.com" in ln:
            kinds.add("substack")
        elif "arxiv.org" in ln or "medium.com" in ln:
            kinds.add("web")
    assert len(kinds) >= 3


def test_build_gold_queries_accepts_every_query(queries_doc):
    """The reused offline _build_gold_queries must not reject any query.

    Refusal queries get the __refuse__ sentinel; answer queries need a
    resolved gold id, supplied here via expected_overrides (the harness
    resolves title->zettel at runtime; the schema test simulates it)."""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from ops.scripts.score_rag_eval import _build_gold_queries

    _slug, doc = queries_doc
    overrides = {
        q["qid"]: (["z-fake-gold"] if q["class"] != "adversarial" else [])
        for q in doc["queries"]
    }
    gold = _build_gold_queries(doc, overrides)
    assert len(gold) == len(doc["queries"])
    by_id = {g.id: g for g in gold}
    for q in doc["queries"]:
        g = by_id[q["qid"]]
        assert g.gold_node_ids  # GoldQuery min_length=1 satisfied
        assert g.atomic_facts
        if q["class"] == "adversarial":
            assert g.expected_behavior in ("refuse", "ask_clarification_or_refuse")


def test_baseline_score_json_present_and_legacy_mapped(queries_doc):
    slug, _doc = queries_doc
    bs = json.loads(
        (RAG_EVAL_V2 / slug / "baseline_score.json").read_text(encoding="utf-8")
    )
    assert bs["composite"] == 60.26
    assert bs["weights"] == {
        "chunking": 0.1, "retrieval": 0.25, "reranking": 0.2, "synthesis": 0.45,
    }
    assert "mapping_note" in bs and "NOT" in bs["mapping_note"]
