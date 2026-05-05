# 06 Scorecard

**Composite:** 63.53  (weights={'chunking': 0.1, 'retrieval': 0.25, 'reranking': 0.2, 'synthesis': 0.45}, hash=422403f9d47a)

## Components
- chunking:    40.43
- retrieval:   76.90
- reranking:   49.31
- synthesis:   67.55

## RAGAS sidecar (0..100)
- faithfulness:      91.67
- answer_relevancy:  90.83

## Latency
- p50: 38580 ms
- p95: 46087 ms

## Coverage
- total queries:        14
- refusal-expected:     1
- eval_divergence:      False

## Holistic monitoring (iter-04)
- gold@1: 0.4286    gold@3: 0.4286    gold@8: 0.7143
- within_budget_rate: 0.2143
- refused_count: 3

### critic_verdict distribution
- supported: 7
- unknown: 2
- retry_budget_exceeded: 2
- partial: 2
- unsupported_no_retry: 1

### query_class distribution
- lookup: 5
- thematic: 4
- multi_hop: 3
- unknown: 2

### magnet-spotter (>=25% top-1 share)
- ⚠️ web-transformative-tools-for: top-1 in 3/14 queries

### burst pressure
- by_status: {'524': 7, '502': 3, '200': 2}
- 503 rate (target ≥0.08): 0.0
- 502 rate (target 0.0):  0.25

## Per-query (RAGAS overall is dataset-level)

| qid | retrieval | rerank | gold_in_retrieved | cites |
|---|---:|---:|:-:|---:|
| q1 | 0.0 | 20.0 | — | 0 |
| q2 | 100.0 | 100.0 | ✓ | 1 |
| q3 | 140.0 | 100.0 | ✓ | 1 |
| q4 | 80.0 | 80.7 | ✓ | 1 |
| q5 | 0.0 | 20.0 | — | 0 |
| q6 | 64.2 | 31.5 | ✓ | 3 |
| q7 | 77.5 | 41.7 | ✓ | 4 |
| q8 | 77.5 | 41.7 | ✓ | 4 |
| q9 | 0.0 | 0.0 | — | 0 |
| q10 | 0.0 | 0.0 | ✓ | 1 |
| q11 | 140.0 | 100.0 | ✓ | 1 |
| q12 | 117.5 | 21.5 | ✓ | 4 |
| q13 | 140.0 | 66.7 | ✓ | 4 |
| q14 | 140.0 | 66.7 | ✓ | 4 |
