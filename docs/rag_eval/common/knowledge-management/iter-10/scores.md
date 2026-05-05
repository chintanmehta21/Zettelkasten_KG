# 06 Scorecard

**Composite:** 66.10  (weights={'chunking': 0.1, 'retrieval': 0.25, 'reranking': 0.2, 'synthesis': 0.45}, hash=422403f9d47a)

## Components
- chunking:    40.43
- retrieval:   78.26
- reranking:   59.75
- synthesis:   67.87

## RAGAS sidecar (0..100)
- faithfulness:      97.14
- answer_relevancy:  80.00

## Latency
- p50: 30016 ms
- p95: 36135 ms

## Coverage
- total queries:        14
- refusal-expected:     1
- eval_divergence:      False

## Holistic monitoring (iter-04)
- gold@1 (unconditional):  0.6429
- gold@1 within budget:    0.3571
- gold@3: 0.7143    gold@8: 0.8571
- within_budget_rate: 0.6429
- refused_count: 3

### critic_verdict distribution
- supported: 6
- partial: 4
- unsupported_no_retry: 3
- unsupported_with_gold_skip: 1

### query_class distribution
- lookup: 5
- thematic: 5
- multi_hop: 4

### magnet-spotter (>=25% top-1 share)
- (none — magnet bias under threshold)

### burst pressure
- by_status: {'503': 6, '502': 3, '200': 3}
- 503 rate (target ≥0.08): 0.5
- 502 rate (target 0.0):  0.25

## Per-query (RAGAS overall is dataset-level)

| qid | retrieval | rerank | gold_in_retrieved | cites |
|---|---:|---:|:-:|---:|
| q1 | 100.0 | 66.7 | ✓ | 4 |
| q2 | 100.0 | 100.0 | ✓ | 1 |
| q3 | 100.0 | 100.0 | ✓ | 1 |
| q4 | 80.0 | 80.7 | ✓ | 1 |
| q5 | 84.0 | 47.5 | — | 0 |
| q6 | 86.7 | 68.5 | ✓ | 3 |
| q7 | 85.0 | 48.2 | ✓ | 4 |
| q8 | 80.0 | 41.7 | ✓ | 4 |
| q9 | 0.0 | 0.0 | — | 0 |
| q10 | 0.0 | 0.0 | — | 0 |
| q11 | 100.0 | 100.0 | ✓ | 1 |
| q12 | 80.0 | 41.7 | ✓ | 3 |
| q13 | 100.0 | 66.7 | ✓ | 4 |
| q14 | 100.0 | 75.0 | ✓ | 2 |
