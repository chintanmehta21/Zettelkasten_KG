from website.features.rag_pipeline.evaluation.kg_recommender import generate_recommendations
from website.features.rag_pipeline.evaluation.types import KGRecommendation


def test_generates_add_link_when_gold_is_distant():
    queries = [{"id": "q1", "gold_node_ids": ["yt-x"]}]
    answers = [{"query_id": "q1", "retrieved_node_ids": ["yt-a", "yt-b", "yt-c", "yt-d", "yt-e", "yt-f", "yt-x"]}]
    edges = []  # no edges from yt-x to anything in retrieval top-5
    recs = generate_recommendations(queries=queries, answers=answers, kasten_edges=edges,
                                     ragas_per_query={}, atomic_facts_per_query={}, kasten_nodes=[])
    types = [r.type for r in recs]
    assert "add_link" in types


def test_orphan_warning_for_zero_degree_node():
    nodes = [{"id": "yt-orphan", "tags": ["foo"]}]
    edges = []
    queries = []
    answers = []
    recs = generate_recommendations(queries=queries, answers=answers, kasten_edges=edges,
                                    ragas_per_query={}, atomic_facts_per_query={}, kasten_nodes=nodes)
    types = [r.type for r in recs]
    assert "orphan_warning" in types


def test_safety_brake_quarantines_when_too_many_of_one_type():
    queries = [{"id": f"q{i}", "gold_node_ids": [f"yt-x{i}"]} for i in range(6)]
    answers = [{"query_id": f"q{i}",
                "retrieved_node_ids": [f"yt-a{j}" for j in range(6)] + [f"yt-x{i}"]}
               for i in range(6)]
    edges = []
    recs = generate_recommendations(queries=queries, answers=answers, kasten_edges=edges,
                                    ragas_per_query={}, atomic_facts_per_query={}, kasten_nodes=[])
    add_link_recs = [r for r in recs if r.type == "add_link"]
    assert all(r.status == "quarantined" for r in add_link_recs), \
        "spec §8b: >5 of one type halts batch"
