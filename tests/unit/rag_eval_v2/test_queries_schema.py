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


def test_links_file_matches_expanded_corpus_across_three_sources(queries_doc):
    """links.txt must have exactly one URL per real Kasten member (expanded
    corpus: psych 9, econ 11) AND its size must equal the sum of the
    queries.json _meta source_type_breakdown. Still catches a malformed /
    desynced links file or a breakdown that drifted from the real corpus."""
    slug, doc = queries_doc
    links = [
        ln.strip()
        for ln in (RAG_EVAL_V2 / slug / "links.txt").read_text(encoding="utf-8").splitlines()
        if ln.strip()
    ]
    expected = _EXPECTED_MEMBER_COUNT[slug]
    assert len(links) == expected, (
        f"{slug}: links.txt has {len(links)} URLs, expected {expected} "
        f"(real expanded-corpus member count)"
    )
    assert sum(doc["_meta"]["source_type_breakdown"].values()) == expected, (
        f"{slug}: _meta.source_type_breakdown sums to "
        f"{sum(doc['_meta']['source_type_breakdown'].values())}, expected "
        f"{expected} (drifted from the real corpus)"
    )
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


def test_expected_primary_citation_typed_per_class(queries_doc):
    """Every non-refusal query has a non-empty str|list[str] expected; every
    refusal query has an empty expected. Guards the iter-regen contract."""
    _slug, doc = queries_doc
    for q in doc["queries"]:
        exp = q["expected_primary_citation"]
        if q["class"] == "adversarial":
            assert exp == [], f"{q['qid']}: refusal must have empty expected"
            assert q["expected_minimum_citations"] == 0
            continue
        if isinstance(exp, list):
            assert exp, f"{q['qid']}: list expected must be non-empty"
            assert all(isinstance(e, str) and e.strip() for e in exp), (
                f"{q['qid']}: every list expected must be a non-empty str"
            )
        else:
            assert isinstance(exp, str) and exp.strip(), (
                f"{q['qid']}: scalar expected must be a non-empty str"
            )
        assert q["expected_minimum_citations"] >= 1


# Full real ingested member titles for the EXPANDED corpus (live-verified
# 2026-05-18 against rag.list_kasten_zettels: psych kasten
# fca95c6b-9797-41e6-9f29-b9a911f79de8 = 9 members; econ kasten
# 34090364-c731-41ed-abe5-e04ef34701e9 = 11 members). Used to simulate
# _resolve_expected (title substring -> zettel) WITHOUT a live DB, so the
# gold-regen contract is guarded in CI: every non-refusal expected substring
# must hit a real title. Includes the intentional off-topic skeleton members
# (Silk Road / FORTRESS II / Turán / HN sentence-comprehension) that no query
# points at — kept so the resolver simulation matches the live title map.
_REAL_TITLES = {
    "psychedelic-drugs": [
        "DMT History Science Consciousness",
        "Silk Road's Rise Fall",
        "Microdosing Psilocybin Benefits Practice",
        "r/consciousness explore if perceptual experiential changes",
        "r/philosophy seeks philosophical perspectives personal exper",
        "Psychedelics Problem-Solving Research",
        "r/philosophy argue psychedelic experiences fundamentally dis",
        "FORTRESS II: Software for Spin-2 BECs",
        "r/IAmA first-time heroin risks",
    ],
    "economics": [
        "BlackRock's Power Universal Ownership",
        "r/AskEconomics first-year economics teacher seeks interestin",
        "Turán Number for Spanning Linear Forests",
        "TheEconomist/big-mac-data",
        "Critique of Sentence Comprehension Test",
        "India's 1991 Economic Reforms Legacy",
        "r/AskHistorians understand Inca Empire described as",
        "Petrodollar System's Potential Erosion",
        "r/india present new evidence from working",
        "Economic Principles Explained",
        "Analysis of FT Piece: Rethinking Heterodox Policies in Polyc",
    ],
}

# Live-verified expanded-corpus sizes (rag.list_kasten_zettels, 2026-05-18).
# The links.txt + queries.json _meta must agree with these or the corpus has
# silently drifted (the exact regression this suite guards).
_EXPECTED_MEMBER_COUNT = {"psychedelic-drugs": 9, "economics": 11}


def _resolve(needle: str, titles: list[str]) -> str | None:
    """Mirror run_eval_v2._resolve_expected's per-needle case-insensitive
    title-substring match (first hit wins)."""
    n = needle.strip().lower()
    for t in titles:
        if n and n in t.lower():
            return t
    return None


def test_every_non_refusal_expected_resolves_against_real_titles(queries_doc):
    """Regression guard for the iter-resolve-[] bug: every non-refusal
    expected substring must match a real ingested title; refusal queries
    must resolve to nothing."""
    slug, doc = queries_doc
    titles = _REAL_TITLES[slug]
    for q in doc["queries"]:
        exp = q["expected_primary_citation"]
        needles = exp if isinstance(exp, list) else ([exp] if exp else [])
        hits = [t for n in needles if (t := _resolve(n, titles))]
        if q["class"] == "adversarial":
            assert not needles and not hits, (
                f"{slug} {q['qid']}: refusal must resolve to nothing"
            )
        else:
            assert len(hits) == len(needles) and len(hits) >= 1, (
                f"{slug} {q['qid']}: expected {needles!r} -> {hits!r} "
                f"(all must match a real ingested title)"
            )


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
