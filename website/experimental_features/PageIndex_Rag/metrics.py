from __future__ import annotations


def recall_at_k(retrieved: list[str], expected: list[str], k: int) -> float:
    if not expected:
        return 1.0 if not retrieved[:k] else 0.0
    return len(set(retrieved[:k]) & set(expected)) / len(set(expected))


def mrr(retrieved: list[str], expected: list[str]) -> float:
    expected_set = set(expected)
    for idx, node_id in enumerate(retrieved, start=1):
        if node_id in expected_set:
            return 1.0 / idx
    return 0.0


def ndcg_at_k(retrieved: list[str], expected: list[str], k: int) -> float:
    expected_set = set(expected)
    dcg = sum((1.0 / (idx + 1)) for idx, node_id in enumerate(retrieved[:k]) if node_id in expected_set)
    ideal_hits = min(len(expected_set), k)
    idcg = sum((1.0 / (idx + 1)) for idx in range(ideal_hits))
    return dcg / idcg if idcg else 1.0


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((pct / 100.0) * (len(ordered) - 1))))
    return ordered[index]
