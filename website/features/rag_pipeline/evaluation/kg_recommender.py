"""Generate kg_recommendations.json from eval results."""
from __future__ import annotations

from website.features.rag_pipeline.evaluation.types import KGRecommendation

_SAFETY_BRAKE_MAX_PER_TYPE = 5


def generate_recommendations(
    *,
    queries: list[dict],
    answers: list[dict],
    kasten_edges: list[dict],
    ragas_per_query: dict[str, dict],
    atomic_facts_per_query: dict[str, list[str]],
    kasten_nodes: list[dict],
) -> list[KGRecommendation]:
    recs: list[KGRecommendation] = []

    # add_link: gold node ranked > 5 AND graph-distant from retrieval top-1
    edge_set = {(e["source_node_id"], e["target_node_id"]) for e in kasten_edges}
    edge_set |= {(t, s) for s, t in edge_set}

    for q, a in zip(queries, answers):
        retrieved = a["retrieved_node_ids"]
        for gold in q["gold_node_ids"]:
            if gold in retrieved and retrieved.index(gold) > 4 and retrieved:
                top = retrieved[0]
                if (gold, top) not in edge_set and gold != top:
                    recs.append(KGRecommendation(
                        type="add_link",
                        payload={"from_node": top, "to_node": gold, "suggested_relation": "rag_eval_proximity"},
                        evidence_query_ids=[q["id"]],
                        confidence=0.7,
                        status="auto_apply",
                    ))

    # reingest_node: faithfulness < 0.5 for cited node
    for q, a in zip(queries, answers):
        ragas = ragas_per_query.get(q["id"], {})
        if ragas.get("faithfulness", 1.0) < 0.5:
            for cite in a.get("citations", []):
                recs.append(KGRecommendation(
                    type="reingest_node",
                    payload={"node_id": cite["node_id"], "low_faithfulness_count": 1},
                    evidence_query_ids=[q["id"]],
                    confidence=0.6,
                    status="quarantined",
                ))

    # orphan_warning: nodes with zero degree
    deg: dict[str, int] = {}
    for e in kasten_edges:
        deg[e["source_node_id"]] = deg.get(e["source_node_id"], 0) + 1
        deg[e["target_node_id"]] = deg.get(e["target_node_id"], 0) + 1
    for n in kasten_nodes:
        if deg.get(n["id"], 0) == 0:
            recs.append(KGRecommendation(
                type="orphan_warning",
                payload={"node_id": n["id"], "current_tags": n.get("tags", [])},
                evidence_query_ids=[],
                confidence=1.0,
                status="auto_apply",
            ))

    # add_tag: atomic fact entity not in any Kasten Zettel's tags
    all_tags = {tag for n in kasten_nodes for tag in n.get("tags", [])}
    for q in queries:
        for fact in atomic_facts_per_query.get(q["id"], []):
            words = [w.lower().strip(",.") for w in fact.split() if w[0].isupper()]
            for w in words:
                if w and w not in all_tags and len(w) > 3:
                    # Only first node in answer's citations gets the suggestion
                    recs.append(KGRecommendation(
                        type="add_tag",
                        payload={"node_id": q["gold_node_ids"][0], "suggested_tag": w,
                                 "evidence_atomic_fact": fact},
                        evidence_query_ids=[q["id"]],
                        confidence=0.5,
                        status="quarantined",
                    ))
                    break  # one tag suggestion per fact

    # Safety brake: > MAX of any one type → quarantine all of that type
    by_type: dict[str, list[int]] = {}
    for idx, r in enumerate(recs):
        by_type.setdefault(r.type, []).append(idx)
    for t, idxs in by_type.items():
        if len(idxs) > _SAFETY_BRAKE_MAX_PER_TYPE:
            for i in idxs:
                recs[i] = recs[i].model_copy(update={"status": "quarantined"})

    return recs
